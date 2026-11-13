"""Session-wide test isolation.

Without an application name, QStandardPaths.AppConfigLocation resolves to
``~/.config`` itself, so tests that save build profiles (and anything else
using ``core.platform.get_config_dir``) wrote straight into the user's real
config directory. Concurrent test runs also raced on those shared files.

Point the XDG base directories at a private temporary tree *before* any Qt
object is created, so every run is hermetic.
"""

import atexit
import os
import shutil
import tempfile

_ROOT = tempfile.mkdtemp(prefix="notepadpq-tests-")
for _var, _sub in (
    ("XDG_CONFIG_HOME", "config"),
    ("XDG_DATA_HOME", "data"),
    ("XDG_CACHE_HOME", "cache"),
    ("XDG_STATE_HOME", "state"),
):
    _path = os.path.join(_ROOT, _sub)
    os.makedirs(_path, exist_ok=True)
    os.environ[_var] = _path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
atexit.register(shutil.rmtree, _ROOT, ignore_errors=True)
