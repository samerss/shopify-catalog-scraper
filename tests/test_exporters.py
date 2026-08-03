"""Tests for the export formats and the filter/sort/group helpers."""

import csv
import json
import os
import tempfile
import unittest

from shopify_catalog_scraper.exporters import (
    CSV_COLUMNS,
    write_csv,
    write_json,
    write_jsonl,
    write_markdown,
    write_products,
    write_text,
)
from shopify_catalog_scraper.filters import filter_products, group_products, sort_products
from shopify_catalog_scraper.models import Product


def build(product_id, title, price, product_type="Widgets", vendor="ACME",
          available=True, compare_at=None, tags=None):
    return Product.from_api(
        {
            "id": product_id,
            "title": title,
            "handle": title.lower().replace(" ", "-"),
            "vendor": vendor,
            "product_type": product_type,
            "tags": tags or [],
            "body_html": "<table><tr><td>Spec</td><td>Value</td></tr></table>",
            "options": [{"name": "Color", "values": ["Red"]}],
            "variants": [
                {
                    "id": product_id * 10,
                    "title": "Default",
                    "price": str(price),
                    "compare_at_price": str(compare_at) if compare_at else None,
                    "available": available,
                    "option1": "Red",
                }
            ],
        },
        store_url="https://shop.example.com",
    )


PRODUCTS = [
    build(1, "Cheap Widget", 10, available=True, compare_at=20),
    build(2, "Pricey Widget", 100, available=False),
    build(3, "Gadget", 50, product_type="Gadgets", vendor="Other", tags=["sale"]),
    build(4, "Untyped Thing", 25, product_type=""),
]


class ExporterTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def path(self, name):
        return os.path.join(self.dir, name)

    def read(self, name):
        with open(self.path(name), encoding="utf-8-sig") as handle:
            return handle.read()


class TestCsv(ExporterTestCase):
    def test_writes_one_row_per_variant(self):
        rows = write_csv(PRODUCTS, self.path("out.csv"), currency="USD")
        self.assertEqual(rows, 4)
        with open(self.path("out.csv"), encoding="utf-8-sig", newline="") as handle:
            records = list(csv.DictReader(handle))
        self.assertEqual(len(records), 4)
        self.assertEqual(list(records[0].keys()), CSV_COLUMNS)

    def test_sale_columns_are_computed(self):
        write_csv(PRODUCTS, self.path("out.csv"))
        with open(self.path("out.csv"), encoding="utf-8-sig", newline="") as handle:
            records = {r["title"]: r for r in csv.DictReader(handle)}
        self.assertEqual(records["Cheap Widget"]["on_sale"], "Yes")
        self.assertEqual(records["Cheap Widget"]["discount_pct"], "50")
        self.assertEqual(records["Pricey Widget"]["on_sale"], "No")
        self.assertEqual(records["Pricey Widget"]["discount_pct"], "")

    def test_stock_column(self):
        write_csv(PRODUCTS, self.path("out.csv"))
        with open(self.path("out.csv"), encoding="utf-8-sig", newline="") as handle:
            records = {r["title"]: r for r in csv.DictReader(handle)}
        self.assertEqual(records["Cheap Widget"]["in_stock"], "Yes")
        self.assertEqual(records["Pricey Widget"]["in_stock"], "No")

    def test_bom_present_by_default(self):
        write_csv(PRODUCTS, self.path("out.csv"))
        with open(self.path("out.csv"), "rb") as handle:
            self.assertTrue(handle.read(3) == b"\xef\xbb\xbf")

    def test_bom_can_be_disabled(self):
        write_csv(PRODUCTS, self.path("nobom.csv"), bom=False)
        with open(self.path("nobom.csv"), "rb") as handle:
            self.assertFalse(handle.read(3) == b"\xef\xbb\xbf")

    def test_unicode_survives_round_trip(self):
        product = build(9, "Café Ünïcode 日本", 5)
        write_csv([product], self.path("u.csv"))
        self.assertIn("Café Ünïcode 日本", self.read("u.csv"))


class TestJson(ExporterTestCase):
    def test_json_document_structure(self):
        write_json(PRODUCTS, self.path("out.json"), store_url="https://shop.example.com", currency="USD")
        with open(self.path("out.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["product_count"], 4)
        self.assertEqual(payload["in_stock_count"], 3)
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(len(payload["products"]), 4)

    def test_jsonl_is_one_object_per_line(self):
        write_jsonl(PRODUCTS, self.path("out.jsonl"))
        lines = [row for row in self.read("out.jsonl").splitlines() if row.strip()]
        self.assertEqual(len(lines), 4)
        for line in lines:
            self.assertIn("title", json.loads(line))


class TestTextCatalog(ExporterTestCase):
    def test_header_counts(self):
        write_text(PRODUCTS, self.path("out.txt"), store_url="https://shop.example.com")
        text = self.read("out.txt")
        self.assertIn("Products: 4 total | 3 in stock | 1 out of stock", text)

    def test_entries_and_sections(self):
        write_text(PRODUCTS, self.path("out.txt"), currency="USD")
        text = self.read("out.txt")
        self.assertEqual(text.count("PRODUCT: "), 4)
        self.assertIn("### WIDGETS (2 products)", text)
        self.assertIn("### GADGETS (1 products)", text)
        self.assertIn("### OTHER (1 products)", text)  # empty product_type

    def test_entry_fields(self):
        write_text(PRODUCTS, self.path("out.txt"), currency="USD")
        text = self.read("out.txt")
        self.assertIn("  Brand: ACME", text)
        self.assertIn("  Price: 10 USD", text)
        self.assertIn("  Colors: Red", text)
        self.assertIn("  Availability: In stock", text)
        self.assertIn("  Availability: Out of stock", text)
        self.assertIn("  Specs: Spec: Value", text)
        self.assertIn("  Link: https://shop.example.com/products/cheap-widget", text)

    def test_sale_annotation(self):
        write_text(PRODUCTS, self.path("out.txt"))
        self.assertIn("(on sale, up to 50% off)", self.read("out.txt"))

    def test_custom_notes_appear_in_header(self):
        write_text(PRODUCTS, self.path("out.txt"), notes=["Call 19857 for help."])
        self.assertIn("Call 19857 for help.", self.read("out.txt"))

    def test_group_by_none_has_no_sections(self):
        write_text(PRODUCTS, self.path("flat.txt"), group_by="none")
        self.assertNotIn("###", self.read("flat.txt"))

    def test_markdown_output(self):
        write_markdown(PRODUCTS, self.path("out.md"), store_url="https://shop.example.com")
        text = self.read("out.md")
        self.assertIn("# Product catalog", text)
        self.assertIn("[Cheap Widget](https://shop.example.com/products/cheap-widget)", text)


class TestDispatch(ExporterTestCase):
    def test_every_format_writes_a_file(self):
        for fmt in ("csv", "json", "jsonl", "txt", "md"):
            path = self.path("out." + fmt)
            write_products(PRODUCTS, path, fmt, store_url="https://shop.example.com")
            self.assertTrue(os.path.getsize(path) > 0, fmt)

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            write_products(PRODUCTS, self.path("x.bin"), "xml")


class TestFilters(unittest.TestCase):
    def test_in_stock_only(self):
        self.assertEqual(len(filter_products(PRODUCTS, in_stock_only=True)), 3)

    def test_on_sale_only(self):
        result = filter_products(PRODUCTS, on_sale_only=True)
        self.assertEqual([p.title for p in result], ["Cheap Widget"])

    def test_vendor_filter_is_case_insensitive(self):
        self.assertEqual(len(filter_products(PRODUCTS, vendors=["acme"])), 3)

    def test_type_filter(self):
        self.assertEqual(len(filter_products(PRODUCTS, types=["Gadgets"])), 1)

    def test_tag_filter(self):
        self.assertEqual(len(filter_products(PRODUCTS, tags=["sale"])), 1)

    def test_search_matches_substring(self):
        self.assertEqual(len(filter_products(PRODUCTS, search="widget")), 2)

    def test_price_bounds(self):
        self.assertEqual(len(filter_products(PRODUCTS, min_price=26)), 2)
        self.assertEqual(len(filter_products(PRODUCTS, max_price=25)), 2)

    def test_combined_filters(self):
        result = filter_products(PRODUCTS, in_stock_only=True, max_price=30)
        self.assertEqual({p.title for p in result}, {"Cheap Widget", "Untyped Thing"})

    def test_no_filters_returns_everything(self):
        self.assertEqual(len(filter_products(PRODUCTS)), 4)


class TestSortAndGroup(unittest.TestCase):
    def test_sort_by_price(self):
        titles = [p.title for p in sort_products(PRODUCTS, "price")]
        self.assertEqual(titles[0], "Cheap Widget")
        self.assertEqual(titles[-1], "Pricey Widget")

    def test_sort_reverse(self):
        self.assertEqual(sort_products(PRODUCTS, "price", reverse=True)[0].title, "Pricey Widget")

    def test_sort_by_title(self):
        self.assertEqual(sort_products(PRODUCTS, "title")[0].title, "Cheap Widget")

    def test_sort_by_discount(self):
        self.assertEqual(sort_products(PRODUCTS, "discount")[0].title, "Cheap Widget")

    def test_products_without_price_sort_last(self):
        priceless = Product.from_api({"id": 99, "title": "No Price", "variants": []})
        ordered = sort_products(list(PRODUCTS) + [priceless], "price")
        self.assertEqual(ordered[-1].title, "No Price")

    def test_sort_none_preserves_order(self):
        self.assertEqual(
            [p.id for p in sort_products(PRODUCTS, "none")], [p.id for p in PRODUCTS]
        )

    def test_unknown_sort_key_raises(self):
        with self.assertRaises(ValueError):
            sort_products(PRODUCTS, "color")

    def test_group_by_type_puts_empty_type_in_other(self):
        groups = group_products(PRODUCTS, "type")
        self.assertEqual(sorted(groups), ["GADGETS", "OTHER", "WIDGETS"])
        self.assertEqual(len(groups["WIDGETS"]), 2)

    def test_group_by_vendor(self):
        self.assertEqual(sorted(group_products(PRODUCTS, "vendor")), ["ACME", "OTHER"])

    def test_grouping_never_loses_products(self):
        groups = group_products(PRODUCTS, "type")
        self.assertEqual(sum(len(v) for v in groups.values()), len(PRODUCTS))


if __name__ == "__main__":
    unittest.main()
