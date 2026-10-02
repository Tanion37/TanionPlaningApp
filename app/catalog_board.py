"""Экран правок проектов и Preset."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .preset_store import delete_preset, list_preset_names, rename_preset
from .projects import resolve_project_name
from .theme import board_style


class CatalogCanvas(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__()
        self.main = main_window
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addWidget(self._projects_column(), 1)
        root.addWidget(self._presets_column(), 1)
        self.apply_theme()

    def apply_theme(self) -> None:
        self.setStyleSheet(board_style())

    def _projects_column(self) -> QWidget:
        box = QVBoxLayout()
        box.addWidget(QLabel("Проекты"))
        self.projects = QListWidget()
        box.addWidget(self.projects, 1)
        row = QHBoxLayout()
        rename = QPushButton("Переименовать")
        remove = QPushButton("Удалить")
        rename.clicked.connect(self._rename_project)
        remove.clicked.connect(self._delete_project)
        row.addWidget(rename)
        row.addWidget(remove)
        box.addLayout(row)
        host = QWidget()
        host.setLayout(box)
        return host

    def _presets_column(self) -> QWidget:
        box = QVBoxLayout()
        box.addWidget(QLabel("Preset"))
        self.presets = QListWidget()
        box.addWidget(self.presets, 1)
        row = QHBoxLayout()
        edit = QPushButton("Править")
        rename = QPushButton("Переименовать")
        remove = QPushButton("Удалить")
        edit.clicked.connect(self._edit_preset)
        rename.clicked.connect(self._rename_preset)
        remove.clicked.connect(self._delete_preset)
        row.addWidget(edit)
        row.addWidget(rename)
        row.addWidget(remove)
        box.addLayout(row)
        host = QWidget()
        host.setLayout(box)
        return host

    def rebuild(self) -> None:
        self.projects.clear()
        for name in self.main._project_names():
            self.projects.addItem(name)
        self.presets.clear()
        for name in list_preset_names():
            self.presets.addItem(name)
        self.apply_theme()

    def _current_project(self) -> str:
        item = self.projects.currentItem()
        return item.text().strip() if item else ""

    def _current_preset(self) -> str:
        item = self.presets.currentItem()
        return item.text().strip() if item else ""

    def _rename_project(self) -> None:
        old = self._current_project()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Проект", "Новое название", text=old)
        if not ok:
            return
        new = resolve_project_name(new.strip(), self.main.store.tasks) or new.strip()
        if not new or new == old:
            return
        for task in self.main.store.tasks:
            if (task.project or "").strip() == old:
                task.project = new
        self.main.request_save()
        self.main.reload_boards()

    def _delete_project(self) -> None:
        name = self._current_project()
        if not name:
            return
        answer = QMessageBox.question(self, "Проект", f"Убрать проект «{name}» с задач?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        for task in self.main.store.tasks:
            if (task.project or "").strip() == name:
                task.project = ""
        self.main.request_save()
        self.main.reload_boards()

    def _edit_preset(self) -> None:
        name = self._current_preset()
        if name:
            self.main.open_preset_window(name)

    def _rename_preset(self) -> None:
        old = self._current_preset()
        if not old:
            return
        new, ok = QInputDialog.getText(self, "Preset", "Новое название", text=old)
        if not ok or not new.strip() or new.strip() == old:
            return
        stem = rename_preset(old, new.strip())
        for task in self.main.store.tasks:
            if (task.preset_name or "") == old:
                task.preset_name = stem
        self.main.request_save()
        self.main.reload_boards()

    def _delete_preset(self) -> None:
        name = self._current_preset()
        if not name:
            return
        answer = QMessageBox.question(self, "Preset", f"Удалить файл «{name}»?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_preset(name)
        self.rebuild()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._swipe_armed = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._swipe_armed
            and self._press_pos is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self.swipe_callback
        ):
            delta = event.position().toPoint() - self._press_pos
            if abs(delta.x()) > 80 and abs(delta.x()) > abs(delta.y()) * 2:
                self.swipe_callback(-1 if delta.x() < 0 else 1)
        self._swipe_armed = False
        self._press_pos = None
        super().mouseReleaseEvent(event)
