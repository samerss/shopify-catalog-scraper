"""Filtering, sorting and grouping helpers for product collections."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Sequence

from .models import Product

__all__ = ["filter_products", "sort_products", "group_products", "SORT_KEYS", "GROUP_KEYS"]

#: Accepted values for ``sort_products(key=...)``.
SORT_KEYS = ("price", "title", "vendor", "type", "created", "updated", "discount", "none")

#: Accepted values for ``group_products(key=...)``.
GROUP_KEYS = ("type", "vendor", "none")

_UNGROUPED = "OTHER"


def filter_products(
    products: Iterable[Product],
    in_stock_only: bool = False,
    on_sale_only: bool = False,
    vendors: Optional[Sequence[str]] = None,
    types: Optional[Sequence[str]] = None,
    search: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    tags: Optional[Sequence[str]] = None,
) -> List[Product]:
    """Return the products matching every supplied condition.

    All text comparisons are case-insensitive. ``vendors``, ``types`` and
    ``tags`` match exactly (after lowercasing); ``search`` is a substring match
    against the title. Price bounds compare against the product's lowest
    variant price, so a product is kept when *any* of its variants qualifies.
    """
    vendor_set = {v.strip().lower() for v in vendors} if vendors else None
    type_set = {t.strip().lower() for t in types} if types else None
    tag_set = {t.strip().lower() for t in tags} if tags else None
    needle = search.strip().lower() if search else None

    kept: List[Product] = []
    for product in products:
        if in_stock_only and not product.in_stock:
            continue
        if on_sale_only and not product.on_sale:
            continue
        if vendor_set is not None and product.vendor.lower() not in vendor_set:
            continue
        if type_set is not None and product.product_type.lower() not in type_set:
            continue
        if tag_set is not None and not tag_set.intersection(t.lower() for t in product.tags):
            continue
        if needle and needle not in product.title.lower():
            continue
        if min_price is not None:
            price = product.price_max
            if price is None or price < min_price:
                continue
        if max_price is not None:
            price = product.price_min
            if price is None or price > max_price:
                continue
        kept.append(product)
    return kept


def _sort_key(key: str) -> Callable[[Product], object]:
    if key == "price":
        # Products with no price sort last rather than crashing the comparison.
        return lambda p: (p.price_min is None, p.price_min or 0.0, p.title.lower())
    if key == "title":
        return lambda p: p.title.lower()
    if key == "vendor":
        return lambda p: (p.vendor.lower(), p.title.lower())
    if key == "type":
        return lambda p: (p.product_type.lower(), p.title.lower())
    if key == "created":
        return lambda p: p.created_at
    if key == "updated":
        return lambda p: p.updated_at
    if key == "discount":
        return lambda p: (-(p.max_discount_pct or 0), p.title.lower())
    raise ValueError("unknown sort key: {!r} (expected one of {})".format(key, ", ".join(SORT_KEYS)))


def sort_products(products: Sequence[Product], key: str = "price", reverse: bool = False) -> List[Product]:
    """Return a new list sorted by ``key``. ``"none"`` preserves feed order."""
    if key == "none":
        return list(products)
    return sorted(products, key=_sort_key(key), reverse=reverse)


def group_products(products: Sequence[Product], key: str = "type") -> "Dict[str, List[Product]]":
    """Group products into an ordered mapping of section name to products.

    Products with an empty grouping value are collected under ``OTHER`` so they
    are never silently dropped from the output. Section names are uppercased and
    ordered alphabetically.
    """
    if key == "none":
        return {"": list(products)}
    if key not in GROUP_KEYS:
        raise ValueError(
            "unknown group key: {!r} (expected one of {})".format(key, ", ".join(GROUP_KEYS))
        )
    attribute = "product_type" if key == "type" else "vendor"
    buckets: Dict[str, List[Product]] = {}
    for product in products:
        value = (getattr(product, attribute, "") or "").strip()
        name = value.upper() if value else _UNGROUPED
        buckets.setdefault(name, []).append(product)
    return {name: buckets[name] for name in sorted(buckets)}
