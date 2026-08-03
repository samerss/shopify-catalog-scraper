"""Command-line interface for shopify-catalog-scraper."""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .client import DEFAULT_USER_AGENT, MAX_PAGE_SIZE, ShopifyClient
from .errors import ScraperError
from .exporters import FORMATS, write_products
from .filters import GROUP_KEYS, SORT_KEYS, filter_products, sort_products
from .models import Product

__all__ = ["main", "build_parser"]

EPILOG = """\
examples:
  # whole catalogue to CSV
  shopify-scraper examplestore.com

  # AI-ready text catalogue plus JSON, into ./out
  shopify-scraper examplestore.com -f txt -f json -o out/

  # only discounted items that are in stock, cheapest first
  shopify-scraper examplestore.com --on-sale-only --in-stock-only --sort price

  # one collection, piped straight to another program
  shopify-scraper examplestore.com --collection sale -f jsonl --out - | jq .

Please scrape responsibly: this reads a public endpoint, but rate limits, the
store's robots.txt and its terms of service still apply.
"""


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (exposed for tests and documentation)."""
    parser = argparse.ArgumentParser(
        prog="shopify-scraper",
        description=(
            "Export the full product catalogue of any Shopify store to CSV, "
            "JSON, JSONL, Markdown or an AI-ready text file. No dependencies."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("store", help="Store URL or bare domain, e.g. examplestore.com")
    parser.add_argument(
        "--version", action="version", version="%(prog)s {}".format(__version__)
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "-f",
        "--format",
        action="append",
        choices=FORMATS,
        metavar="FMT",
        help=(
            "Output format, repeatable. One of: " + ", ".join(FORMATS) + ". "
            "Default: csv"
        ),
    )
    output.add_argument(
        "-o",
        "--out",
        default=".",
        help=(
            "Output directory, or an explicit file path when a single format is "
            "requested. Use '-' to write to stdout. Default: current directory"
        ),
    )
    output.add_argument(
        "--prefix",
        default=None,
        help="Filename prefix for generated files. Default: the store domain",
    )
    output.add_argument(
        "--no-bom",
        action="store_true",
        help="Omit the UTF-8 BOM from CSV output (the BOM helps Excel, hurts some parsers)",
    )
    output.add_argument(
        "--compact", action="store_true", help="Write JSON without indentation"
    )

    content = parser.add_argument_group("content")
    content.add_argument(
        "--desc-chars",
        type=int,
        default=800,
        metavar="N",
        help="Truncate descriptions to N characters; 0 means no limit. Default: 800",
    )
    content.add_argument(
        "--no-description",
        action="store_true",
        help="Omit product descriptions entirely",
    )
    content.add_argument(
        "--currency",
        default="",
        metavar="CODE",
        help=(
            "Currency label for prices, e.g. USD or EGP. The Shopify feed does "
            "not report currency, so nothing is guessed -- if you omit this, "
            "prices are written without a currency label."
        ),
    )
    content.add_argument(
        "--group-by",
        choices=GROUP_KEYS,
        default="type",
        help="Section grouping for txt/md output. Default: type",
    )
    content.add_argument(
        "--sort",
        choices=SORT_KEYS,
        default="price",
        dest="sort_key",
        help="Sort order. Default: price",
    )
    content.add_argument("--reverse", action="store_true", help="Reverse the sort order")
    content.add_argument("--title", default=None, help="Heading for txt/md output")
    content.add_argument(
        "--note",
        action="append",
        default=None,
        dest="notes",
        metavar="TEXT",
        help=(
            "Extra header line for txt output, repeatable. Useful for "
            "instructions to an AI assistant that will read the file."
        ),
    )
    content.add_argument(
        "--price-decimals",
        choices=("auto", "0", "2"),
        default="auto",
        help="Decimal places in txt/md prices. Default: auto",
    )

    selection = parser.add_argument_group("selection")
    selection.add_argument(
        "--collection", default=None, help="Only scrape this collection handle"
    )
    selection.add_argument(
        "--in-stock-only", action="store_true", help="Keep only purchasable products"
    )
    selection.add_argument(
        "--on-sale-only", action="store_true", help="Keep only discounted products"
    )
    selection.add_argument(
        "--vendor", action="append", default=None, help="Keep only this vendor, repeatable"
    )
    selection.add_argument(
        "--type",
        action="append",
        default=None,
        dest="product_type",
        help="Keep only this product type, repeatable",
    )
    selection.add_argument(
        "--tag", action="append", default=None, dest="tags", help="Keep only this tag, repeatable"
    )
    selection.add_argument("--search", default=None, help="Keep products whose title contains TEXT")
    selection.add_argument("--min-price", type=float, default=None, help="Minimum price")
    selection.add_argument("--max-price", type=float, default=None, help="Maximum price")
    selection.add_argument(
        "--max-products",
        type=int,
        default=None,
        metavar="N",
        help="Stop after N products have been kept",
    )

    network = parser.add_argument_group("network")
    network.add_argument(
        "--page-size",
        type=int,
        default=MAX_PAGE_SIZE,
        metavar="N",
        help="Products per request, max {}. Default: {}".format(MAX_PAGE_SIZE, MAX_PAGE_SIZE),
    )
    network.add_argument(
        "--max-pages", type=int, default=200, metavar="N", help="Page ceiling. Default: 200"
    )
    network.add_argument(
        "--delay",
        type=float,
        default=0.5,
        metavar="SECONDS",
        help="Pause between page requests. Default: 0.5",
    )
    network.add_argument(
        "--timeout", type=float, default=30.0, metavar="SECONDS", help="Request timeout. Default: 30"
    )
    network.add_argument(
        "--retries", type=int, default=3, metavar="N", help="Retries per request. Default: 3"
    )
    network.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header. Identify yourself honestly.",
    )

    logging_group = parser.add_argument_group("logging")
    logging_group.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )
    logging_group.add_argument(
        "--list-collections",
        action="store_true",
        help="Print the store's collection handles and exit",
    )
    return parser


def _resolve_paths(args: argparse.Namespace, formats: Sequence[str], domain: str) -> List[str]:
    """Work out where each requested format should be written."""
    if args.out == "-":
        return ["-"] * len(formats)
    prefix = args.prefix or domain.replace(".", "-")
    date = datetime.date.today().isoformat()
    _, extension = os.path.splitext(args.out)
    if extension and len(formats) == 1:
        return [args.out]
    directory = args.out
    if directory and directory != ".":
        os.makedirs(directory, exist_ok=True)
    return [
        os.path.join(directory, "{}-catalog-{}.{}".format(prefix, date, fmt)) for fmt in formats
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    formats = list(dict.fromkeys(args.format or ["csv"]))

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    try:
        client = ShopifyClient(
            args.store,
            timeout=args.timeout,
            max_retries=args.retries,
            delay=args.delay,
            user_agent=args.user_agent,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2  # pragma: no cover - parser.error exits

    domain = client.store_url.split("://")[-1]

    try:
        if args.list_collections:
            for collection in client.fetch_collections():
                print(
                    "{}\t{}\t{} products".format(
                        collection.get("handle", ""),
                        collection.get("title", ""),
                        collection.get("products_count", "?"),
                    )
                )
            return 0

        log("Scraping {}{} ...".format(client.store_url,
                                       " [collection: {}]".format(args.collection)
                                       if args.collection else ""))

        def on_page(page: int, count: int, total: int) -> None:
            log("  page {:>3}: {:>4} products (running total {})".format(page, count, total))

        products: List[Product] = []
        for product in client.iter_products(
            limit=args.page_size,
            max_pages=args.max_pages,
            collection=args.collection,
            on_page=on_page,
        ):
            products.append(product)

        if not products:
            log("No products returned. The store may be empty, password "
                "protected, or scoped to a collection that does not exist.")
            return 1

        selected = filter_products(
            products,
            in_stock_only=args.in_stock_only,
            on_sale_only=args.on_sale_only,
            vendors=args.vendor,
            types=args.product_type,
            search=args.search,
            min_price=args.min_price,
            max_price=args.max_price,
            tags=args.tags,
        )
        selected = sort_products(selected, key=args.sort_key, reverse=args.reverse)
        if args.max_products is not None and args.max_products >= 0:
            if len(selected) > args.max_products:
                log("Truncating to the first {} of {} matching products "
                    "(--max-products).".format(args.max_products, len(selected)))
                selected = selected[: args.max_products]

        if not selected:
            log("{} products scraped, but none matched the filters.".format(len(products)))
            return 1

        # 0 (or negative) means "no limit"; --no-description wins outright.
        max_chars = args.desc_chars if args.desc_chars and args.desc_chars > 0 else None
        if args.no_description:
            for product in selected:
                product.body_html = ""
        variants = sum(len(p.variants) for p in selected)
        in_stock = sum(1 for p in selected if p.in_stock)
        on_sale = sum(1 for p in selected if p.on_sale)

        for fmt, path in zip(formats, _resolve_paths(args, formats, domain)):
            written = write_products(
                selected,
                path,
                fmt,
                store_url=client.store_url,
                currency=args.currency,
                max_chars=max_chars,
                group_by=args.group_by,
                title=args.title,
                notes=args.notes,
                bom=not args.no_bom,
                pretty=not args.compact,
                price_decimals=args.price_decimals,
            )
            log("Wrote {} ({} records) -> {}".format(fmt, written, path))

        log(
            "Done. {} products, {} variants, {} in stock, {} on sale.".format(
                len(selected), variants, in_stock, on_sale
            )
        )
        return 0

    except ScraperError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
