"""Окно «Новый Preset»: карточки и связи, сохранение в JSON."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .models import Task
from .preset_store import (
    chain_tasks_from_steps,
    load_steps,
    presets_dir,
    remove_with_outgoing,
    save_preset,
)
from .task_graph import add_linked_task, linked_task_title
from .widgets import TaskBlock


class PresetWindow(QDialog):
    def __init__(self, parent=None, preset_name: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новый Preset")
        self.resize(720, 640)
        self.saved_name = ""
        self.tasks: list[Task] = []
        self.selected_id: str | None = None
        if preset_name:
            self.tasks = chain_tasks_from_steps(load_steps(preset_name))
            self.saved_name = preset_name

        root = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.cards = QVBoxLayout(self.host)
        self.cards.addStretch(1)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        create_btn = QPushButton("Создать задачу")
        delete_btn = QPushButton("Удалить задачу")
        close_btn = QPushButton("Закрыть окно")
        save_btn = QPushButton("Сохранить")
        create_btn.clicked.connect(self._create_task)
        delete_btn.clicked.connect(self._delete_selected)
        close_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._save)
        buttons.addWidget(create_btn)
        buttons.addWidget(delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)
        self._rebuild()

    def _create_task(self) -> None:
        number = len(self.tasks) + 1
        self.tasks.append(Task(id=f"{number:03d}", title="Новая задача"))
        self.selected_id = self.tasks[-1].id
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
        for index in range(self.cards.count()):
            widget = self.cards.itemAt(index).widget()
            if isinstance(widget, TaskBlock) and widget.task.id == task_id:
                return widget
        return None

    def _mark(self) -> None:
        for index in range(self.cards.count()):
            widget = self.cards.itemAt(index).widget()
            if isinstance(widget, TaskBlock):
                widget.set_marked(widget.task.id == self.selected_id)

    def _rebuild(self) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for task in self.tasks:
            block = TaskBlock(task, show_catalogs=False)
            block.set_linked_title(linked_task_title(self.tasks, task))
            block.set_marked(task.id == self.selected_id)
            block.clicked.connect(self._select)
            block.add_linked.connect(self._on_add_linked)
            block.role_changed.connect(self._on_role)
            self.cards.addWidget(block)
        self.cards.addStretch(1)

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
