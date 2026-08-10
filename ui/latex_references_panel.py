"""Lightweight standalone LaTeX references panel.

This module is intentionally not installed by MainWindow.  Use
``LatexReferencesPanel.set_project`` from an embedding UI and connect its
``navigate_requested`` signal to the host's file-opening/navigation code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.latex_references import (
    LatexInclude,
    LatexLocation,
    LatexReference,
    LatexReferencesAnalysis,
    analyze_latex_project,
)


class _AnalysisWorker(QThread):
    completed = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, current_file: str | Path | None, content: str | None,
                 max_depth: int, generation: int) -> None:
        super().__init__()
        self._current_file = current_file
        self._content = content
        self._max_depth = max_depth
        self._generation = generation
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if self._cancelled:
            return
        try:
            result = analyze_latex_project(
                self._current_file, self._content, max_depth=self._max_depth,
            )
        except Exception as error:  # the UI must survive an unreadable project
            if not self._cancelled:
                self.failed.emit(self._generation, str(error))
            return
        if not self._cancelled:
            self.completed.emit(self._generation, result)


class LatexReferencesModel(QObject):
    """Worker-backed, reusable state holder for a project analysis.

    It has no visible UI and can be used without
    :class:`LatexReferencesPanel`.
    """

    analysis_ready = pyqtSignal(object)
    scan_started = pyqtSignal()
    scan_failed = pyqtSignal(str)
    navigate_requested = pyqtSignal(object, int, int)

    def __init__(self, parent=None, max_depth: int = 5) -> None:
        super().__init__(parent)
        self._max_depth = max_depth
        self._current_file: str | Path | None = None
        self._content: str | None = None
        self._generation = 0
        self._worker: _AnalysisWorker | None = None
        self._old_workers: list[_AnalysisWorker] = []
        self._analysis = LatexReferencesAnalysis(None, ())

    @property
    def analysis(self) -> LatexReferencesAnalysis:
        return self._analysis

    @property
    def definitions(self) -> tuple[LatexReference, ...]:
        return self._analysis.definitions

    @property
    def references(self) -> tuple[LatexReference, ...]:
        return self._analysis.references

    @property
    def undefined(self) -> tuple[LatexReference, ...]:
        return self._analysis.undefined

    @property
    def duplicates(self) -> tuple[LatexReference, ...]:
        return self._analysis.duplicates

    @property
    def unused(self) -> tuple[LatexReference, ...]:
        return self._analysis.unused

    @property
    def citations(self) -> tuple[LatexReference, ...]:
        return self._analysis.citations

    @property
    def missing_includes(self) -> tuple[LatexInclude, ...]:
        return self._analysis.missing_includes

    @property
    def missing_assets(self) -> tuple[LatexInclude, ...]:
        return self._analysis.missing_assets

    @property
    def includes(self) -> tuple[LatexInclude, ...]:
        return self._analysis.includes

    @property
    def assets(self) -> tuple[LatexInclude, ...]:
        return self._analysis.assets

    @property
    def undefined_citations(self) -> tuple[LatexReference, ...]:
        return self._analysis.undefined_citations

    @property
    def unused_citations(self) -> tuple[str, ...]:
        return self._analysis.unused_citations

    def set_project(self, current_file: str | Path | None,
                    content: str | None = None) -> None:
        """Set the project snapshot used by the next scan."""
        self._current_file = current_file
        self._content = content

    def refresh(self) -> LatexReferencesAnalysis:
        """Scan synchronously and return the new result."""
        self.cancel()
        self._generation += 1
        self._analysis = analyze_latex_project(
            self._current_file, self._content, max_depth=self._max_depth,
        )
        self.analysis_ready.emit(self._analysis)
        return self._analysis

    def refresh_async(self) -> None:
        """Scan in a QThread and publish only the newest result."""
        self.cancel()
        self._generation += 1
        generation = self._generation
        worker = _AnalysisWorker(
            self._current_file, self._content, self._max_depth, generation,
        )
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._worker = worker
        self._old_workers.append(worker)
        self.scan_started.emit()
        worker.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    def request_navigation(self, location: LatexLocation) -> None:
        """Emit navigation for an item selected by an embedding view."""
        self.navigate_requested.emit(location.file, location.line, location.column)

    def _cleanup_worker(self, worker: _AnalysisWorker) -> None:
        try:
            self._old_workers.remove(worker)
        except ValueError:
            pass

    def _on_completed(self, generation: int, result: LatexReferencesAnalysis) -> None:
        if generation != self._generation:
            return
        self._worker = None
        self._analysis = result
        self.analysis_ready.emit(result)

    def _on_failed(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self._worker = None
            self.scan_failed.emit(message)

    def close(self) -> None:
        """Cancel and wait briefly for a running scan."""
        self.cancel()
        for worker in tuple(self._old_workers):
            if worker.isRunning():
                worker.wait()
        self._old_workers.clear()


class LatexReferencesPanel(QWidget):
    """A small category view over :class:`LatexReferencesModel`.

    ``navigation_target`` is optional. If supplied, it is called with
    ``(path, line, column)`` in addition to the public Qt signal. This is a
    convenient adapter for hosts that prefer callbacks.
    """

    navigate_requested = pyqtSignal(object, int, int)
    analysis_changed = pyqtSignal(object)

    _CATEGORIES = (
        ("all", "All"),
        ("definitions", "Definitions"),
        ("references", "References"),
        ("undefined", "Undefined"),
        ("duplicates", "Duplicates"),
        ("unused", "Unused"),
        ("citations", "Citations"),
        ("undefined_citations", "Undefined citations"),
        ("missing_includes", "Missing includes"),
        ("missing_assets", "Missing assets"),
    )

    def __init__(self, model: LatexReferencesModel | None = None,
                 navigation_target: Callable[[Path, int, int], None] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.model = model or LatexReferencesModel(self)
        self._navigation_target = navigation_target
        self._build_ui()
        self.model.analysis_ready.connect(self._on_analysis)
        self.model.scan_failed.connect(self._on_scan_failed)
        self.model.navigate_requested.connect(self.navigate_requested)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        self._category = QComboBox()
        for value, label in self._CATEGORIES:
            self._category.addItem(label, value)
        self._category.currentIndexChanged.connect(self._rebuild)
        self._status = QLabel("No analysis")
        self._status.setStyleSheet("color: #888; font-size: 11px;")
        bar.addWidget(self._category, 1)
        bar.addWidget(self._status)
        layout.addLayout(bar)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Kind", "Key / path", "File", "Line"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.itemDoubleClicked.connect(self._activate)
        layout.addWidget(self._tree, 1)

    def set_project(self, current_file: str | Path | None,
                    content: str | None = None, *, asynchronous: bool = True) -> None:
        """Set a project snapshot and refresh it."""
        self.model.set_project(current_file, content)
        if asynchronous:
            self.model.refresh_async()
        else:
            self.model.refresh()

    def refresh(self, *, asynchronous: bool = True) -> None:
        if asynchronous:
            self.model.refresh_async()
        else:
            self.model.refresh()

    def _on_analysis(self, analysis: LatexReferencesAnalysis) -> None:
        self._status.setText(f"{len(analysis.files)} files")
        self._rebuild()
        self.analysis_changed.emit(analysis)

    def _on_scan_failed(self, message: str) -> None:
        self._status.setText("Scan failed")
        self._tree.clear()
        item = QTreeWidgetItem(["error", message, "", ""])
        self._tree.addTopLevelItem(item)

    def _items_for_category(self, category: str):
        analysis = self.model.analysis
        if category == "all":
            return (
                [("definition", item) for item in analysis.definitions]
                + [("reference", item) for item in analysis.references]
                + [("undefined", item) for item in analysis.undefined]
                + [("duplicate", item) for item in analysis.duplicates]
                + [("unused", item) for item in analysis.unused]
                + [("citation", item) for item in analysis.citations]
                + [("undefined citation", item) for item in analysis.undefined_citations]
                + [(item.kind, item) for item in analysis.missing_includes]
                + [(item.kind, item) for item in analysis.missing_assets]
            )
        values = getattr(analysis, category, ())
        return [(category.replace("_", " "), item) for item in values]

    def _rebuild(self) -> None:
        self._tree.clear()
        category = self._category.currentData()
        for kind, value in self._items_for_category(category):
            if isinstance(value, LatexReference):
                location = value.location
                key = value.key
            else:
                location = value.location
                key = value.requested
            item = QTreeWidgetItem([
                kind, key, location.file.name, str(location.line),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, location)
            item.setToolTip(2, str(location.file))
            self._tree.addTopLevelItem(item)
        self._tree.resizeColumnToContents(0)
        self._tree.resizeColumnToContents(3)

    def _activate(self, item: QTreeWidgetItem, _column: int) -> None:
        location = item.data(0, Qt.ItemDataRole.UserRole)
        if location is None or not hasattr(location, "file"):
            return
        self.model.request_navigation(location)
        if self._navigation_target is not None:
            self._navigation_target(location.file, location.line, location.column)

    def closeEvent(self, event) -> None:
        self.model.close()
        super().closeEvent(event)


__all__ = ["LatexReferencesModel", "LatexReferencesPanel"]
