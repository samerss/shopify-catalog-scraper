"""Basic usage of the shopify_catalog_scraper Python API.

Run with:
    python examples/basic_usage.py examplestore.com
"""

from __future__ import annotations

import sys

from shopify_catalog_scraper import (
    ShopifyClient,
    filter_products,
    sort_products,
    write_csv,
    write_text,
)


def main(store: str) -> int:
    client = ShopifyClient(store, delay=0.5)

    print("Fetching {} ...".format(client.store_url))
    products = client.fetch_all_products(
        on_page=lambda page, count, total: print(
            "  page {}: {} products (total {})".format(page, count, total)
        )
    )
    if not products:
        print("No products returned.")
        return 1

    in_stock = [p for p in products if p.in_stock]
    variants = sum(len(p.variants) for p in products)
    print(
        "\n{} products, {} variants, {} in stock".format(
            len(products), variants, len(in_stock)
        )
    )

    # The ten deepest discounts currently available to buy.
    deals = sort_products(
        filter_products(products, on_sale_only=True, in_stock_only=True), "discount"
    )
    if deals:
        print("\nTop discounts:")
        for product in deals[:10]:
            print(
                "  {:>3}% off  {:<45.45}  {}".format(
                    product.max_discount_pct, product.title, product.url
                )
            )
    else:
        print("\nNothing on sale right now.")

    # What is this store mostly selling?
    counts = {}
    for product in products:
        counts[product.product_type or "(untyped)"] = (
            counts.get(product.product_type or "(untyped)", 0) + 1
        )
    print("\nLargest categories:")
    for name, count in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
        print("  {:>5}  {}".format(count, name))

    write_csv(products, "catalog.csv", currency="USD")
    write_text(products, "catalog.txt", store_url=client.store_url, currency="USD")
    print("\nWrote catalog.csv and catalog.txt")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
