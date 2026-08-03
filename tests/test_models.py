"""Tests for the Product and Variant data models."""

import unittest

from shopify_catalog_scraper.models import Product, Variant, format_price, to_float

SAMPLE = {
    "id": 101,
    "title": "  Test Charger  ",
    "handle": "test-charger",
    "vendor": "ACME",
    "product_type": "Accessories",
    "tags": ["usb", "fast-charge"],
    "body_html": "<table><tr><td>Output</td><td>15W</td></tr></table><p>Charges fast.</p>",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-06-01T00:00:00Z",
    "published_at": "2024-01-02T00:00:00Z",
    "images": [{"src": "https://cdn.example.com/a.jpg"}, {"src": "https://cdn.example.com/b.jpg"}],
    "options": [{"name": "Color", "values": ["Black", "White"]}],
    "variants": [
        {
            "id": 1,
            "title": "Black",
            "sku": "SKU-B",
            "price": "100.00",
            "compare_at_price": "125.00",
            "available": True,
            "option1": "Black",
            "grams": 200,
            "requires_shipping": True,
            "taxable": True,
            "featured_image": {"src": "https://cdn.example.com/black.jpg"},
        },
        {
            "id": 2,
            "title": "White",
            "sku": "SKU-W",
            "price": "150.00",
            "compare_at_price": None,
            "available": False,
            "option1": "White",
        },
    ],
}


class TestToFloat(unittest.TestCase):
    def test_parses_numeric_strings(self):
        self.assertEqual(to_float("104.39"), 104.39)
        self.assertEqual(to_float(7), 7.0)

    def test_returns_none_for_garbage(self):
        for value in (None, "", "abc", [], {}):
            self.assertIsNone(to_float(value))


class TestFormatPrice(unittest.TestCase):
    def test_auto_drops_trailing_zeros(self):
        self.assertEqual(format_price(1990.0), "1,990")

    def test_auto_keeps_real_decimals(self):
        self.assertEqual(format_price(104.39), "104.39")

    def test_explicit_decimal_settings(self):
        self.assertEqual(format_price(104.39, "0"), "104")
        self.assertEqual(format_price(1990.0, "2"), "1,990.00")

    def test_none_is_empty_string(self):
        self.assertEqual(format_price(None), "")


class TestVariant(unittest.TestCase):
    def setUp(self):
        self.product = Product.from_api(SAMPLE, store_url="https://shop.example.com")
        self.black, self.white = self.product.variants

    def test_prices_parsed_as_floats(self):
        self.assertEqual(self.black.price, 100.0)
        self.assertEqual(self.black.compare_at_price, 125.0)

    def test_on_sale_and_discount(self):
        self.assertTrue(self.black.on_sale)
        self.assertEqual(self.black.discount_pct, 20)
        self.assertEqual(self.black.savings, 25.0)

    def test_variant_without_compare_at_is_not_on_sale(self):
        self.assertFalse(self.white.on_sale)
        self.assertIsNone(self.white.discount_pct)
        self.assertIsNone(self.white.savings)

    def test_compare_at_below_price_is_not_a_discount(self):
        variant = Variant.from_api({"price": "100", "compare_at_price": "80"})
        self.assertFalse(variant.on_sale)

    def test_compare_at_equal_to_price_is_not_a_discount(self):
        variant = Variant.from_api({"price": "100", "compare_at_price": "100"})
        self.assertFalse(variant.on_sale)

    def test_missing_fields_get_safe_defaults(self):
        variant = Variant.from_api({})
        self.assertIsNone(variant.price)
        self.assertFalse(variant.available)
        self.assertEqual(variant.sku, "")


class TestProduct(unittest.TestCase):
    def setUp(self):
        self.product = Product.from_api(SAMPLE, store_url="https://shop.example.com")

    def test_title_is_stripped(self):
        self.assertEqual(self.product.title, "Test Charger")

    def test_url_built_from_handle(self):
        self.assertEqual(self.product.url, "https://shop.example.com/products/test-charger")

    def test_price_range(self):
        self.assertEqual(self.product.price_min, 100.0)
        self.assertEqual(self.product.price_max, 150.0)

    def test_stock_rollup(self):
        self.assertTrue(self.product.in_stock)
        self.assertEqual(self.product.variants_in_stock, 1)

    def test_out_of_stock_when_no_variant_available(self):
        raw = dict(SAMPLE)
        raw["variants"] = [dict(v, available=False) for v in SAMPLE["variants"]]
        self.assertFalse(Product.from_api(raw).in_stock)

    def test_sale_rollup(self):
        self.assertTrue(self.product.on_sale)
        self.assertEqual(self.product.max_discount_pct, 20)

    def test_colors_from_option_values(self):
        self.assertEqual(self.product.colors, ["Black", "White"])

    def test_colors_fall_back_to_variants_when_values_empty(self):
        raw = dict(SAMPLE)
        raw["options"] = [{"name": "Colour", "values": []}]
        self.assertEqual(Product.from_api(raw).colors, ["Black", "White"])

    def test_no_colors_when_option_absent(self):
        raw = dict(SAMPLE)
        raw["options"] = [{"name": "Size", "values": ["S", "M"]}]
        self.assertEqual(Product.from_api(raw).colors, [])

    def test_description_flattens_specs(self):
        self.assertEqual(self.product.description(), "Output: 15W | Charges fast.")

    def test_description_respects_cap(self):
        self.assertLessEqual(len(self.product.description(10)), 11)

    def test_image_url_is_first_image(self):
        self.assertEqual(self.product.image_url, "https://cdn.example.com/a.jpg")

    def test_tags_string_is_split(self):
        raw = dict(SAMPLE)
        raw["tags"] = "one, two,three"
        self.assertEqual(Product.from_api(raw).tags, ["one", "two", "three"])

    def test_empty_product_does_not_raise(self):
        product = Product.from_api({})
        self.assertEqual(product.title, "")
        self.assertIsNone(product.price_min)
        self.assertFalse(product.in_stock)
        self.assertEqual(product.colors, [])
        self.assertEqual(product.description(), "")

    def test_to_dict_is_json_serialisable(self):
        import json

        payload = self.product.to_dict()
        json.dumps(payload)  # must not raise
        self.assertEqual(payload["id"], 101)
        self.assertEqual(len(payload["variants"]), 2)
        self.assertTrue(payload["variants"][0]["on_sale"])


if __name__ == "__main__":
    unittest.main()
