"""shopify-catalog-scraper -- export any Shopify store's catalogue.

A dependency-free Python library and CLI that reads a storefront's public
product feed and writes it out as CSV, JSON, JSONL, Markdown, or a plain-text
catalogue built for AI knowledge bases.

Quick start::

    from shopify_catalog_scraper import ShopifyClient, write_csv

    client = ShopifyClient("examplestore.com")
    products = client.fetch_all_products()
    write_csv(products, "catalog.csv", currency="USD")

    for product in products:
        if product.on_sale and product.in_stock:
            print(product.title, product.price_min, product.max_discount_pct)
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Samer"
__license__ = "MIT"

from .client import DEFAULT_USER_AGENT, MAX_PAGE_SIZE, ShopifyClient, normalize_store_url
from .errors import (
    AccessDeniedError,
    NotAShopifyStoreError,
    RateLimitedError,
    ScraperError,
    StoreUnreachableError,
)
from .exporters import (
    CSV_COLUMNS,
    FORMATS,
    write_csv,
    write_json,
    write_jsonl,
    write_markdown,
    write_products,
    write_text,
)
from .filters import filter_products, group_products, sort_products
from .html_text import extract_spec_pairs, html_to_text, split_html
from .models import Product, Variant, format_price

__all__ = [
    "__version__",
    "ShopifyClient",
    "normalize_store_url",
    "DEFAULT_USER_AGENT",
    "MAX_PAGE_SIZE",
    "Product",
    "Variant",
    "format_price",
    "html_to_text",
    "split_html",
    "extract_spec_pairs",
    "filter_products",
    "sort_products",
    "group_products",
    "write_csv",
    "write_json",
    "write_jsonl",
    "write_text",
    "write_markdown",
    "write_products",
    "CSV_COLUMNS",
    "FORMATS",
    "ScraperError",
    "StoreUnreachableError",
    "NotAShopifyStoreError",
    "AccessDeniedError",
    "RateLimitedError",
]
