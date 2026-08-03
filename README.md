# shopify-catalog-scraper

[![CI](https://github.com/samerss/shopify-catalog-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/samerss/shopify-catalog-scraper/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](pyproject.toml)

Export the **complete product catalog of any Shopify store** — every product, every variant, prices, stock status, discounts, colors, images and specifications — to CSV, JSON, JSONL, Markdown, or a clean plain-text catalog built for AI knowledge bases.

No API key. No browser. No dependencies. One command.

```bash
shopify-scraper examplestore.com
# Wrote csv (1810 records) -> examplestore-com-catalog-2026-08-03.csv
# Done. 1353 products, 1810 variants, 1200 in stock, 3 on sale.
```

---

## Why this exists

Most Shopify scrapers render pages in a headless browser and parse the HTML that comes back. That approach is slow, heavy, and breaks the moment a merchant changes theme — which they do.

This tool reads the storefront's **structured product feed** instead. Every Shopify store publishes one, it returns clean typed JSON, and it does not care what the site looks like. The result is a scraper that runs in seconds, survives redesigns, and needs nothing installed beyond Python itself.

The second problem it solves is messier. Shopify keeps product descriptions as raw HTML, and merchants paste in whatever their suppliers gave them: specification tables, marketing markup, inline styles, tracking scripts. Strip the tags naively and a spec table collapses into unreadable soup:

> Input 5V 3A Output 15W max Material ABS + PC Weight 268g

This tool's HTML engine recognises tables and flattens each row into a labelled pair, so the same product reads:

> `Input: 5V 3A | Output: 15W max | Material: ABS + PC | Weight: 268g`

That single difference is what makes the output usable as an AI knowledge base, a price sheet, or a supplier comparison — instead of a pile of text you still have to clean.

## Features

- **Full catalog extraction** — paginates through every product, de-duplicated by ID
- **Variant-level detail** — price, compare-at price, SKU, options, weight, stock, image
- **Discount intelligence** — computes `on_sale`, `discount_pct` and `savings` from compare-at pricing
- **Readable specifications** — HTML tables flattened to `label: value` pairs, capped on a word boundary
- **Five output formats** — `csv`, `json`, `jsonl`, `txt` (AI-ready catalog), `md`
- **Filtering and sorting** — by stock, sale, vendor, type, tag, title, price range
- **Collections** — scope a run to one collection handle, or list them all
- **Polite by default** — 0.5 s between requests, honest User-Agent, `Retry-After` respected
- **Robust** — exponential backoff on 5xx/429, clear errors for password-protected stores, and a guard that detects stores which ignore pagination instead of looping forever
- **Zero dependencies** — Python standard library only, 3.8 through 3.13
- **Library or CLI** — import it, or run it from a cron job

## Install

```bash
pip install git+https://github.com/samerss/shopify-catalog-scraper.git
```

Or clone and install in editable mode:

```bash
git clone https://github.com/samerss/shopify-catalog-scraper.git
cd shopify-catalog-scraper
pip install -e .
```

No install at all is also fine — the package has no dependencies:

```bash
git clone https://github.com/samerss/shopify-catalog-scraper.git
cd shopify-catalog-scraper
PYTHONPATH=src python -m shopify_catalog_scraper examplestore.com
```

## Quick start

```bash
# Whole catalog to CSV in the current directory
shopify-scraper examplestore.com

# AI-ready text catalog plus JSON, written to ./out
shopify-scraper examplestore.com -f txt -f json -o out/

# Only discounted, in-stock products, cheapest first
shopify-scraper examplestore.com --on-sale-only --in-stock-only --sort price

# A single collection, piped straight into jq
shopify-scraper examplestore.com --collection summer-sale -f jsonl --out - | jq .

# What collections does this store have?
shopify-scraper examplestore.com --list-collections
```

## Output formats

### CSV — one row per variant

29 columns, UTF-8 with a BOM so Excel opens non-Latin text correctly instead of turning it into mojibake (`--no-bom` if your parser dislikes it).

| product_id | title | vendor | price | compare_at_price | on_sale | discount_pct | in_stock | product_url |
|---|---|---|---|---|---|---|---|---|
| 101 | Fast Charger 65W | ACME | 1990 | 2490 | Yes | 20 | Yes | https://… |

Full column list: `product_id`, `variant_id`, `title`, `variant_title`, `vendor`, `product_type`, `description`, `sku`, `price`, `compare_at_price`, `currency`, `on_sale`, `discount_pct`, `savings`, `in_stock`, `option1`–`option3`, `colors`, `grams`, `requires_shipping`, `taxable`, `tags`, `product_url`, `image_url`, `created_at`, `updated_at`, `published_at`, `scraped_at_utc`.

### TXT — the AI knowledge base format

Designed to be dropped straight into a RAG pipeline or an assistant's knowledge base: predictable labels, one fact per line, a link on every entry.

```text
EXAMPLESTORE.COM PRODUCT CATALOG
Source: https://examplestore.com
Products: 1353 total | 1200 in stock | 153 out of stock
All prices in USD.
Generated: 2026-08-03 20:01:10 UTC
======================================================================

### CHARGERS (30 products)

PRODUCT: ACME Fast Charger 65W GaN
  Brand: ACME
  Price: 1,990 USD  (on sale, up to 20% off)
  Colors: Black, White
  Availability: In stock
  Specs: Input: 100-240V~50/60Hz | Output: 65W max | Material: ABS + PC | Weight: 268g | Compact gallium-nitride charger for laptops and phones.
  Link: https://examplestore.com/products/acme-fast-charger-65w-gan
```

Add your own instructions to the header for the assistant that will read the file:

```bash
shopify-scraper examplestore.com -f txt \
  --note "Share the Link when a customer asks about a product." \
  --note "If a product is out of stock, suggest calling 555-0100."
```

### JSON / JSONL / Markdown

`json` gives one document with metadata plus a `products` array. `jsonl` gives one product object per line for streaming pipelines. `md` gives headings and links for a wiki page.

## Python API

```python
from shopify_catalog_scraper import ShopifyClient, filter_products, write_csv

client = ShopifyClient("examplestore.com", delay=0.5)
products = client.fetch_all_products()

deals = filter_products(products, on_sale_only=True, in_stock_only=True)
for product in sorted(deals, key=lambda p: -(p.max_discount_pct or 0))[:10]:
    print(f"{product.max_discount_pct:>3}% off  {product.title}  ->  {product.url}")

write_csv(deals, "deals.csv", currency="USD")
```

Stream instead of loading everything into memory:

```python
for product in client.iter_products():
    if product.in_stock and (product.price_min or 0) < 50:
        print(product.title, product.price_min)
```

Use the HTML engine on its own:

```python
from shopify_catalog_scraper import html_to_text, extract_spec_pairs

html = "<table><tr><td>Weight</td><td>268g</td></tr></table><p>Very light.</p>"
html_to_text(html)         # 'Weight: 268g | Very light.'
extract_spec_pairs(html)   # ['Weight: 268g']
```

### Key objects

| Object | What you get |
|---|---|
| `ShopifyClient(store, ...)` | `fetch_all_products()`, `iter_products()`, `fetch_page()`, `fetch_collections()` |
| `Product` | `title`, `vendor`, `product_type`, `tags`, `url`, `colors`, `price_min`/`price_max`, `in_stock`, `on_sale`, `max_discount_pct`, `description()`, `to_dict()` |
| `Variant` | `sku`, `price`, `compare_at_price`, `on_sale`, `discount_pct`, `savings`, `available`, `option1`–`3` |

## CLI reference

**Output**

| Flag | Default | Description |
|---|---|---|
| `-f, --format` | `csv` | `csv`, `json`, `jsonl`, `txt`, `md`. Repeatable. |
| `-o, --out` | `.` | Output directory, explicit file path, or `-` for stdout |
| `--prefix` | store domain | Filename prefix |
| `--no-bom` | off | Omit the UTF-8 BOM from CSV |
| `--compact` | off | JSON without indentation |

**Content**

| Flag | Default | Description |
|---|---|---|
| `--desc-chars` | `800` | Truncate descriptions to N characters; `0` means no limit |
| `--no-description` | off | Omit descriptions entirely |
| `--currency` | *(none)* | Currency label, e.g. `USD`. Never guessed — see note below |
| `--group-by` | `type` | `type`, `vendor`, `none` (txt/md sections) |
| `--sort` | `price` | `price`, `title`, `vendor`, `type`, `created`, `updated`, `discount`, `none` |
| `--reverse` | off | Reverse the sort |
| `--title` | store domain | Heading for txt/md |
| `--note` | – | Extra header line for txt. Repeatable. |
| `--price-decimals` | `auto` | `auto`, `0`, `2` |

**Selection**

| Flag | Description |
|---|---|
| `--collection HANDLE` | Only this collection |
| `--in-stock-only` | Only purchasable products |
| `--on-sale-only` | Only discounted products |
| `--vendor`, `--type`, `--tag` | Keep matching products. Repeatable. |
| `--search TEXT` | Title contains TEXT |
| `--min-price`, `--max-price` | Price bounds |
| `--max-products N` | Keep at most N (reported, never silent) |

**Network**

| Flag | Default | Description |
|---|---|---|
| `--delay` | `0.5` | Seconds between page requests |
| `--page-size` | `250` | Products per request (Shopify caps at 250) |
| `--max-pages` | `200` | Runaway guard |
| `--timeout` | `30` | Request timeout |
| `--retries` | `3` | Retries per request |
| `--user-agent` | package UA | Identify yourself honestly |

**Other:** `-q/--quiet`, `--list-collections`, `--version`, `-h/--help`.

> **On currency:** the Shopify product feed does not report a currency code, so this tool never invents one. Pass `--currency` to label prices; leave it off and prices are written unlabelled.

## Real-world example: a daily catalog sync

The pattern this tool was extracted from — re-scrape every morning, regenerate an assistant's knowledge base, and email the result:

```python
# examples/daily_sync.py
from shopify_catalog_scraper import ShopifyClient, write_text, write_csv

client = ShopifyClient("examplestore.com")
products = client.fetch_all_products()

write_text(
    products, "catalog_LIVE.txt",
    store_url=client.store_url, currency="USD", group_by="type",
    notes=["Share the Link when a customer asks about a product."],
)
write_csv(products, "catalog.csv", currency="USD")

in_stock = sum(1 for p in products if p.in_stock)
print(f"{len(products)} products, {in_stock} in stock")
```

Run it from cron:

```cron
15 4 * * * /usr/bin/python3 /opt/catalog/daily_sync.py >> /var/log/catalog.log 2>&1
```

See [`examples/`](examples/) for the full versions, including a price-drop monitor that diffs today's run against yesterday's.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | No products, no matches after filtering, or a scrape error |
| `2` | Bad arguments |
| `130` | Interrupted |

Errors are typed, so library users can catch precisely what went wrong: `AccessDeniedError` (401/403 — store opted out or is password protected), `NotAShopifyStoreError` (404 or a non-JSON response), `RateLimitedError` (429 after retries), `StoreUnreachableError` (DNS, timeout, 5xx). All inherit from `ScraperError`.

## Please scrape responsibly

This tool reads an endpoint that Shopify stores publish publicly, and it only ever reads data that any visitor to the storefront can already see. That does not make everything fair game:

- **Respect the store's terms of service and its `robots.txt`.** Being technically reachable is not the same as being permitted.
- **Keep the default delay** unless the store is yours. Hammering someone's storefront costs them money and bandwidth.
- **Identify yourself.** The default User-Agent names this tool; if you run it at scale, put your own contact in `--user-agent` so a merchant can reach you.
- **If a store blocks you, stop.** A 401/403 is a decision, and this tool deliberately offers no way around it.
- **Mind the law.** Copying and republishing product descriptions or images may infringe copyright, and personal data protection rules may apply to what you collect. Competitive price monitoring is generally accepted; wholesale content copying is not.

You are responsible for how you use this software.

## Development

```bash
git clone https://github.com/samerss/shopify-catalog-scraper.git
cd shopify-catalog-scraper
python -m unittest discover -s tests -v     # 134 tests, no network required
```

The test suite stubs out `urlopen` entirely, so it runs offline and deterministically — including pathological cases like a store that ignores the `page` parameter and returns page one forever.

Contributions welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

Not affiliated with, endorsed by, or sponsored by Shopify Inc.
