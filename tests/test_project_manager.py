import tempfile
import unittest
from pathlib import Path

from ui.project_manager import (
    ProjectManager,
    _decode_project_file_path,
    _encode_project_file_path,
)


class ProjectManagerPathsTest(unittest.TestCase):
    def test_paths_inside_project_are_saved_relative_and_restored_absolute(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_path = root / "projects" / "demo.npqproj"
            source = root / "projects" / "src" / "main.tex"
            source.parent.mkdir(parents=True)
            source.write_text("% test")

            stored = _encode_project_file_path(str(source), project_path)

            self.assertEqual(stored, "src/main.tex")
            self.assertEqual(
                _decode_project_file_path(stored, project_path), str(source.resolve())
            )

    def test_external_paths_remain_absolute(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_path = root / "demo.npqproj"
            external = (root.parent / "outside.tex").resolve()

            self.assertEqual(_encode_project_file_path(str(external), project_path), str(external))

    def test_serialization_does_not_mutate_loaded_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_path = root / "demo.npqproj"
            source = root / "main.tex"
            source.write_text("% test")
            data = {"name": "Demo", "groups": [{"name": "Sources", "files": [str(source)]}]}

            class FakeManager:
                def _project_data(self):
                    return data

            serialized = ProjectManager._serializable_data(FakeManager(), project_path)

            self.assertEqual(serialized["groups"][0]["files"], ["main.tex"])
            self.assertEqual(data["groups"][0]["files"], [str(source)])

    def test_open_normalization_accepts_legacy_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project_path = root / "demo.npqproj"
            source = root / "main.tex"
            source.write_text("% test")
            data = {
                "name": "Demo",
                "groups": [{"name": "Sources", "files": ["main.tex", str(source)]}],
            }

            normalized = ProjectManager._normalize_loaded_data(data, project_path)

            self.assertEqual(
                normalized["groups"][0]["files"], [str(source.resolve()), str(source.resolve())]
            )


if __name__ == "__main__":
    unittest.main()
