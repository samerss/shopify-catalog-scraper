"""Price-drop monitor: diff today's catalog against the last snapshot.

Keeps a small JSON snapshot of variant prices between runs and reports what
changed: price drops, price rises, items that came back into stock, and products
that appeared or disappeared.

Run with:
    python examples/price_monitor.py examplestore.com

The first run has nothing to compare against, so it just writes the baseline.
"""

from __future__ import annotations

import json
import os
import sys

from shopify_catalog_scraper import ShopifyClient
from shopify_catalog_scraper.errors import ScraperError

SNAPSHOT = "price_snapshot.json"


def snapshot_of(products) -> dict:
    """Map ``"<product_id>:<variant_id>"`` to price, stock and title."""
    state = {}
    for product in products:
        for variant in product.variants:
            key = "{}:{}".format(product.id, variant.id)
            state[key] = {
                "title": product.title,
                "variant": variant.title,
                "price": variant.price,
                "available": variant.available,
                "url": product.url,
            }
    return state


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def main(store: str) -> int:
    try:
        client = ShopifyClient(store, delay=0.5)
        products = client.fetch_all_products()
    except ScraperError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1

    current = snapshot_of(products)
    previous = load(SNAPSHOT)

    if not previous:
        with open(SNAPSHOT, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        print("Baseline written: {} variants tracked.".format(len(current)))
        return 0

    drops, rises, restocked, sold_out = [], [], [], []
    for key, now in current.items():
        before = previous.get(key)
        if before is None:
            continue
        old_price, new_price = before.get("price"), now.get("price")
        if old_price is not None and new_price is not None:
            if new_price < old_price:
                drops.append((key, before, now))
            elif new_price > old_price:
                rises.append((key, before, now))
        if now.get("available") and not before.get("available"):
            restocked.append(now)
        elif before.get("available") and not now.get("available"):
            sold_out.append(now)

    added = [v for k, v in current.items() if k not in previous]
    removed = [v for k, v in previous.items() if k not in current]

    def show(label, rows):
        if rows:
            print("\n{} ({}):".format(label, len(rows)))
            for row in rows[:20]:
                print("  {}".format(row))

    if drops:
        print("\nPRICE DROPS ({}):".format(len(drops)))
        for _, before, now in sorted(
            drops, key=lambda d: (d[2]["price"] - d[1]["price"]) / d[1]["price"]
        )[:20]:
            pct = round((before["price"] - now["price"]) / before["price"] * 100)
            print(
                "  -{:>3}%  {} -> {}  {}  {}".format(
                    pct, before["price"], now["price"], now["title"], now["url"]
                )
            )

    show("PRICE RISES", ["{} {} -> {}".format(n["title"], b["price"], n["price"]) for _, b, n in rises])
    show("BACK IN STOCK", [r["title"] for r in restocked])
    show("SOLD OUT", [r["title"] for r in sold_out])
    show("NEW", [r["title"] for r in added])
    show("GONE", [r["title"] for r in removed])

    if not any([drops, rises, restocked, sold_out, added, removed]):
        print("No changes since the last run.")

    with open(SNAPSHOT, "w", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
