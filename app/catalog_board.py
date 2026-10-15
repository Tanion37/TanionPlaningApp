"""Экран правок проектов и Preset."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .preset_store import delete_preset, list_preset_names, load_steps, rename_preset, root_indexes
from .project_roles import (
    PROJECT_LEAD,
    apply_executor_to_tasks,
    assign_executor,
    executor_for,
    forget_project,
    load_assignments,
    rename_project as rename_project_roles,
    roles_of_project,
)
from .projects import next_instance_name, preset_of_project, project_name_taken, resolve_project_name, same_project
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
        create = QPushButton("Новый")
        edit = QPushButton("Править")
        rename = QPushButton("Переименовать")
        remove = QPushButton("Удалить")
        create.clicked.connect(self._new_project)
        edit.clicked.connect(self._edit_project)
        rename.clicked.connect(self._rename_project)
        remove.clicked.connect(self._delete_project)
        row.addWidget(create)
        row.addWidget(edit)
        row.addWidget(rename)
        row.addWidget(remove)
        box.addLayout(row)
        host = QWidget()
        host.setLayout(box)
        return host

    def _presets_column(self) -> QWidget:
        box = QVBoxLayout()
        box.addWidget(QLabel("Preset проекта"))
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
        tasks = self.main.store.tasks
        for name in self.main._project_names():
            preset = preset_of_project(tasks, name)
            label = f"{name} — {preset}" if preset else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.projects.addItem(item)
        self.presets.clear()
        for name in list_preset_names():
            self.presets.addItem(name)
        self.apply_theme()

    def _current_project(self) -> str:
        item = self.projects.currentItem()
        if item is None:
            return ""
        stored = item.data(Qt.ItemDataRole.UserRole)
        return str(stored or item.text()).strip()

    def _current_preset(self) -> str:
        item = self.presets.currentItem()
        return item.text().strip() if item else ""

    def _new_project(self) -> None:
        presets = list_preset_names()
        if not presets:
            QMessageBox.information(self, "Проект", "Сначала сохраните Preset. Проект — это его запуск.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Новый проект")
        dialog.resize(420, 280)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel("Preset проекта"))
        preset_combo = QComboBox()
        for name in presets:
            preset_combo.addItem(name, name)
        box.addWidget(preset_combo)
        box.addWidget(QLabel("Название проекта"))
        def _free_name(preset: str) -> str:
            return next_instance_name(preset, self.main.store.tasks, load_assignments())

        name_edit = QLineEdit(_free_name(presets[0]))
        box.addWidget(name_edit)
        box.addWidget(QLabel(PROJECT_LEAD))
        lead_combo = QComboBox()
        lead_combo.addItem("", "")
        for person in self.main._executor_names():
            lead_combo.addItem(person, person)
        box.addWidget(lead_combo)

        def _fill_name() -> None:
            preset = str(preset_combo.currentData() or "")
            name_edit.setText(_free_name(preset))

        preset_combo.currentIndexChanged.connect(lambda _index: _fill_name())

        def _name_exists(name: str) -> bool:
            if project_name_taken(name, self.main.store.tasks):
                return True
            for existing in load_assignments():
                if same_project(existing, name):
                    return True
            return False

        def _accept() -> None:
            preset = str(preset_combo.currentData() or "").strip()
            name = name_edit.text().strip()
            lead = str(lead_combo.currentData() or "").strip()
            if not preset:
                QMessageBox.warning(dialog, "Проект", "Выберите Preset проекта.")
                return
            if not name:
                QMessageBox.warning(dialog, "Проект", "Укажите название проекта.")
                return
            if _name_exists(name):
                QMessageBox.warning(dialog, "Проект", "Название проекта уже существует.")
                return
            if not lead:
                QMessageBox.warning(
                    dialog,
                    "Проект",
                    "Назначьте исполнителя на роль «Руководитель проекта». "
                    "Без этого корневые задачи не уйдут во входящие.",
                )
                return
            if not root_indexes(load_steps(preset)):
                QMessageBox.warning(dialog, "Проект", "В этом Preset нет корневых задач.")
                return
            dialog.accept()

        save = QPushButton("Создать")
        save.clicked.connect(_accept)
        box.addWidget(save)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        preset = str(preset_combo.currentData() or "").strip()
        name = name_edit.text().strip()
        lead = str(lead_combo.currentData() or "").strip()
        if not preset or not name or not lead:
            return
        assign_executor(name, PROJECT_LEAD, lead)
        self.main.create_project_from_preset(name, preset)

    def _edit_project(self) -> None:
        old = self._current_project()
        if not old:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Править проект")
        dialog.resize(420, 520)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel("Название"))
        name_edit = QLineEdit(old)
        box.addWidget(name_edit)
        klass = preset_of_project(self.main.store.tasks, old)
        box.addWidget(QLabel(f"Preset: {klass}" if klass else "Preset: не задан"))
        role_combos: dict[str, QComboBox] = {}
        for role in roles_of_project(old, self.main.store.tasks):
            box.addWidget(QLabel(role))
            combo = QComboBox()
            combo.addItem("", "")
            current = executor_for(old, role)
            for person in self.main._executor_names():
                combo.addItem(person, person)
            if current:
                if combo.findData(current) < 0:
                    combo.addItem(current, current)
                combo.setCurrentIndex(combo.findData(current))
            role_combos[role] = combo
            box.addWidget(combo)
        box.addWidget(QLabel("Задачи проекта"))
        tasks = QListWidget()
        for task in self.main.store.tasks:
            if (task.project or "").strip() == old:
                tasks.addItem(task.title or task.id)
        box.addWidget(tasks, 1)
        save = QPushButton("Сохранить")
        save.clicked.connect(dialog.accept)
        box.addWidget(save)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        new = resolve_project_name(name_edit.text().strip(), self.main.store.tasks) or name_edit.text().strip()
        if not new:
            return
        if new != old:
            for task in self.main.store.tasks:
                if (task.project or "").strip() == old:
                    task.project = new
            rename_project_roles(old, new)
        for role, combo in role_combos.items():
            person = str(combo.currentData() or "").strip()
            if person:
                assign_executor(new, role, person)
                apply_executor_to_tasks(self.main.store, new, role, person)
        self.main.request_save()
        self.main.reload_boards()

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
        rename_project_roles(old, new)
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
        forget_project(name)
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
