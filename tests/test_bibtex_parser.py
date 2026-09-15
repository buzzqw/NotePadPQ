import unittest

from core.bibtex_parser import (
    find_bibtex_entry_end,
    find_bibtex_keys,
    split_bibtex_items,
)


class BibtexParserTests(unittest.TestCase):
    def test_split_items_respects_braces_quotes_and_parentheses(self):
        body = 'key, title={A, {nested}}, note="quoted, value", year=2026'

        self.assertEqual(
            split_bibtex_items(body),
            ["key", " title={A, {nested}}", ' note="quoted, value"', " year=2026"],
        )

    def test_entry_end_supports_parenthesized_entries_and_nested_values(self):
        text = "@online(key, title={A {nested}, value}, url=\"https://x\")"
        opening = text.index("(")

        self.assertEqual(find_bibtex_entry_end(text, opening, "("), len(text) - 1)
        self.assertIsNone(find_bibtex_entry_end(text[: -1], opening, "("))

    def test_keys_ignore_comments_and_metadata_entries(self):
        text = (
            "% @article{ignored, title={No}}\n"
            "@string{month = \"jan\"}\n"
            "@article{first, title={First}}\n"
            "@book(second, title={Second})\n"
        )

        self.assertEqual(find_bibtex_keys(text), ["first", "second"])


if __name__ == "__main__":
    unittest.main()
