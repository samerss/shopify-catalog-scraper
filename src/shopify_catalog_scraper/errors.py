"""Exception types raised by :mod:`shopify_catalog_scraper`."""

from __future__ import annotations

__all__ = [
    "ScraperError",
    "StoreUnreachableError",
    "NotAShopifyStoreError",
    "AccessDeniedError",
    "RateLimitedError",
]


class ScraperError(Exception):
    """Base class for every error raised by this package."""


class StoreUnreachableError(ScraperError):
    """The store could not be reached (DNS failure, timeout, connection reset)."""


class NotAShopifyStoreError(ScraperError):
    """The URL responded, but does not expose a Shopify product feed.

    Raised when ``/products.json`` returns a 404, an HTML error page, or a JSON
    document without a ``products`` key. Usually this means the URL is not a
    Shopify store at all, or a custom storefront proxies the real domain.
    """


class AccessDeniedError(ScraperError):
    """The store actively refused the request (HTTP 401/403).

    Some merchants disable the public product feed, put the storefront behind a
    password, or sit behind a bot-protection layer that blocks non-browser
    clients. There is no workaround in this tool by design: if a store has opted
    out of serving this endpoint, that decision is respected.
    """


class RateLimitedError(ScraperError):
    """The store returned HTTP 429 and retries were exhausted.

    Re-run with a larger ``--delay`` to be gentler on the origin.
    """
