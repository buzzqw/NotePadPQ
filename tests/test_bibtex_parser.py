import unittest

from core.bibtex_parser import (
    find_bibtex_entry_end,
    find_bibtex_keys,
    parse_bibtex_entries,
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

    def test_metadata_extracts_first_author_year_and_title(self):
        text = (
            "@article{doe2024,\n"
            "  author = {Doe, John and Smith, Jane},\n"
            '  title = "{A {Nested} Title}",\n'
            "  year = 2024\n"
            "}\n"
            "@book{other, author={Mario Rossi}, date={2021-05-01}}\n"
        )

        entries = parse_bibtex_entries(text)

        self.assertEqual(entries["doe2024"]["author"], "Doe")
        self.assertEqual(entries["doe2024"]["year"], "2024")
        self.assertEqual(entries["doe2024"]["title"], "A {Nested} Title")
        self.assertEqual(entries["other"]["author"], "Rossi")
        self.assertEqual(entries["other"]["year"], "2021")

    def test_metadata_skips_comments_and_string_entries(self):
        text = (
            "% @article{ignored, title={No}}\n"
            "@string{month = \"jan\"}\n"
            "@misc{kept, title={Yes}}\n"
        )

        self.assertEqual(set(parse_bibtex_entries(text)), {"kept"})

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
