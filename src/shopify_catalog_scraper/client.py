"""HTTP client for the public Shopify product feed.

Every Shopify storefront exposes ``/products.json``: a paginated, structured
feed of the store's published catalogue. Reading it is dramatically more robust
than scraping rendered HTML pages, because it does not care what theme the
merchant uses, survives redesigns, and returns clean typed fields instead of
markup that has to be reverse-engineered.

This module handles the parts that are easy to get wrong: pagination that ends
without telling you, stores that silently ignore the ``page`` parameter and hand
back page one forever, transient 5xx responses, and rate limiting.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterator, List, Optional

from .errors import (
    AccessDeniedError,
    NotAShopifyStoreError,
    RateLimitedError,
    StoreUnreachableError,
)
from .models import Product

__all__ = ["ShopifyClient", "normalize_store_url", "DEFAULT_USER_AGENT", "MAX_PAGE_SIZE"]

DEFAULT_USER_AGENT = (
    "shopify-catalog-scraper/1.0 (+https://github.com/topics/shopify; "
    "python-urllib)"
)

#: Shopify caps the ``limit`` parameter at 250 products per request.
MAX_PAGE_SIZE = 250


def normalize_store_url(store: str) -> str:
    """Normalise user input into a scheme-qualified origin.

    Accepts bare domains, full URLs, and URLs with paths or query strings.

    >>> normalize_store_url("example.com")
    'https://example.com'
    >>> normalize_store_url("https://example.com/collections/all?page=2")
    'https://example.com'
    """
    store = (store or "").strip()
    if not store:
        raise ValueError("store URL must not be empty")
    if "://" not in store:
        store = "https://" + store
    parts = urllib.parse.urlsplit(store)
    if not parts.netloc:
        raise ValueError("could not parse a hostname from {!r}".format(store))
    scheme = parts.scheme if parts.scheme in ("http", "https") else "https"
    return "{}://{}".format(scheme, parts.netloc)


class ShopifyClient:
    """Fetches products from a single Shopify storefront.

    Args:
        store: Store URL or bare domain, e.g. ``"examplestore.com"``.
        timeout: Per-request socket timeout in seconds.
        max_retries: Retry attempts for transient failures (timeouts, 5xx, 429).
        backoff: Multiplier for exponential backoff between retries.
        delay: Seconds to sleep between successful page requests. Defaults to a
            polite ``0.5``; set to ``0`` only against stores you own.
        user_agent: Value sent in the ``User-Agent`` header. Identify yourself
            honestly -- it lets merchants see who is calling and contact you.
        extra_headers: Additional request headers.

    Example::

        client = ShopifyClient("examplestore.com")
        products = client.fetch_all_products()
        print(len(products), "products")
    """

    def __init__(
        self,
        store: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 1.5,
        delay: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.store_url = normalize_store_url(store)
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff = backoff
        self.delay = max(0.0, float(delay))
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if extra_headers:
            self.headers.update(extra_headers)

    # -- low level --------------------------------------------------------

    def _build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = self.store_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def _get_json(self, url: str) -> Dict[str, Any]:
        """GET ``url`` and decode JSON, retrying transient failures."""
        attempt = 0
        last_error: Optional[BaseException] = None
        while attempt <= self.max_retries:
            request = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code in (401, 403):
                    raise AccessDeniedError(
                        "{} refused the request (HTTP {}). The store may have "
                        "disabled its public product feed, be password "
                        "protected, or sit behind bot protection.".format(
                            self.store_url, exc.code
                        )
                    ) from exc
                if exc.code == 404:
                    raise NotAShopifyStoreError(
                        "{} returned HTTP 404 for {}. It may not be a Shopify "
                        "store, or the storefront lives on another domain.".format(
                            self.store_url, url
                        )
                    ) from exc
                if exc.code == 429:
                    if attempt >= self.max_retries:
                        raise RateLimitedError(
                            "{} is rate limiting this client (HTTP 429). Re-run "
                            "with a larger --delay.".format(self.store_url)
                        ) from exc
                    self._sleep_for_retry(attempt, exc.headers.get("Retry-After"))
                elif 500 <= exc.code < 600:
                    if attempt >= self.max_retries:
                        raise StoreUnreachableError(
                            "{} returned HTTP {} after {} attempts.".format(
                                self.store_url, exc.code, attempt + 1
                            )
                        ) from exc
                    self._sleep_for_retry(attempt, None)
                else:
                    raise StoreUnreachableError(
                        "Unexpected HTTP {} from {}.".format(exc.code, url)
                    ) from exc
            except (urllib.error.URLError, OSError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise StoreUnreachableError(
                        "Could not reach {} after {} attempts: {}".format(
                            self.store_url, attempt + 1, exc
                        )
                    ) from exc
                self._sleep_for_retry(attempt, None)
            attempt += 1
        else:  # pragma: no cover - loop always breaks or raises
            raise StoreUnreachableError(str(last_error))

        try:
            return json.loads(payload.decode("utf-8", "replace"))
        except ValueError as exc:
            raise NotAShopifyStoreError(
                "{} did not return JSON. This is usually an HTML error page, a "
                "redirect to a password page, or a non-Shopify site.".format(url)
            ) from exc

    def _sleep_for_retry(self, attempt: int, retry_after: Optional[str]) -> None:
        wait = self.backoff ** attempt
        if retry_after:
            try:
                wait = max(wait, float(retry_after))
            except (TypeError, ValueError):
                pass
        time.sleep(min(wait, 60.0))

    # -- product feed -----------------------------------------------------

    def fetch_page(
        self,
        page: int,
        limit: int = MAX_PAGE_SIZE,
        collection: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch one page of raw product dictionaries.

        Args:
            page: 1-based page number.
            limit: Products per page, capped at 250 by Shopify.
            collection: Optional collection handle to scope the feed to.
        """
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        path = "/products.json"
        if collection:
            path = "/collections/{}/products.json".format(urllib.parse.quote(collection))
        data = self._get_json(self._build_url(path, {"limit": limit, "page": page}))
        if not isinstance(data, dict) or "products" not in data:
            raise NotAShopifyStoreError(
                "Response from {} has no 'products' key -- this does not look "
                "like a Shopify product feed.".format(self.store_url)
            )
        products = data.get("products")
        return products if isinstance(products, list) else []

    def iter_products(
        self,
        limit: int = MAX_PAGE_SIZE,
        max_pages: int = 200,
        collection: Optional[str] = None,
        on_page: Optional[Callable[[int, int, int], None]] = None,
    ) -> Iterator[Product]:
        """Yield every published product, one page at a time.

        Pagination stops on the first of: a short page, an empty page, a page
        containing no product IDs we have not already seen, or ``max_pages``.

        That third condition matters. A minority of storefronts ignore the
        ``page`` parameter and cheerfully return page one on every request; a
        naive loop against those stores never terminates. Tracking seen IDs
        turns an infinite loop into a clean stop.

        Args:
            limit: Products per request (max 250).
            max_pages: Hard ceiling on requests, as a runaway guard.
            collection: Optional collection handle to scope the feed to.
            on_page: Callback invoked as ``(page_number, page_count,
                running_total)`` after each successful page. Useful for
                progress output.
        """
        seen_ids = set()
        total = 0
        for page in range(1, max_pages + 1):
            batch = self.fetch_page(page, limit=limit, collection=collection)
            if not batch:
                break
            fresh = 0
            for raw in batch:
                product_id = raw.get("id")
                if product_id is not None and product_id in seen_ids:
                    continue
                if product_id is not None:
                    seen_ids.add(product_id)
                fresh += 1
                total += 1
                yield Product.from_api(raw, store_url=self.store_url)
            if on_page is not None:
                on_page(page, len(batch), total)
            if fresh == 0:
                # The store is ignoring ?page= and repeating itself.
                break
            if len(batch) < limit:
                break
            if self.delay:
                time.sleep(self.delay)

    def fetch_all_products(
        self,
        limit: int = MAX_PAGE_SIZE,
        max_pages: int = 200,
        collection: Optional[str] = None,
        on_page: Optional[Callable[[int, int, int], None]] = None,
    ) -> List[Product]:
        """Eagerly fetch the whole catalogue into a list."""
        return list(
            self.iter_products(
                limit=limit, max_pages=max_pages, collection=collection, on_page=on_page
            )
        )

    def fetch_collections(self, limit: int = MAX_PAGE_SIZE) -> List[Dict[str, Any]]:
        """List the store's public collections (handle, title, product count)."""
        data = self._get_json(self._build_url("/collections.json", {"limit": limit}))
        collections = data.get("collections")
        return collections if isinstance(collections, list) else []
