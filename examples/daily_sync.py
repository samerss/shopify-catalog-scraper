"""Daily catalog sync: regenerate a knowledge-base file and report the totals.

This is the pattern the library was extracted from. A scheduled job re-scrapes
the store every morning, rewrites the text catalog that an AI assistant uses as
its knowledge base, and prints a summary line for the job log.

Run with:
    python examples/daily_sync.py examplestore.com

Schedule with cron:
    15 4 * * * /usr/bin/python3 /opt/catalog/daily_sync.py examplestore.com >> /var/log/catalog.log 2>&1

Two things make this safe to run unattended:

* The output is written to a temporary file and moved into place only after a
  sanity check passes, so a bad scrape never overwrites a good catalog.
* The sanity check compares against the previous run, because "the store
  returned 4 products today instead of 1,300" is a failure, not a catalog.
"""

from __future__ import annotations

import os
import sys
import tempfile

from shopify_catalog_scraper import ShopifyClient, write_csv, write_text
from shopify_catalog_scraper.errors import ScraperError

OUTPUT_TXT = "catalog_LIVE.txt"
OUTPUT_CSV = "catalog.csv"
CURRENCY = "USD"

#: Fail the run if the catalog shrinks by more than this fraction overnight.
MAX_SHRINK = 0.5

#: Extra header lines aimed at whatever assistant reads the text catalog.
ASSISTANT_NOTES = [
    "Share the Link when a customer asks about a product.",
    "If a product shows 'Out of stock', say it is currently unavailable.",
]


def previous_product_count(path: str) -> int:
    """Read the product count from the header of an existing catalog file."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as handle:
            for _ in range(12):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("Products:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def main(store: str) -> int:
    try:
        client = ShopifyClient(store, delay=0.5, max_retries=3)
        products = client.fetch_all_products()
    except ScraperError as exc:
        print("FAILED: {}".format(exc), file=sys.stderr)
        return 1

    if not products:
        print("FAILED: store returned no products", file=sys.stderr)
        return 1

    previous = previous_product_count(OUTPUT_TXT)
    if previous and len(products) < previous * MAX_SHRINK:
        print(
            "FAILED: catalog shrank from {} to {} products; keeping the old file".format(
                previous, len(products)
            ),
            file=sys.stderr,
        )
        return 1

    # Write to a temporary file first, then move it into place atomically.
    directory = os.path.dirname(os.path.abspath(OUTPUT_TXT))
    handle, temp_path = tempfile.mkstemp(dir=directory, suffix=".txt")
    os.close(handle)
    write_text(
        products,
        temp_path,
        store_url=client.store_url,
        currency=CURRENCY,
        group_by="type",
        notes=ASSISTANT_NOTES,
    )
    os.replace(temp_path, OUTPUT_TXT)
    write_csv(products, OUTPUT_CSV, currency=CURRENCY)

    in_stock = sum(1 for p in products if p.in_stock)
    on_sale = sum(1 for p in products if p.on_sale)
    print(
        "OK: {} products, {} variants, {} in stock, {} on sale (previous run: {})".format(
            len(products),
            sum(len(p.variants) for p in products),
            in_stock,
            on_sale,
            previous or "none",
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
