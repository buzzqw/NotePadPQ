"""
core/diagnostics.py - Optional performance diagnostics for NotePadPQ.

The profiler is deliberately opt-in.  When enabled it records only operation
names, timings, resource usage and safe metadata (never document contents).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TypeVar

_LOGGER_NAME = "notepadpq.diagnostics"
_DEFAULT_THRESHOLD_MS = 100.0
_MAX_SUMMARY_ITEMS = 20
_T = TypeVar("_T")

@dataclass
class _OperationStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0


_enabled = False
_threshold_ms = _DEFAULT_THRESHOLD_MS
_logger = logging.getLogger(_LOGGER_NAME)
_handler: RotatingFileHandler | None = None
_stats: dict[str, _OperationStats] = {}
_stats_lock = threading.Lock()
_notify_state = threading.local()


def profiling_requested() -> bool:
    """Return whether the user requested performance diagnostics."""
    value = os.environ.get("NOTEPADPQ_PROFILE", "")
    return "--profile" in os.sys.argv or value.lower() in {"1", "true", "yes", "on"}


def _default_log_path() -> Path:
    configured = os.environ.get("NOTEPADPQ_PROFILE_LOG")
    if configured:
        return Path(configured).expanduser()

    try:
        # Import lazily: this module is also usable by non-Qt unit tests.
        from core.platform import get_config_dir

        return get_config_dir() / "notepadpq-performance.log"
    except Exception:
        return Path.home() / ".config" / "NotePadPQ" / "notepadpq-performance.log"


def _safe_value(value: Any) -> str:
    """Render metadata without accidentally dumping document text."""
    if isinstance(value, Path):
        return value.name or str(value)
    text = str(value)
    return text.replace("\n", "\\n").replace("\r", "\\r")[:160]


def _format_fields(fields: dict[str, Any]) -> str:
    return " ".join(f"{key}={_safe_value(value)}" for key, value in fields.items())


def _rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def configure_diagnostics(
    *,
    enabled: bool | None = None,
    threshold_ms: float | None = None,
    log_path: Path | str | None = None,
) -> Path | None:
    """Configure the optional profiler and return its log path when enabled."""
    global _enabled, _threshold_ms, _handler

    if enabled is None:
        enabled = profiling_requested()
    if threshold_ms is None:
        configured_threshold = os.environ.get("NOTEPADPQ_PROFILE_THRESHOLD_MS")
        try:
            threshold_ms = float(configured_threshold) if configured_threshold else _DEFAULT_THRESHOLD_MS
        except ValueError:
            threshold_ms = _DEFAULT_THRESHOLD_MS

    _enabled = bool(enabled)
    _threshold_ms = max(0.0, float(threshold_ms))
    if not _enabled:
        if _handler is not None:
            _logger.removeHandler(_handler)
            _handler.close()
            _handler = None
        return None

    path = Path(log_path).expanduser() if log_path else _default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Reconfiguration is useful for tests and keeps duplicate handlers out of
    # the process when the application is embedded or restarted in-process.
    if _handler is not None:
        _logger.removeHandler(_handler)
        _handler.close()
    _handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    _logger.handlers.clear()
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    with _stats_lock:
        _stats.clear()
    _logger.info("diagnostics_started threshold_ms=%.1f pid=%s", _threshold_ms, os.getpid())
    return path


def log_qt_message(level: str, message: str, location: str = "") -> None:
    """Forward relevant Qt messages to the diagnostics log."""
    if not _enabled:
        return
    suffix = f" location={location}" if location else ""
    _logger.warning("qt_message level=%s message=%s%s", level, _safe_value(message), suffix)


def record_exception(name: str, exception: BaseException, traceback_text: str = "") -> None:
    if not _enabled:
        return
    fields = {"operation": name, "exception": type(exception).__name__, "message": str(exception)}
    if traceback_text:
        fields["traceback"] = traceback_text
    _logger.error("unhandled_exception %s", _format_fields(fields))


@contextmanager
def operation(name: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Measure an operation and log it if it exceeds the configured threshold."""
    if not _enabled:
        yield fields
        return

    started = time.perf_counter()
    rss_before = _rss_mb()
    try:
        yield fields
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _record_stats(name, elapsed_ms)
        details = dict(fields, operation=name, duration_ms=f"{elapsed_ms:.1f}", exception=type(exc).__name__)
        _logger.error("operation_failed %s", _format_fields(details))
        raise
    else:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _record_stats(name, elapsed_ms)
        rss_after = _rss_mb()
        rss_delta = None if rss_before is None or rss_after is None else rss_after - rss_before
        if elapsed_ms >= _threshold_ms or (rss_delta is not None and rss_delta >= 32.0):
            details = dict(fields, operation=name, duration_ms=f"{elapsed_ms:.1f}")
            if rss_after is not None:
                details["rss_mb"] = f"{rss_after:.1f}"
            if rss_delta is not None:
                details["rss_delta_mb"] = f"{rss_delta:+.1f}"
            _logger.warning("slow_operation %s", _format_fields(details))


def _record_stats(name: str, elapsed_ms: float) -> None:
    with _stats_lock:
        stats = _stats.setdefault(name, _OperationStats())
        stats.count += 1
        stats.total_ms += elapsed_ms
        stats.max_ms = max(stats.max_ms, elapsed_ms)


def profile_operation(name: str, **static_fields: Any) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    """Decorator counterpart of :func:`operation` for named application methods."""
    def decorator(function: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> _T:
            with operation(name, **static_fields):
                return function(*args, **kwargs)

        return wrapped

    return decorator


def shutdown_diagnostics() -> None:
    """Write an aggregate report and close the diagnostics file."""
    global _enabled, _handler
    if not _enabled:
        return

    with _stats_lock:
        entries = sorted(_stats.items(), key=lambda item: item[1].total_ms, reverse=True)
    _logger.info("performance_summary begin operations=%s", len(entries))
    for name, stats in entries[:_MAX_SUMMARY_ITEMS]:
        average = stats.total_ms / stats.count if stats.count else 0.0
        _logger.info(
            "performance_summary operation=%s count=%s total_ms=%.1f average_ms=%.1f max_ms=%.1f",
            name, stats.count, stats.total_ms, average, stats.max_ms,
        )
    _logger.info("diagnostics_finished")
    if _handler is not None:
        _handler.flush()
        _handler.close()
        _logger.removeHandler(_handler)
        _handler = None
    with _stats_lock:
        _stats.clear()
    _enabled = False


class ProfilingApplication(__import__("PyQt6.QtWidgets", fromlist=["QApplication"]).QApplication):
    """QApplication variant that reports slow event handlers."""

    def notify(self, receiver, event):  # noqa: N802 - Qt API name
        stack = getattr(_notify_state, "stack", None)
        if stack is None:
            stack = []
            _notify_state.stack = stack
        frame = {"had_nested_dispatch": False}
        if stack:
            stack[-1]["had_nested_dispatch"] = True
        stack.append(frame)
        started = time.perf_counter()
        try:
            return super().notify(receiver, event)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            stack.pop()
            # Modal dialogs and QMenu.exec() run a nested event loop. Their
            # outer event duration includes time spent waiting for the user,
            # so it is not a useful measure of handler performance.
            if _enabled and elapsed_ms >= _threshold_ms and not frame["had_nested_dispatch"]:
                event_type = getattr(getattr(event, "type", lambda: "unknown")(), "name", "unknown")
                receiver_name = type(receiver).__name__
                receiver_class = receiver_name
                object_name = "-"
                parent_class = "-"
                timer_id = "-"
                try:
                    receiver_class = receiver.metaObject().className()
                except (AttributeError, RuntimeError):
                    pass
                try:
                    object_name = receiver.objectName() or "-"
                except (AttributeError, RuntimeError):
                    pass
                try:
                    parent = receiver.parent()
                    if parent is not None:
                        parent_class = parent.metaObject().className()
                except (AttributeError, RuntimeError):
                    pass
                if event_type == "Timer":
                    try:
                        timer_id = event.timerId()
                    except AttributeError:
                        pass
                _logger.warning(
                    "slow_qt_event receiver=%s receiver_class=%s object_name=%s "
                    "parent=%s timer_id=%s event=%s duration_ms=%.1f",
                    receiver_name, receiver_class, object_name, parent_class,
                    timer_id, event_type, elapsed_ms,
                )


def install_event_loop_monitor(app) -> object | None:
    """Monitor delays in the GUI event loop, which indicate UI freezes."""
    if not _enabled:
        return None

    from PyQt6.QtCore import QTimer

    class _EventLoopMonitor:
        def __init__(self):
            self._last = time.perf_counter()
            self._timer = QTimer(app)
            self._timer.setInterval(250)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

        def _tick(self):
            now = time.perf_counter()
            expected_ms = self._timer.interval()
            delay_ms = (now - self._last) * 1000 - expected_ms
            self._last = now
            if delay_ms >= _threshold_ms:
                _logger.warning("event_loop_lag delay_ms=%.1f", delay_ms)

    monitor = _EventLoopMonitor()
    app.aboutToQuit.connect(shutdown_diagnostics)
    return monitor
