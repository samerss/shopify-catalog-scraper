# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-08-03

First public release. Extracted and generalised from a production catalog
pipeline that had been running daily against a live storefront of ~1,350
products and ~1,810 variants.

### Added

- `ShopifyClient` for the public product feed, with pagination, per-request
  retries, exponential backoff, `Retry-After` support and a configurable delay.
- Detection for storefronts that ignore the `page` parameter and return the
  first page indefinitely — pagination stops instead of looping forever.
- `Product` and `Variant` models that normalise the loosely-typed feed: prices
  become floats, missing keys get safe defaults, colour values are read from the
  declared option with a variant-level fallback.
- Discount intelligence: `on_sale`, `discount_pct` and `savings`, computed only
  when the compare-at price is strictly above the selling price.
- HTML-to-text engine that flattens specification tables into `label: value`
  pairs, drops `<script>`/`<style>` content, normalises whitespace, truncates on
  a word boundary, and falls back to a regex strip on unparseable markup.
- Exporters for CSV (one row per variant, UTF-8 BOM by default), JSON, JSONL,
  Markdown and a grouped plain-text catalog aimed at AI knowledge bases.
- Filtering by stock, sale status, vendor, product type, tag, title substring and
  price range; sorting by price, title, vendor, type, dates or discount depth;
  grouping by type or vendor with an `OTHER` bucket so nothing is dropped.
- CLI (`shopify-scraper`) covering every option, plus `--list-collections`,
  stdout output via `--out -`, and typed exit codes.
- Typed exception hierarchy: `AccessDeniedError`, `NotAShopifyStoreError`,
  `RateLimitedError`, `StoreUnreachableError`.
- 134 offline unit tests and doctests; CI across Python 3.8–3.13.

[Unreleased]: https://github.com/samerss/shopify-catalog-scraper/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/samerss/shopify-catalog-scraper/releases/tag/v1.0.0
