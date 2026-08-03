"""Convert Shopify ``body_html`` product descriptions into clean plain text.

Shopify stores product descriptions as free-form HTML. In practice that HTML is
messy: suppliers paste in specification tables, marketing markup, inline styles
and tracking scripts. Naively stripping tags gives you a wall of run-together
words where a specification table used to be --
``Input 5V 3A Output 15W max Material ABS + PC`` -- with no indication of which
value belongs to which label.

This module solves that. It walks the document once and treats tables specially:
each table row is flattened into a readable ``label: value`` pair, and the pairs
are joined with a separator. The same product then reads::

    Input: 5V 3A | Output: 15W max | Material: ABS + PC | Weight: 268g

Everything outside of tables is collected as ordinary prose, with block-level
elements becoming spaces so words never run together across tag boundaries.

The parser is deliberately forgiving. Real storefront HTML is frequently invalid
-- unclosed tags, stray ``</td>``, tables nested three deep inside a layout
grid. If :class:`html.parser.HTMLParser` gives up entirely, the module falls
back to a regex strip so that one malformed product never costs you the run.

Only the Python standard library is used.
"""

from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "html_to_text",
    "split_html",
    "extract_spec_pairs",
    "truncate",
    "HtmlTextExtractor",
]

#: Tags whose boundaries should become whitespace, so that ``<p>a</p><p>b</p>``
#: becomes ``a b`` rather than ``ab``.
BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "tbody", "tfoot", "thead", "tr", "ul",
    }
)

#: Tags whose *contents* are discarded entirely.
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "iframe", "svg"})

_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_PUNCT = " \t\r\n,;:|-–—/\\"


class HtmlTextExtractor(HTMLParser):
    """Single-pass extractor that separates table specs from prose.

    After :meth:`feed` and :meth:`close`, two attributes hold the result:

    ``spec_pairs``
        A list of ``"label: value"`` strings, one per meaningful table row.
    ``prose``
        All non-table text, whitespace-normalised.

    Most callers want :func:`html_to_text` or :func:`split_html` instead of
    driving this class directly.
    """

    def __init__(self, pair_separator: str = ": ", value_separator: str = ", ") -> None:
        super().__init__(convert_charrefs=True)
        self.pair_separator = pair_separator
        self.value_separator = value_separator
        self.spec_pairs: List[str] = []
        self._prose: List[str] = []
        self._table_depth = 0
        self._skip_depth = 0
        self._in_cell = False
        self._cell_tag = "td"
        self._cell_buffer: List[str] = []
        self._row_cells: List[Tuple[str, List[str]]] = []

    # -- HTMLParser hooks -------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D102
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._table_depth:
            self._flush_row()  # tolerate a missing </tr>
            self._row_cells = []
        elif tag in ("td", "th") and self._table_depth:
            if self._in_cell:
                self._close_cell()  # tolerate a missing </td>
            self._in_cell = True
            self._cell_tag = tag
            self._cell_buffer = []
        elif tag == "br":
            self._emit(" ")
        elif tag in BLOCK_TAGS:
            self._emit(" ")

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: D102
        if tag in BLOCK_TAGS and not self._skip_depth:
            self._emit(" ")

    def handle_endtag(self, tag: str) -> None:  # noqa: D102
        if tag in SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "table":
            if self._table_depth:
                self._flush_row()
                self._table_depth -= 1
        elif tag == "tr" and self._table_depth:
            self._flush_row()
        elif tag in ("td", "th") and self._table_depth and self._in_cell:
            self._close_cell()
        elif tag in BLOCK_TAGS:
            self._emit(" ")

    def handle_data(self, data: str) -> None:  # noqa: D102
        if self._skip_depth:
            return
        self._emit(data)

    def close(self) -> None:  # noqa: D102
        super().close()
        # Salvage anything left dangling by unclosed markup.
        self._flush_row()

    # -- internals --------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._in_cell:
            self._cell_buffer.append(text)
        elif not self._table_depth:
            self._prose.append(text)

    def _close_cell(self) -> None:
        self._row_cells.append((self._cell_tag, self._cell_buffer))
        self._cell_buffer = []
        self._in_cell = False

    def _flush_row(self) -> None:
        # A cell still open at row boundary means the markup omitted </td>.
        if self._in_cell:
            self._close_cell()
        if not self._row_cells:
            return
        cells = [(tag, _collapse("".join(buf))) for tag, buf in self._row_cells]
        self._row_cells = []
        values = [text for _, text in cells if text]
        if not values:
            return
        # A row made purely of <th> is a header row -- it labels the columns
        # below rather than carrying a value, so it is not a spec pair.
        if all(tag == "th" for tag, text in cells if text):
            return
        if len(values) == 1:
            self.spec_pairs.append(values[0])
        elif len(values) == 2:
            self.spec_pairs.append(values[0] + self.pair_separator + values[1])
        else:
            self.spec_pairs.append(
                values[0] + self.pair_separator + self.value_separator.join(values[1:])
            )

    @property
    def prose(self) -> str:
        """All text found outside of tables, whitespace-normalised."""
        return _collapse("".join(self._prose))


def _collapse(text: str) -> str:
    """Collapse every run of whitespace (including ``&nbsp;``) to one space."""
    return " ".join(text.split())


def _fallback(html: str) -> str:
    """Last-resort extraction for markup that defeats the real parser."""
    try:
        return _collapse(_html.unescape(_TAG_RE.sub(" ", html)))
    except Exception:  # pragma: no cover - defensive
        return ""


def split_html(html: Optional[str]) -> Tuple[List[str], str]:
    """Split raw description HTML into ``(spec_pairs, prose)``.

    Never raises: malformed input degrades to ``([], <best effort text>)``.

    >>> split_html("<table><tr><td>Weight</td><td>268g</td></tr></table><p>Nice.</p>")
    (['Weight: 268g'], 'Nice.')
    """
    if not html or not str(html).strip():
        return [], ""
    raw = str(html)
    parser = HtmlTextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return [], _fallback(raw)
    return parser.spec_pairs, parser.prose


def extract_spec_pairs(html: Optional[str]) -> List[str]:
    """Return only the flattened ``label: value`` pairs found in tables."""
    return split_html(html)[0]


def truncate(text: str, max_chars: Optional[int], ellipsis: str = "…") -> str:
    """Trim ``text`` to ``max_chars``, breaking on a word boundary.

    Trailing separator punctuation is stripped so a truncated spec list never
    ends on a dangling ``|`` or comma.

    >>> truncate("one two three", 8)
    'one two…'
    >>> truncate("short", 100)
    'short'
    """
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(_TRAILING_PUNCT) + ellipsis


def html_to_text(
    html: Optional[str],
    max_chars: Optional[int] = None,
    specs_first: bool = True,
    spec_separator: str = " | ",
    ellipsis: str = "…",
) -> str:
    """Convert description HTML to a single clean line of plain text.

    Args:
        html: Raw ``body_html`` from the Shopify product feed.
        max_chars: Cap the result at this many characters, cutting on a word
            boundary. ``None`` (the default) means no limit.
        specs_first: Put flattened specification pairs ahead of the marketing
            prose. This is usually what you want: when the text is truncated,
            the hard facts survive and the marketing copy is what gets cut.
        spec_separator: String placed between consecutive spec pairs.
        ellipsis: Appended when the text is truncated.

    Returns:
        A whitespace-normalised single-line string. Empty input gives ``""``.
    """
    pairs, prose = split_html(html)
    specs = spec_separator.join(pairs)
    if specs and prose:
        combined = f"{specs}{spec_separator}{prose}" if specs_first else f"{prose}{spec_separator}{specs}"
    else:
        combined = specs or prose
    return truncate(_collapse(combined), max_chars, ellipsis)


def join_nonempty(parts: Sequence[str], separator: str = " | ") -> str:
    """Join the truthy members of ``parts`` with ``separator``."""
    return separator.join(p for p in parts if p)
