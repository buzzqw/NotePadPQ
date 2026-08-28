import os
import subprocess
import sys
from types import SimpleNamespace

from plugins.language_tool_plugin import (
    _absolute_to_line_col,
    _is_prose_editor,
    _line_col_to_absolute,
    _mask_latex,
    _parse_matches,
    _terminate_server_process,
)
from plugins.plugin_manager import PluginManager


def test_language_tool_matches_are_normalized():
    payload = {
        "matches": [{
            "offset": 4,
            "length": 3,
            "message": "Suggerimento",
            "shortMessage": "Stile",
            "rule": {"id": "TEST_RULE", "category": {"id": "STYLE"}},
            "replacements": [{"value": "uno"}, {"value": "due"}],
        }, {"offset": "bad", "length": 2}],
    }

    assert _parse_matches(payload) == [{
        "offset": 4,
        "length": 3,
        "message": "Suggerimento",
        "short_message": "Stile",
        "rule_id": "TEST_RULE",
        "category": "STYLE",
        "replacements": ["uno", "due"],
    }]


def test_language_tool_offsets_round_trip():
    text = "Prima riga\nSeconda riga\nTerza"
    for position in (0, 4, 10, 11, len(text)):
        line, column = _absolute_to_line_col(text, position)
        assert _line_col_to_absolute(text, line, column) == position


def test_language_tool_skips_code_editors():
    assert _is_prose_editor(SimpleNamespace(_current_language="Markdown"))
    assert _is_prose_editor(SimpleNamespace(_current_language="Plain Text"))
    assert not _is_prose_editor(SimpleNamespace(_current_language="Python"))
    assert _is_prose_editor(SimpleNamespace(_current_language="LaTeX"))


def test_language_tool_skips_latex_file_extensions():
    editor = SimpleNamespace(
        _current_language="Plain Text",
        file_path=SimpleNamespace(suffix=".tex"),
    )
    assert _is_prose_editor(editor)


def test_language_tool_masks_latex_markup_preserving_offsets():
    source = (
        r"\section{This sentence has an errror}"
        "\n"
        r"\begin{equation}x^2 + y^2\end{equation}"
        "\n"
        r"Visible prose. % hidden comment with errror"
    )
    masked, visible = _mask_latex(source)

    assert len(masked) == len(source)
    assert masked.index("This sentence") == source.index("This sentence")
    assert "errror" in masked
    assert "hidden comment" not in masked
    assert "x^2" not in masked
    error_start = source.index("errror")
    assert all(visible[error_start:error_start + len("errror")])
    command_start = source.index(r"\section")
    assert not any(visible[command_start:command_start + len(r"\section")])


def test_plugin_manager_unloads_enabled_plugins():
    calls = []

    class Plugin:
        def on_unload(self):
            calls.append("unloaded")

    manager = object.__new__(PluginManager)
    manager._plugins = {
        "active": {"enabled": True, "instance": Plugin()},
        "inactive": {"enabled": False, "instance": Plugin()},
    }
    manager._main_window = object()

    manager.unload_all()

    assert calls == ["unloaded"]
    assert not manager._plugins["active"]["enabled"]
    assert not manager._plugins["inactive"]["enabled"]
    assert manager._main_window is None


def test_language_tool_server_process_is_terminated():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=(os.name != "nt"),
    )
    try:
        _terminate_server_process(process)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
