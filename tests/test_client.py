"""Tests for the HTTP client, using a stubbed urlopen -- no network access."""

import io
import json
import unittest
import urllib.error
from unittest import mock

from shopify_catalog_scraper.client import ShopifyClient, normalize_store_url
from shopify_catalog_scraper.errors import (
    AccessDeniedError,
    NotAShopifyStoreError,
    RateLimitedError,
    StoreUnreachableError,
)


def make_product(product_id):
    return {
        "id": product_id,
        "title": "Product {}".format(product_id),
        "handle": "product-{}".format(product_id),
        "variants": [{"id": product_id * 10, "price": "10.00", "available": True}],
    }


class FakeResponse(io.BytesIO):
    """Minimal stand-in for the object returned by urlopen."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


def json_response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def http_error(code, headers=None):
    return urllib.error.HTTPError(
        url="https://shop.example.com/products.json",
        code=code,
        msg="error",
        hdrs=headers or {},
        fp=None,
    )


class TestNormalizeStoreUrl(unittest.TestCase):
    def test_adds_scheme_to_bare_domain(self):
        self.assertEqual(normalize_store_url("example.com"), "https://example.com")

    def test_strips_path_and_query(self):
        self.assertEqual(
            normalize_store_url("https://example.com/collections/all?page=2"),
            "https://example.com",
        )

    def test_preserves_http_scheme(self):
        self.assertEqual(normalize_store_url("http://example.com"), "http://example.com")

    def test_preserves_subdomain_and_port(self):
        self.assertEqual(
            normalize_store_url("shop.example.co.uk:8080"), "https://shop.example.co.uk:8080"
        )

    def test_rejects_empty_input(self):
        for value in ("", "   ", None):
            with self.assertRaises(ValueError):
                normalize_store_url(value)


class TestPagination(unittest.TestCase):
    def setUp(self):
        self.client = ShopifyClient("shop.example.com", delay=0, max_retries=0)

    def test_stops_on_short_page(self):
        pages = [
            json_response({"products": [make_product(i) for i in range(250)]}),
            json_response({"products": [make_product(1000 + i) for i in range(5)]}),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=pages) as opener:
            products = self.client.fetch_all_products()
        self.assertEqual(len(products), 255)
        self.assertEqual(opener.call_count, 2)

    def test_stops_on_empty_page(self):
        pages = [
            json_response({"products": [make_product(i) for i in range(250)]}),
            json_response({"products": []}),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=pages):
            products = self.client.fetch_all_products()
        self.assertEqual(len(products), 250)

    def test_store_that_ignores_page_param_terminates(self):
        # Pathological store: always returns a full first page. Without the
        # seen-id guard this would loop until max_pages.
        page = [make_product(i) for i in range(250)]
        responses = [json_response({"products": page}) for _ in range(10)]
        with mock.patch("urllib.request.urlopen", side_effect=responses) as opener:
            products = self.client.fetch_all_products(max_pages=10)
        self.assertEqual(len(products), 250)
        self.assertEqual(opener.call_count, 2)  # first page, then the repeat detected

    def test_duplicate_ids_across_pages_are_dropped(self):
        first = [make_product(i) for i in range(250)]
        second = [make_product(249), make_product(250)]  # 249 already seen
        responses = [json_response({"products": first}), json_response({"products": second})]
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            products = self.client.fetch_all_products()
        self.assertEqual(len(products), 251)
        self.assertEqual(len({p.id for p in products}), 251)

    def test_max_pages_is_respected(self):
        full = {"products": [make_product(i) for i in range(250)]}

        def endless(*args, **kwargs):
            # Fresh ids every call so the repeat-detector never fires.
            endless.counter += 1
            offset = endless.counter * 1000
            return json_response(
                {"products": [make_product(offset + i) for i in range(250)]}
            )

        endless.counter = 0
        with mock.patch("urllib.request.urlopen", side_effect=endless) as opener:
            products = self.client.fetch_all_products(max_pages=3)
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(len(products), 750)
        self.assertTrue(full)  # keep the fixture referenced

    def test_on_page_callback_receives_progress(self):
        responses = [json_response({"products": [make_product(1)]})]
        seen = []
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            self.client.fetch_all_products(on_page=lambda p, c, t: seen.append((p, c, t)))
        self.assertEqual(seen, [(1, 1, 1)])

    def test_page_size_is_capped_at_250(self):
        with mock.patch("urllib.request.urlopen", return_value=json_response({"products": []})) as opener:
            self.client.fetch_page(1, limit=9999)
        url = opener.call_args[0][0].full_url
        self.assertIn("limit=250", url)

    def test_collection_scoped_url(self):
        with mock.patch("urllib.request.urlopen", return_value=json_response({"products": []})) as opener:
            self.client.fetch_page(1, collection="summer-sale")
        url = opener.call_args[0][0].full_url
        self.assertIn("/collections/summer-sale/products.json", url)


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        self.client = ShopifyClient("shop.example.com", delay=0, max_retries=0)

    def test_403_raises_access_denied(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(403)):
            with self.assertRaises(AccessDeniedError):
                self.client.fetch_page(1)

    def test_401_raises_access_denied(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401)):
            with self.assertRaises(AccessDeniedError):
                self.client.fetch_page(1)

    def test_404_raises_not_a_shopify_store(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(404)):
            with self.assertRaises(NotAShopifyStoreError):
                self.client.fetch_page(1)

    def test_non_json_body_raises_not_a_shopify_store(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"<html>nope</html>")):
            with self.assertRaises(NotAShopifyStoreError):
                self.client.fetch_page(1)

    def test_json_without_products_key_raises(self):
        with mock.patch("urllib.request.urlopen", return_value=json_response({"errors": "x"})):
            with self.assertRaises(NotAShopifyStoreError):
                self.client.fetch_page(1)

    def test_429_raises_rate_limited_when_retries_exhausted(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(429)):
            with self.assertRaises(RateLimitedError):
                self.client.fetch_page(1)

    def test_connection_error_raises_store_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(StoreUnreachableError):
                self.client.fetch_page(1)

    def test_500_is_retried_then_succeeds(self):
        client = ShopifyClient("shop.example.com", delay=0, max_retries=2, backoff=1.0)
        responses = [http_error(500), json_response({"products": [make_product(1)]})]
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            with mock.patch("time.sleep"):
                page = client.fetch_page(1)
        self.assertEqual(len(page), 1)

    def test_500_raises_after_retries_exhausted(self):
        client = ShopifyClient("shop.example.com", delay=0, max_retries=1, backoff=1.0)
        with mock.patch("urllib.request.urlopen", side_effect=http_error(500)):
            with mock.patch("time.sleep"):
                with self.assertRaises(StoreUnreachableError):
                    client.fetch_page(1)

    def test_timeout_is_retried(self):
        client = ShopifyClient("shop.example.com", delay=0, max_retries=1, backoff=1.0)
        responses = [OSError("timed out"), json_response({"products": []})]
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            with mock.patch("time.sleep"):
                self.assertEqual(client.fetch_page(1), [])


class TestHeaders(unittest.TestCase):
    def test_user_agent_is_sent(self):
        client = ShopifyClient("shop.example.com", user_agent="my-bot/2.0", delay=0)
        with mock.patch("urllib.request.urlopen", return_value=json_response({"products": []})) as opener:
            client.fetch_page(1)
        request = opener.call_args[0][0]
        self.assertEqual(request.get_header("User-agent"), "my-bot/2.0")

    def test_extra_headers_are_merged(self):
        client = ShopifyClient(
            "shop.example.com", extra_headers={"X-Trace": "abc"}, delay=0
        )
        with mock.patch("urllib.request.urlopen", return_value=json_response({"products": []})) as opener:
            client.fetch_page(1)
        self.assertEqual(opener.call_args[0][0].get_header("X-trace"), "abc")


if __name__ == "__main__":
    unittest.main()
