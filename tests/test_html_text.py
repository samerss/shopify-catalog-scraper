"""Tests for the HTML-to-text conversion engine."""

import unittest

from shopify_catalog_scraper.html_text import (
    extract_spec_pairs,
    html_to_text,
    split_html,
    truncate,
)


class TestSpecTables(unittest.TestCase):
    def test_two_cell_row_becomes_label_value(self):
        html = "<table><tr><td>Weight</td><td>268g</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["Weight: 268g"])

    def test_multi_cell_row_joins_values(self):
        html = "<table><tr><td>Ports</td><td>USB-C</td><td>HDMI</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["Ports: USB-C, HDMI"])

    def test_single_cell_row_kept_verbatim(self):
        html = "<table><tr><td>Made in Egypt</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["Made in Egypt"])

    def test_header_only_row_is_skipped(self):
        html = (
            "<table>"
            "<tr><th>Spec</th><th>Value</th></tr>"
            "<tr><td>Weight</td><td>268g</td></tr>"
            "</table>"
        )
        self.assertEqual(extract_spec_pairs(html), ["Weight: 268g"])

    def test_mixed_th_td_row_is_kept(self):
        html = "<table><tr><th>Weight</th><td>268g</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["Weight: 268g"])

    def test_empty_rows_are_dropped(self):
        html = "<table><tr><td></td><td>  </td></tr><tr><td>A</td><td>B</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["A: B"])

    def test_multiple_tables_accumulate(self):
        html = (
            "<table><tr><td>A</td><td>1</td></tr></table>"
            "<table><tr><td>B</td><td>2</td></tr></table>"
        )
        self.assertEqual(extract_spec_pairs(html), ["A: 1", "B: 2"])

    def test_br_inside_cell_becomes_space(self):
        html = "<table><tr><td>Input</td><td>5V 2A<br>9V 2A</td></tr></table>"
        self.assertEqual(extract_spec_pairs(html), ["Input: 5V 2A 9V 2A"])

    def test_unclosed_cells_are_salvaged(self):
        html = "<table><tr><td>Weight<td>268g</table>"
        self.assertEqual(extract_spec_pairs(html), ["Weight: 268g"])


class TestProse(unittest.TestCase):
    def test_block_tags_do_not_run_words_together(self):
        self.assertEqual(split_html("<p>one</p><p>two</p>")[1], "one two")

    def test_script_and_style_content_is_dropped(self):
        html = "<style>.a{color:red}</style><p>Real</p><script>alert(1)</script>"
        self.assertEqual(split_html(html)[1], "Real")

    def test_entities_are_decoded(self):
        self.assertEqual(split_html("<p>Tom &amp; Jerry&nbsp;5&quot;</p>")[1], 'Tom & Jerry 5"')

    def test_nbsp_collapses_to_single_space(self):
        self.assertEqual(split_html("<p>a&nbsp;&nbsp;&nbsp;b</p>")[1], "a b")

    def test_table_text_does_not_leak_into_prose(self):
        html = "<p>Intro</p><table><tr><td>A</td><td>1</td></tr></table><p>Outro</p>"
        pairs, prose = split_html(html)
        self.assertEqual(pairs, ["A: 1"])
        self.assertEqual(prose, "Intro Outro")


class TestEdgeCases(unittest.TestCase):
    def test_empty_input(self):
        for value in (None, "", "   "):
            self.assertEqual(split_html(value), ([], ""))
            self.assertEqual(html_to_text(value), "")

    def test_plain_text_without_tags(self):
        self.assertEqual(html_to_text("just words"), "just words")

    def test_non_string_input_is_coerced(self):
        self.assertEqual(html_to_text(12345), "12345")

    def test_deeply_nested_tables(self):
        html = (
            "<div><table><tr><td>Outer</td><td>"
            "<table><tr><td>Inner</td><td>x</td></tr></table>"
            "</td></tr></table></div>"
        )
        # Nesting must not raise and must not lose the inner data entirely.
        pairs = extract_spec_pairs(html)
        self.assertTrue(any("Inner" in p for p in pairs))

    def test_malformed_markup_does_not_raise(self):
        for html in ("<p>unclosed", "<<>>", "<table><tr><td>", "a < b > c"):
            self.assertIsInstance(html_to_text(html), str)


class TestComposition(unittest.TestCase):
    def setUp(self):
        self.html = (
            "<table><tr><td>Weight</td><td>268g</td></tr></table>"
            "<p>Great product.</p>"
        )

    def test_specs_precede_prose_by_default(self):
        self.assertEqual(html_to_text(self.html), "Weight: 268g | Great product.")

    def test_specs_last_when_requested(self):
        self.assertEqual(
            html_to_text(self.html, specs_first=False), "Great product. | Weight: 268g"
        )

    def test_custom_separator(self):
        self.assertEqual(
            html_to_text(self.html, spec_separator=" ~ "), "Weight: 268g ~ Great product."
        )

    def test_prose_only_has_no_separator(self):
        self.assertEqual(html_to_text("<p>Only prose</p>"), "Only prose")


class TestTruncate(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(truncate("short", 100), "short")

    def test_breaks_on_word_boundary(self):
        self.assertEqual(truncate("one two three", 8), "one two…")

    def test_strips_trailing_separator_punctuation(self):
        self.assertEqual(truncate("alpha | beta gamma", 9), "alpha…")

    def test_none_and_zero_disable_truncation(self):
        text = "a" * 50
        self.assertEqual(truncate(text, None), text)
        self.assertEqual(truncate(text, 0), text)

    def test_respects_max_length(self):
        result = truncate("word " * 100, 40)
        self.assertLessEqual(len(result), 41)  # 40 chars plus the ellipsis

    def test_custom_ellipsis(self):
        self.assertEqual(truncate("one two three", 8, ellipsis="..."), "one two...")

    def test_html_to_text_applies_cap(self):
        result = html_to_text("<p>" + "word " * 100 + "</p>", max_chars=30)
        self.assertLessEqual(len(result), 31)
        self.assertTrue(result.endswith("…"))


if __name__ == "__main__":
    unittest.main()
