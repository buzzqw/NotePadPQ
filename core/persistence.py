"""Small, durable helpers for application-owned persisted state."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _fsync_directory(path: Path) -> None:
    """Persist a replacement's directory entry where the platform supports it."""
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Write *data* via a synced sibling temporary file and replace it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        elif path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8",
                      errors: str | None = None) -> None:
    """Atomically write text without changing its requested encoding."""
    encode_kwargs = {"errors": errors} if errors is not None else {}
    atomic_write_bytes(path, text.encode(encoding, **encode_kwargs))


def atomic_write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Serialize JSON and atomically replace its destination."""
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n")


def archive_invalid_file(path: Path) -> Path | None:
    """Move an unreadable or invalid persisted file aside before it is replaced."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    archived = path.with_name(f"{path.name}.invalid-{stamp}-{uuid4().hex[:8]}")
    try:
        os.replace(path, archived)
        _fsync_directory(path.parent)
        return archived
    except OSError:
        # A copy still preserves the diagnostic data if the original cannot be renamed.
        try:
            shutil.copy2(path, archived)
            return archived
        except OSError:
            return None


def load_json(path: Path, *, validate: Callable[[Any], bool] | None = None,
              default: Any = None) -> Any:
    """Load valid JSON, archiving malformed or schema-invalid prior state.

    Filesystem failures are left in place because they are not evidence that the
    file content is bad. Invalid content is never silently overwritten later.
    """
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        archive_invalid_file(path)
        return default
    except OSError:
        return default
    if validate is not None and not validate(data):
        archive_invalid_file(path)
        return default
    return data
