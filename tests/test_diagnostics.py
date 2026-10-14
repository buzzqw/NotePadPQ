import logging
import time
from pathlib import Path

from core import diagnostics


def test_operation_records_slow_operation_and_summary(tmp_path: Path):
    log_path = tmp_path / "performance.log"
    diagnostics.configure_diagnostics(enabled=True, threshold_ms=0, log_path=log_path)
    try:
        with diagnostics.operation("test.operation", size_bytes=12):
            time.sleep(0.002)

        diagnostics.shutdown_diagnostics()
        text = log_path.read_text(encoding="utf-8")
        assert "slow_operation" in text
        assert "operation=test.operation" in text
        assert "performance_summary" in text
        assert "size_bytes=12" in text
    finally:
        # shutdown_diagnostics is idempotent and also protects the test suite
        # if an assertion above fails.
        diagnostics.shutdown_diagnostics()


def test_profiling_is_disabled_by_default(caplog):
    diagnostics.configure_diagnostics(enabled=False)
    with caplog.at_level(logging.DEBUG):
        with diagnostics.operation("test.disabled"):
            pass
    assert "test.disabled" not in caplog.text
