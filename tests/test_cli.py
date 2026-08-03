"""End-to-end CLI tests with a stubbed network layer."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from shopify_catalog_scraper.cli import build_parser, main


def product(product_id, title="Item", price="10.00", available=True, ptype="Widgets"):
    return {
        "id": product_id,
        "title": "{} {}".format(title, product_id),
        "handle": "item-{}".format(product_id),
        "vendor": "ACME",
        "product_type": ptype,
        "body_html": "<p>Nice.</p>",
        "variants": [
            {"id": product_id * 10, "price": price, "available": available, "title": "Default"}
        ],
    }


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def feed(products):
    return FakeResponse(json.dumps({"products": products}).encode("utf-8"))


class TestParser(unittest.TestCase):
    def test_store_is_required(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])

    def test_defaults(self):
        args = build_parser().parse_args(["example.com"])
        self.assertEqual(args.desc_chars, 800)
        self.assertEqual(args.sort_key, "price")
        self.assertEqual(args.group_by, "type")
        self.assertEqual(args.delay, 0.5)
        self.assertIsNone(args.format)

    def test_repeatable_format_flag(self):
        args = build_parser().parse_args(["example.com", "-f", "csv", "-f", "txt"])
        self.assertEqual(args.format, ["csv", "txt"])

    def test_invalid_format_rejected(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["example.com", "-f", "xml"])


class TestMain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def run_cli(self, argv, responses):
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            with redirect_stderr(err):
                code = main(argv)
        return code, err.getvalue()

    def test_writes_csv_by_default(self):
        code, _ = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--delay", "0"],
            [feed([product(1), product(2)])],
        )
        self.assertEqual(code, 0)
        files = os.listdir(self.dir)
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].endswith(".csv"))
        self.assertIn("shop-example-com-catalog-", files[0])

    def test_multiple_formats_produce_multiple_files(self):
        code, _ = self.run_cli(
            ["shop.example.com", "-o", self.dir, "-f", "csv", "-f", "json", "-f", "txt", "--delay", "0"],
            [feed([product(1)])],
        )
        self.assertEqual(code, 0)
        extensions = sorted(os.path.splitext(f)[1] for f in os.listdir(self.dir))
        self.assertEqual(extensions, [".csv", ".json", ".txt"])

    def test_explicit_output_path_is_honoured(self):
        target = os.path.join(self.dir, "custom.json")
        code, _ = self.run_cli(
            ["shop.example.com", "-o", target, "-f", "json", "--delay", "0"],
            [feed([product(1)])],
        )
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(target))

    def test_stdout_output(self):
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=[feed([product(1)])]):
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(["shop.example.com", "-o", "-", "-f", "jsonl", "--delay", "0"])
        self.assertEqual(code, 0)
        self.assertIn('"title"', out.getvalue())

    def test_filters_are_applied(self):
        code, _ = self.run_cli(
            ["shop.example.com", "-o", self.dir, "-f", "jsonl", "--in-stock-only", "--delay", "0"],
            [feed([product(1, available=True), product(2, available=False)])],
        )
        self.assertEqual(code, 0)
        path = os.path.join(self.dir, os.listdir(self.dir)[0])
        with open(path, encoding="utf-8") as handle:
            lines = [row for row in handle if row.strip()]
        self.assertEqual(len(lines), 1)

    def test_max_products_truncation_is_reported(self):
        code, log = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--max-products", "1", "--delay", "0"],
            [feed([product(1), product(2), product(3)])],
        )
        self.assertEqual(code, 0)
        self.assertIn("Truncating to the first 1 of 3", log)

    def test_no_products_returns_error_code(self):
        code, log = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--delay", "0"], [feed([])]
        )
        self.assertEqual(code, 1)
        self.assertIn("No products", log)

    def test_filters_matching_nothing_returns_error_code(self):
        code, log = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--search", "zzz", "--delay", "0"],
            [feed([product(1)])],
        )
        self.assertEqual(code, 1)
        self.assertIn("none matched", log)

    def test_access_denied_is_reported_cleanly(self):
        error = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        code, log = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--delay", "0", "--retries", "0"], [error]
        )
        self.assertEqual(code, 1)
        self.assertIn("error:", log)

    def test_quiet_suppresses_progress(self):
        code, log = self.run_cli(
            ["shop.example.com", "-o", self.dir, "--quiet", "--delay", "0"],
            [feed([product(1)])],
        )
        self.assertEqual(code, 0)
        self.assertEqual(log, "")

    def test_no_description_flag(self):
        code, _ = self.run_cli(
            ["shop.example.com", "-o", self.dir, "-f", "jsonl", "--no-description", "--delay", "0"],
            [feed([product(1)])],
        )
        self.assertEqual(code, 0)
        path = os.path.join(self.dir, os.listdir(self.dir)[0])
        with open(path, encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual(record["description"], "")

    def test_list_collections(self):
        payload = FakeResponse(
            json.dumps(
                {"collections": [{"handle": "sale", "title": "Sale", "products_count": 12}]}
            ).encode()
        )
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen", side_effect=[payload]):
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = main(["shop.example.com", "--list-collections"])
        self.assertEqual(code, 0)
        self.assertIn("sale", out.getvalue())


if __name__ == "__main__":
    unittest.main()
