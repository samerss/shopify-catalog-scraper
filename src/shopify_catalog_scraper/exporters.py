"""Write scraped products out as CSV, JSON, JSONL, Markdown or plain text.

Each exporter targets a different consumer:

``csv``
    One row per *variant*, for spreadsheets and BI tools. Written with a UTF-8
    BOM by default so Excel renders non-Latin characters correctly instead of
    turning them into mojibake.
``json`` / ``jsonl``
    One record per *product*, for feeding another program.
``txt``
    A grouped, human-readable catalogue. This format was designed as a
    knowledge-base document for retrieval-augmented AI assistants: predictable
    labels, one fact per line, and a direct product link on every entry.
``md``
    The same idea as ``txt`` but with Markdown headings and links, for pasting
    into a wiki or README.
"""

from __future__ import annotations

import contextlib
import csv
import datetime
import json
import sys
from typing import Any, Dict, Iterator, List, Optional, Sequence, TextIO

from .filters import group_products
from .models import Product, format_price

__all__ = [
    "CSV_COLUMNS",
    "FORMATS",
    "write_csv",
    "write_json",
    "write_jsonl",
    "write_text",
    "write_markdown",
    "write_products",
    "utc_timestamp",
]

#: Supported ``--format`` values.
FORMATS = ("csv", "json", "jsonl", "txt", "md")

#: Column order for the CSV export. One row per variant.
CSV_COLUMNS = [
    "product_id",
    "variant_id",
    "title",
    "variant_title",
    "vendor",
    "product_type",
    "description",
    "sku",
    "price",
    "compare_at_price",
    "currency",
    "on_sale",
    "discount_pct",
    "savings",
    "in_stock",
    "option1",
    "option2",
    "option3",
    "colors",
    "grams",
    "requires_shipping",
    "taxable",
    "tags",
    "product_url",
    "image_url",
    "created_at",
    "updated_at",
    "published_at",
    "scraped_at_utc",
]


def utc_timestamp() -> str:
    """Current UTC time as ``YYYY-MM-DD HH:MM:SS UTC``."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@contextlib.contextmanager
def _open_out(path: str, encoding: str = "utf-8", newline: str = "") -> Iterator[TextIO]:
    """Open ``path`` for writing, or yield stdout when ``path`` is ``"-"``."""
    if path == "-":
        yield sys.stdout
        return
    handle = open(path, "w", encoding=encoding, newline=newline)
    try:
        yield handle
    finally:
        handle.close()


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def write_csv(
    products: Sequence[Product],
    path: str,
    currency: str = "",
    max_chars: Optional[int] = 800,
    bom: bool = True,
    delimiter: str = ",",
) -> int:
    """Write one row per variant. Returns the number of rows written."""
    encoding = "utf-8-sig" if bom and path != "-" else "utf-8"
    rows = 0
    with _open_out(path, encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        scraped_at = utc_timestamp()
        for product in products:
            description = product.description(max_chars)
            tags = "; ".join(product.tags)
            colors = ", ".join(product.colors)
            variants = product.variants or [None]
            for variant in variants:
                if variant is None:
                    continue
                writer.writerow(
                    {
                        "product_id": product.id if product.id is not None else "",
                        "variant_id": variant.id if variant.id is not None else "",
                        "title": product.title,
                        "variant_title": variant.title,
                        "vendor": product.vendor,
                        "product_type": product.product_type,
                        "description": description,
                        "sku": variant.sku,
                        "price": variant.price if variant.price is not None else "",
                        "compare_at_price": (
                            variant.compare_at_price
                            if variant.compare_at_price is not None
                            else ""
                        ),
                        "currency": currency,
                        "on_sale": _yes_no(variant.on_sale),
                        "discount_pct": (
                            variant.discount_pct if variant.discount_pct is not None else ""
                        ),
                        "savings": variant.savings if variant.savings is not None else "",
                        "in_stock": _yes_no(variant.available),
                        "option1": variant.option1,
                        "option2": variant.option2,
                        "option3": variant.option3,
                        "colors": colors,
                        "grams": variant.grams if variant.grams is not None else "",
                        "requires_shipping": _yes_no(variant.requires_shipping),
                        "taxable": _yes_no(variant.taxable),
                        "tags": tags,
                        "product_url": product.url,
                        "image_url": variant.featured_image_url or product.image_url,
                        "created_at": product.created_at,
                        "updated_at": product.updated_at,
                        "published_at": product.published_at,
                        "scraped_at_utc": scraped_at,
                    }
                )
                rows += 1
    return rows


def _json_payload(
    products: Sequence[Product], store_url: str, currency: str, max_chars: Optional[int]
) -> Dict[str, Any]:
    return {
        "store": store_url,
        "currency": currency,
        "scraped_at_utc": utc_timestamp(),
        "product_count": len(products),
        "in_stock_count": sum(1 for p in products if p.in_stock),
        "products": [p.to_dict(max_chars) for p in products],
    }


def write_json(
    products: Sequence[Product],
    path: str,
    store_url: str = "",
    currency: str = "",
    max_chars: Optional[int] = 800,
    pretty: bool = True,
) -> int:
    """Write a single JSON document with metadata plus every product."""
    payload = _json_payload(products, store_url, currency, max_chars)
    with _open_out(path, newline="\n") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
        handle.write("\n")
    return len(products)


def write_jsonl(
    products: Sequence[Product], path: str, max_chars: Optional[int] = 800
) -> int:
    """Write one JSON object per line -- convenient for streaming pipelines."""
    with _open_out(path, newline="\n") as handle:
        for product in products:
            handle.write(json.dumps(product.to_dict(max_chars), ensure_ascii=False))
            handle.write("\n")
    return len(products)


def _entry_lines(
    product: Product,
    currency: str,
    max_chars: Optional[int],
    price_decimals: str,
    show_range: bool,
) -> List[str]:
    lines = ["PRODUCT: " + product.title]
    if product.vendor:
        lines.append("  Brand: " + product.vendor)

    low, high = product.price_min, product.price_max
    if low is None:
        price_text = "N/A"
    else:
        price_text = format_price(low, price_decimals)
        if show_range and high is not None and high > low:
            price_text += " - " + format_price(high, price_decimals)
        if currency:
            price_text += " " + currency
    if product.on_sale and product.max_discount_pct:
        price_text += "  (on sale, up to {}% off)".format(product.max_discount_pct)
    lines.append("  Price: " + price_text)

    colors = product.colors
    if colors:
        lines.append("  Colors: " + ", ".join(colors))
    lines.append("  Availability: " + ("In stock" if product.in_stock else "Out of stock"))
    description = product.description(max_chars)
    if description:
        lines.append("  Specs: " + description)
    if product.url:
        lines.append("  Link: " + product.url)
    return lines


def write_text(
    products: Sequence[Product],
    path: str,
    store_url: str = "",
    currency: str = "",
    max_chars: Optional[int] = 800,
    group_by: str = "type",
    title: Optional[str] = None,
    notes: Optional[Sequence[str]] = None,
    price_decimals: str = "auto",
    show_price_range: bool = True,
) -> int:
    """Write a grouped, human- and LLM-readable catalogue.

    Args:
        group_by: ``"type"``, ``"vendor"`` or ``"none"``.
        title: Heading for the document. Defaults to the store domain.
        notes: Extra lines placed in the header block -- handy for instructions
            aimed at an AI assistant reading this file, such as what to say when
            a product is out of stock.
    """
    heading = title or "{} PRODUCT CATALOG".format(
        store_url.split("://")[-1].upper() if store_url else "PRODUCT CATALOG"
    )
    in_stock = sum(1 for p in products if p.in_stock)
    header = [heading]
    if store_url:
        header.append("Source: {}".format(store_url))
    header.append(
        "Products: {} total | {} in stock | {} out of stock".format(
            len(products), in_stock, len(products) - in_stock
        )
    )
    if currency:
        header.append("All prices in {}.".format(currency))
    header.append("Generated: {}".format(utc_timestamp()))
    for note in notes or []:
        header.append(note)
    header.append("=" * 70)

    with _open_out(path, newline="\n") as handle:
        handle.write("\n".join(header) + "\n\n")
        for section, items in group_products(products, group_by).items():
            if section:
                handle.write("### {} ({} products)\n\n".format(section, len(items)))
            for product in items:
                lines = _entry_lines(
                    product, currency, max_chars, price_decimals, show_price_range
                )
                handle.write("\n".join(lines) + "\n\n")
    return len(products)


def write_markdown(
    products: Sequence[Product],
    path: str,
    store_url: str = "",
    currency: str = "",
    max_chars: Optional[int] = 800,
    group_by: str = "type",
    title: Optional[str] = None,
    price_decimals: str = "auto",
) -> int:
    """Write the catalogue as Markdown with headings and links."""
    heading = title or "Product catalog"
    in_stock = sum(1 for p in products if p.in_stock)
    with _open_out(path, newline="\n") as handle:
        handle.write("# {}\n\n".format(heading))
        if store_url:
            handle.write("Source: <{}>\n\n".format(store_url))
        handle.write(
            "{} products, {} in stock. Generated {}.\n\n".format(
                len(products), in_stock, utc_timestamp()
            )
        )
        for section, items in group_products(products, group_by).items():
            if section:
                handle.write("## {} ({})\n\n".format(section.title(), len(items)))
            for product in items:
                name = product.title.replace("|", "\\|")
                handle.write(
                    "### [{}]({})\n\n".format(name, product.url) if product.url
                    else "### {}\n\n".format(name)
                )
                facts = []
                if product.vendor:
                    facts.append("**Brand:** {}".format(product.vendor))
                if product.price_min is not None:
                    price = format_price(product.price_min, price_decimals)
                    facts.append(
                        "**Price:** {}{}".format(price, " " + currency if currency else "")
                    )
                facts.append(
                    "**Availability:** {}".format(
                        "In stock" if product.in_stock else "Out of stock"
                    )
                )
                if product.colors:
                    facts.append("**Colors:** {}".format(", ".join(product.colors)))
                handle.write(" · ".join(facts) + "\n\n")
                description = product.description(max_chars)
                if description:
                    handle.write(description + "\n\n")
    return len(products)


def write_products(
    products: Sequence[Product],
    path: str,
    fmt: str,
    store_url: str = "",
    currency: str = "",
    max_chars: Optional[int] = 800,
    group_by: str = "type",
    title: Optional[str] = None,
    notes: Optional[Sequence[str]] = None,
    bom: bool = True,
    pretty: bool = True,
    price_decimals: str = "auto",
) -> int:
    """Dispatch to the exporter named by ``fmt``."""
    if fmt == "csv":
        return write_csv(products, path, currency, max_chars, bom=bom)
    if fmt == "json":
        return write_json(products, path, store_url, currency, max_chars, pretty=pretty)
    if fmt == "jsonl":
        return write_jsonl(products, path, max_chars)
    if fmt == "txt":
        return write_text(
            products,
            path,
            store_url,
            currency,
            max_chars,
            group_by=group_by,
            title=title,
            notes=notes,
            price_decimals=price_decimals,
        )
    if fmt == "md":
        return write_markdown(
            products,
            path,
            store_url,
            currency,
            max_chars,
            group_by=group_by,
            title=title,
            price_decimals=price_decimals,
        )
    raise ValueError("unknown format: {!r} (expected one of {})".format(fmt, ", ".join(FORMATS)))
