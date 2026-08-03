# Contributing

Thanks for taking the time. Bug reports, real-world edge cases and pull requests are all welcome.

## Getting set up

```bash
git clone https://github.com/samerss/shopify-catalog-scraper.git
cd shopify-catalog-scraper
python -m unittest discover -s tests -v
```

There is nothing to install. The package and its tests use only the Python standard library, which is a constraint worth keeping — it is the reason this tool runs anywhere without a build step.

## Ground rules for changes

**No runtime dependencies.** If a change seems to need a third-party package, open an issue first and describe the problem. There is usually a standard-library route.

**Tests run offline.** Every test stubs `urllib.request.urlopen`. Never write a test that reaches the network: it makes CI flaky and depends on a stranger's storefront staying online and unchanged.

**Test the ugly input.** The interesting bugs in this project all come from real storefront HTML — unclosed `<td>`, tables nested three deep, `<script>` blocks in the middle of a description, missing keys in the JSON feed. If you fix one, add the malformed input to `tests/test_html_text.py` so it stays fixed.

**Degrade, don't crash.** One malformed product should never abort a 1,300-product run. Parsing helpers return empty strings or `None` rather than raising.

**Match the existing style.** Four-space indent, type hints on public functions, docstrings that explain *why* rather than restating the signature.

## Adding an export format

1. Write `write_<name>()` in `src/shopify_catalog_scraper/exporters.py`, taking `(products, path, ...)` and returning the record count.
2. Add the name to `FORMATS` and a branch in `write_products()`.
3. Add tests to `tests/test_exporters.py` — at minimum that the file is non-empty and that the counts are right.
4. Document it in the README.

## Pull requests

Keep them focused; one concern per PR. Include a test that fails before your change and passes after. Note any behaviour change in `CHANGELOG.md` under "Unreleased".

CI runs the suite on Python 3.8 through 3.13. All of them need to pass.

## Reporting bugs

The single most useful thing you can include is the input that broke it — the raw `body_html` snippet, or the store domain and the exact command you ran. A description of wrong output without the input that produced it is very hard to act on.

Please don't paste large scraped catalogs into issues; a few representative lines is plenty.
