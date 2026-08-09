import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import lazy_loader


class LazyLoaderTest(unittest.TestCase):
    def test_load_worker_bounds_a_file_without_newlines(self):
        content = "e\u0301" * 100
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "long-line.txt"
            path.write_text(content, encoding="utf-8")
            chunks = []
            worker = lazy_loader._LoadWorker(path)
            worker.chunk_ready.connect(
                lambda text, _index, _total: chunks.append(text)
            )

            with mock.patch.object(lazy_loader, "CHUNK_SIZE_BYTES", 16), \
                    mock.patch.object(lazy_loader, "MAX_PENDING_TEXT_CHARS", 16):
                worker.run()

            self.assertEqual("".join(chunks), content)
            self.assertTrue(all(len(chunk) <= 16 for chunk in chunks))
            self.assertGreater(len(chunks), 1)

    def test_paged_utf8_preserves_characters_at_page_boundaries(self):
        content = "🙂" * 80
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "utf8.txt"
            path.write_text(content, encoding="utf-8")
            with mock.patch.object(lazy_loader, "CHUNK_SIZE_PAGED", 16), \
                    mock.patch.object(lazy_loader, "PAGE_LOOKAHEAD_CAP", 8):
                document = lazy_loader.PagedDocument(path)
                pages = [document.read_page_at(document.current_start)]
                while True:
                    page = document.next_page()
                    if page is None:
                        break
                    pages.append(page)

            self.assertEqual("".join(pages), content)
            self.assertNotIn("\ufffd", "".join(pages))

    def test_paged_utf16_uses_encoded_newline_boundaries(self):
        content = "\n".join(f"riga {index} - e\u0301 🙂" for index in range(40)) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "utf16.txt"
            path.write_bytes(b"\xff\xfe" + content.encode("utf-16-le"))
            with mock.patch.object(lazy_loader, "CHUNK_SIZE_PAGED", 32), \
                    mock.patch.object(lazy_loader, "PAGE_LOOKAHEAD_CAP", 16):
                document = lazy_loader.PagedDocument(path)
                pages = [document.read_page_at(document.current_start)]
                while True:
                    page = document.next_page()
                    if page is None:
                        break
                    pages.append(page)

            self.assertEqual("".join(pages), content)
            self.assertNotIn("\ufffd", "".join(pages))

    def test_paged_navigation_tracks_global_line_and_page_offsets(self):
        content = "".join(f"line {index}\n" for index in range(200))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lines.txt"
            path.write_text(content, encoding="utf-8")
            with mock.patch.object(lazy_loader, "CHUNK_SIZE_PAGED", 64), \
                    mock.patch.object(lazy_loader, "PAGE_LOOKAHEAD_CAP", 16):
                document = lazy_loader.PagedDocument(path)
                document.read_page_at(document.current_start)
                first_line = document.current_line_start
                document.next_page()
                next_line = document.current_line_start
                next_page = document.current_page_number
                document.prev_page()
                previous_line = document.current_line_start
                jumped = document.jump_to_fraction(0.5)

            self.assertEqual(first_line, 0)
            self.assertGreater(next_line, first_line)
            self.assertGreater(next_page, 1)
            self.assertEqual(previous_line, first_line)
            self.assertGreater(document.current_line_start, next_line)
            self.assertTrue(jumped.startswith("line "))


if __name__ == "__main__":
    unittest.main()
