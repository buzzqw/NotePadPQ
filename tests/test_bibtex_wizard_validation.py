import unittest

from editor.bibtex_wizard import (
    find_bibtex_keys,
    find_duplicate_bibtex_keys,
    normalize_bibtex_record,
    normalize_doi,
    parse_bibtex_record,
    validate_bibtex_record,
)


class BibTeXWizardValidationTests(unittest.TestCase):
    def test_normalizes_fields_doi_url_and_keeps_biblatex_fields(self):
        record = normalize_bibtex_record({
            "_type": "ONLINE",
            "KEY": "  WebRef  ",
            "Author": " Ada Lovelace ",
            "Title": " Notes ",
            "URL": " {https://example.org/paper} ",
            "DOI": "https://doi.org/10.1000/ABC-1.",
            "urldate": "2026-08-10",
            "date": "2026",
        })

        self.assertEqual(record["_type"], "online")
        self.assertEqual(record["key"], "WebRef")
        self.assertEqual(record["url"], "https://example.org/paper")
        self.assertEqual(record["doi"], "10.1000/abc-1")
        self.assertEqual(record["date"], "2026")

    def test_required_fields_depend_on_entry_type(self):
        errors = validate_bibtex_record(
            {"key": "smith2026", "author": "Smith", "title": "A paper", "year": "2026"},
            entry_type="article",
        )

        self.assertTrue(any("journal" in error for error in errors))
        self.assertFalse(any("publisher" in error for error in errors))

        online_errors = validate_bibtex_record(
            {"key": "site2026", "author": "Smith", "title": "A site"},
            entry_type="online",
        )
        self.assertTrue(any("url" in error and "urldate" in error for error in online_errors))

    def test_unknown_biblatex_type_is_not_rejected_for_unknown_required_fields(self):
        errors = validate_bibtex_record(
            {"_type": "software", "key": "tool2026", "title": "Tool"}
        )

        self.assertEqual(errors, [])

    def test_doi_and_url_are_checked_without_network_access(self):
        self.assertEqual(normalize_doi(" DOI: 10.1000/XYZ "), "10.1000/xyz")
        self.assertEqual(normalize_doi("https://doi.org/10.1000/xyz?view=full"), "")

        errors = validate_bibtex_record({
            "_type": "misc",
            "key": "bad-link",
            "doi": "not-a-doi",
            "url": "example.org/paper",
        })
        self.assertIn("Invalid DOI", errors)
        self.assertIn("Invalid URL", errors)

    def test_duplicate_keys_ignore_comments_and_metadata_entries(self):
        text = r"""
        % @article{ignored, title = {Comment}}
        @article{same, title = {First}}
        @string{month = "jan"}
        @online(same, title = {Second})
        @book{other, title = {Third}}
        @misc{wrapped, note = {@article{not-an-entry, title={x}}}}
        """

        self.assertEqual(find_bibtex_keys(text), ["same", "same", "other", "wrapped"])
        self.assertEqual(find_duplicate_bibtex_keys(text), ["same"])
        self.assertIn(
            "Duplicate BibTeX key: same",
            validate_bibtex_record(
                {"_type": "misc", "key": "same"}, existing_keys=text
            ),
        )

    def test_parser_handles_nested_braces_and_normalizes_result(self):
        record = parse_bibtex_record(
            '@article{key2026, title = {A {Nested}, title}, '
            'doi = {https://doi.org/10.1000/XYZ}, url = "https://example.org"}'
        )

        self.assertEqual(record["_type"], "article")
        self.assertEqual(record["key"], "key2026")
        self.assertEqual(record["title"], "A {Nested}, title")
        self.assertEqual(record["doi"], "10.1000/xyz")
        self.assertEqual(record["url"], "https://example.org")


if __name__ == "__main__":
    unittest.main()
