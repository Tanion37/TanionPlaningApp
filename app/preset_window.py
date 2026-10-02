"""Окно «Новый Preset»: карточки и связи, сохранение в JSON."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import Task
from .preset_store import (
    load_steps,
    presets_dir,
    remove_with_outgoing,
    save_preset,
    tasks_from_steps,
)
from .task_graph import add_linked_task, linked_task_title
from .widgets import TASK_W, TaskBlock


class PresetWindow(QDialog):
    def __init__(self, parent=None, preset_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новый Preset")
        self.resize(720, 640)
        self.saved_name = ""
        self.tasks: list[Task] = []
        self.selected_id: str | None = None
        self._blocks: list[TaskBlock] = []
        self._cols = 0
        if preset_name:
            self.tasks = tasks_from_steps(load_steps(preset_name))
            self.saved_name = preset_name

        root = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        create_btn = QPushButton("Создать задачу")
        delete_btn = QPushButton("Удалить задачу")
        save_btn = QPushButton("Сохранить")
        create_btn.clicked.connect(self._create_task)
        delete_btn.clicked.connect(self._delete_selected)
        save_btn.clicked.connect(self._save)
        buttons.addWidget(create_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        self._rebuild()

    def _create_task(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Создать задачу")
        box = QVBoxLayout(dialog)
        form = QFormLayout()
        title_edit = QLineEdit()
        parent_box = QComboBox()
        parent_box.addItem("Корневая задача", "")
        for task in self.tasks:
            label = (task.title or task.id).strip()
            parent_box.addItem(label, task.id)
        form.addRow("Название", title_edit)
        form.addRow("Связать с", parent_box)
        box.addLayout(form)
        row = QHBoxLayout()
        ok_btn = QPushButton("ОК")
        cancel_btn = QPushButton("Отмена")
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        box.addLayout(row)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        title = title_edit.text().strip()
        if not title:
            return
        parent_id = str(parent_box.currentData() or "")
        if parent_id:
            parent = next((task for task in self.tasks if task.id == parent_id), None)
            if parent is None:
                return
            created = add_linked_task(self.tasks, parent, title)
            if created is None:
                return
            self.selected_id = created.id
        else:
            used = {task.id for task in self.tasks}
            number = 1
            while f"{number:03d}" in used:
                number += 1
            created = Task(id=f"{number:03d}", title=title)
            self.tasks.append(created)
            self.selected_id = created.id
        self._rebuild()

    def _delete_selected(self) -> None:
        if not self.selected_id:
            return
        remove_with_outgoing(self.tasks, self.selected_id)
        self.selected_id = None
        self._rebuild()

    def _on_add_linked(self, task_id: str, title: str, drafts: object = ()) -> None:
        parent = next((task for task in self.tasks if task.id == task_id), None)
        if parent is None:
            return
        add_linked_task(self.tasks, parent, title)
        self._rebuild()
        block = self._block_for(task_id)
        if block is not None:
            block.restore_drafts([str(item) for item in (drafts or [])])

    def _on_role(self, task_id: str, role: str) -> None:
        for task in self.tasks:
            if task.id == task_id:
                task.role = role
                return

    def _select(self, task_id: str) -> None:
        self.selected_id = task_id
        self._mark()

    def _block_for(self, task_id: str) -> TaskBlock | None:
        for block in self._blocks:
            if block.task.id == task_id:
                return block
        return None

    def _mark(self) -> None:
        for block in self._blocks:
            block.set_marked(block.task.id == self.selected_id)

    def _rebuild(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._blocks = []
        for task in self.tasks:
            block = TaskBlock(task)
            block.set_linked_title(linked_task_title(self.tasks, task))
            block.set_marked(task.id == self.selected_id)
            block.clicked.connect(self._select)
            block.add_linked.connect(self._on_add_linked)
            block.role_changed.connect(self._on_role)
            self._blocks.append(block)
        self._cols = 0
        self._reflow()

    def _reflow(self) -> None:
        if not self._blocks:
            return
        width = max(TASK_W, self.scroll.viewport().width() - 8)
        cols = max(1, width // (TASK_W + 12))
        if cols == self._cols:
            return
        self._cols = cols
        for block in self._blocks:
            self.grid.removeWidget(block)
        for index, block in enumerate(self._blocks):
            row, col = divmod(index, cols)
            self.grid.addWidget(block, row, col, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._cols = 0
        self._reflow()

    def _save(self) -> None:
        named = [task for task in self.tasks if (task.title or "").strip()]
        if not named:
            QMessageBox.information(self, "Новый Preset", "Создайте хотя бы одну задачу.")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Название файла JSON",
            str(presets_dir() / (self.saved_name or "preset.json")),
            "JSON (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        stem = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if stem.lower().endswith(".json"):
            stem = stem[:-5]
        saved = save_preset(stem, self.tasks)
        self.saved_name = saved.stem
        self.accept()
