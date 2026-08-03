"""Typed representations of Shopify products and variants.

The public product feed returns loosely-typed JSON: prices arrive as strings,
optional keys go missing, and colour information lives in two different places
depending on how the merchant set the product up. These dataclasses normalise
all of that once, so the exporters and your own code can work with real numbers
and predictable attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .html_text import html_to_text

__all__ = ["Variant", "Product", "to_float", "format_price"]

#: Option names that identify a colour axis, lowercased.
COLOR_OPTION_NAMES = frozenset({"color", "colour", "colors", "colours"})


def to_float(value: Any) -> Optional[float]:
    """Best-effort numeric conversion. Returns ``None`` instead of raising.

    >>> to_float("104.39")
    104.39
    >>> to_float(None) is None
    True
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price(value: Optional[float], decimals: str = "auto") -> str:
    """Render a price with thousands separators.

    Args:
        value: The amount, or ``None``.
        decimals: ``"auto"`` drops ``.00`` on whole amounts, ``"0"`` always
            rounds to whole units, ``"2"`` always shows two decimal places.

    >>> format_price(1990.0)
    '1,990'
    >>> format_price(104.39)
    '104.39'
    >>> format_price(104.39, "0")
    '104'
    """
    if value is None:
        return ""
    if decimals == "0":
        return "{:,.0f}".format(value)
    if decimals == "2":
        return "{:,.2f}".format(value)
    if abs(value - round(value)) < 0.005:
        return "{:,.0f}".format(value)
    return "{:,.2f}".format(value)


@dataclass
class Variant:
    """A single purchasable variant of a product."""

    id: Optional[int] = None
    title: str = ""
    sku: str = ""
    price: Optional[float] = None
    compare_at_price: Optional[float] = None
    available: bool = False
    option1: str = ""
    option2: str = ""
    option3: str = ""
    grams: Optional[int] = None
    requires_shipping: bool = True
    taxable: bool = True
    position: Optional[int] = None
    featured_image_url: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_api(cls, raw: Dict[str, Any]) -> "Variant":
        """Build a :class:`Variant` from one entry of ``product["variants"]``."""
        image = raw.get("featured_image")
        image_url = ""
        if isinstance(image, dict):
            image_url = image.get("src") or ""
        return cls(
            id=raw.get("id"),
            title=raw.get("title") or "",
            sku=raw.get("sku") or "",
            price=to_float(raw.get("price")),
            compare_at_price=to_float(raw.get("compare_at_price")),
            available=bool(raw.get("available")),
            option1=str(raw.get("option1") or ""),
            option2=str(raw.get("option2") or ""),
            option3=str(raw.get("option3") or ""),
            grams=raw.get("grams") if isinstance(raw.get("grams"), int) else None,
            requires_shipping=bool(raw.get("requires_shipping", True)),
            taxable=bool(raw.get("taxable", True)),
            position=raw.get("position"),
            featured_image_url=image_url,
            created_at=raw.get("created_at") or "",
            updated_at=raw.get("updated_at") or "",
        )

    @property
    def on_sale(self) -> bool:
        """True when a compare-at price is set *above* the selling price.

        Merchants routinely leave ``compare_at_price`` equal to or below the
        real price, which is not a discount. Only a strictly higher compare-at
        value counts.
        """
        return (
            self.compare_at_price is not None
            and self.price is not None
            and self.compare_at_price > self.price
        )

    @property
    def discount_pct(self) -> Optional[int]:
        """Whole-number discount percentage, or ``None`` when not on sale."""
        if not self.on_sale or not self.compare_at_price:
            return None
        return int(round((self.compare_at_price - self.price) / self.compare_at_price * 100))

    @property
    def savings(self) -> Optional[float]:
        """Absolute amount saved versus the compare-at price."""
        if not self.on_sale:
            return None
        return round(self.compare_at_price - self.price, 2)


@dataclass
class Product:
    """A product together with all of its variants."""

    id: Optional[int] = None
    title: str = ""
    handle: str = ""
    vendor: str = ""
    product_type: str = ""
    tags: List[str] = field(default_factory=list)
    body_html: str = ""
    image_urls: List[str] = field(default_factory=list)
    options: List[Dict[str, Any]] = field(default_factory=list)
    variants: List[Variant] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    published_at: str = ""
    store_url: str = ""

    @classmethod
    def from_api(cls, raw: Dict[str, Any], store_url: str = "") -> "Product":
        """Build a :class:`Product` from one entry of the ``products`` array."""
        tags = raw.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        images = []
        for image in raw.get("images") or []:
            if isinstance(image, dict) and image.get("src"):
                images.append(image["src"])
        return cls(
            id=raw.get("id"),
            title=(raw.get("title") or "").strip(),
            handle=raw.get("handle") or "",
            vendor=(raw.get("vendor") or "").strip(),
            product_type=(raw.get("product_type") or "").strip(),
            tags=list(tags),
            body_html=raw.get("body_html") or "",
            image_urls=images,
            options=list(raw.get("options") or []),
            variants=[Variant.from_api(v) for v in (raw.get("variants") or [])],
            created_at=raw.get("created_at") or "",
            updated_at=raw.get("updated_at") or "",
            published_at=raw.get("published_at") or "",
            store_url=store_url.rstrip("/"),
        )

    # -- derived values ---------------------------------------------------

    @property
    def url(self) -> str:
        """Canonical storefront URL for the product."""
        if not self.handle:
            return ""
        base = self.store_url or ""
        return "{}/products/{}".format(base, self.handle) if base else "/products/" + self.handle

    @property
    def image_url(self) -> str:
        """First product image, or an empty string."""
        return self.image_urls[0] if self.image_urls else ""

    @property
    def prices(self) -> List[float]:
        """Every non-null variant price."""
        return [v.price for v in self.variants if v.price is not None]

    @property
    def price_min(self) -> Optional[float]:
        return min(self.prices) if self.prices else None

    @property
    def price_max(self) -> Optional[float]:
        return max(self.prices) if self.prices else None

    @property
    def in_stock(self) -> bool:
        """True when at least one variant is purchasable."""
        return any(v.available for v in self.variants)

    @property
    def variants_in_stock(self) -> int:
        return sum(1 for v in self.variants if v.available)

    @property
    def on_sale(self) -> bool:
        return any(v.on_sale for v in self.variants)

    @property
    def max_discount_pct(self) -> Optional[int]:
        """Deepest discount across the product's variants."""
        discounts = [v.discount_pct for v in self.variants if v.discount_pct is not None]
        return max(discounts) if discounts else None

    @property
    def colors(self) -> List[str]:
        """Colour values for the product, in the merchant's own order.

        Reads the declared colour option first. Some merchants define the option
        but leave its ``values`` array empty, so this falls back to walking the
        variants and collecting the corresponding ``optionN`` field.
        """
        for index, option in enumerate(self.options):
            name = str(option.get("name", "")).strip().lower()
            if name not in COLOR_OPTION_NAMES:
                continue
            values = [str(v).strip() for v in (option.get("values") or []) if str(v).strip()]
            if values:
                return values
            key = "option{}".format(index + 1)
            seen: List[str] = []
            for variant in self.variants:
                value = getattr(variant, key, "")
                if value and value not in seen:
                    seen.append(value)
            return seen
        return []

    def description(self, max_chars: Optional[int] = 800, specs_first: bool = True) -> str:
        """Plain-text description with specification tables flattened."""
        return html_to_text(self.body_html, max_chars=max_chars, specs_first=specs_first)

    def to_dict(self, max_chars: Optional[int] = 800) -> Dict[str, Any]:
        """JSON-serialisable representation, including derived fields."""
        return {
            "id": self.id,
            "title": self.title,
            "handle": self.handle,
            "url": self.url,
            "vendor": self.vendor,
            "product_type": self.product_type,
            "tags": self.tags,
            "description": self.description(max_chars),
            "image_url": self.image_url,
            "image_urls": self.image_urls,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "in_stock": self.in_stock,
            "on_sale": self.on_sale,
            "max_discount_pct": self.max_discount_pct,
            "colors": self.colors,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "published_at": self.published_at,
            "variants": [
                {
                    "id": v.id,
                    "title": v.title,
                    "sku": v.sku,
                    "price": v.price,
                    "compare_at_price": v.compare_at_price,
                    "on_sale": v.on_sale,
                    "discount_pct": v.discount_pct,
                    "available": v.available,
                    "option1": v.option1,
                    "option2": v.option2,
                    "option3": v.option3,
                    "grams": v.grams,
                    "requires_shipping": v.requires_shipping,
                    "taxable": v.taxable,
                    "image_url": v.featured_image_url,
                }
                for v in self.variants
            ],
        }
