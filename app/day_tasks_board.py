"""Экран «Задачи дня»: Входящие | Контроль | Горит/Нужно/Можно | ДЕНЬ."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .day_hide import without_hidden as without_day_hidden
from .day_tasks import (
    SECTION_GORIT,
    SECTION_MOZHNO,
    SECTION_NUZHNO,
    UNTAGGED_SECTION,
    apply_priority_section,
    control_tasks,
    day_tag_counts,
    executor_sections,
    inbox_tasks,
    pack_day_columns,
    priority_sections,
    refresh_inbox_tags,
    release_inbox_outside_inbox,
    section_heading,
)
from .layout_metrics import content_side_margins
from .theme import readable
from .models import Task
from .tags import display_symbol
from .widgets import TASK_BLOCK_H, TASK_W, TagBar, TagCircle, TaskBlock

COL_W = TASK_W + 24
COL_GAP = 12


class DropSection(QFrame):
    """Раздел Горит/Нужно/Можно — drop задач; заголовок = кисть."""

    task_dropped = pyqtSignal(str, str)  # task_id, section
    title_clicked = pyqtSignal(str)  # section

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = title
        self.setAcceptDrops(True)
        self._paint_on = False
        self._drop_on = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 8, 6, 10)
        self._layout.setSpacing(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_lab = QLabel(title)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        self.title_lab.setFont(font)
        self.title_lab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_lab.setToolTip(f"Кисть «{title}»: клик по задачам = как drop сюда")
        self.title_lab.mousePressEvent = self._on_title_press  # type: ignore[method-assign]
        self._layout.addWidget(self.title_lab)
        self._blocks_host = QVBoxLayout()
        self._blocks_host.setSpacing(8)
        self._layout.addLayout(self._blocks_host)
        self._drop_pad = QWidget()
        self._drop_pad.setFixedHeight(36)
        self._layout.addWidget(self._drop_pad)
        self._apply_chrome()

    def _on_title_press(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.title_clicked.emit(self.section)
            event.accept()
            return
        QLabel.mousePressEvent(self.title_lab, event)

    def clear_tasks(self) -> None:
        while self._blocks_host.count():
            item = self._blocks_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sync_drop_pad()

    def add_block(self, block: TaskBlock) -> None:
        self._blocks_host.addWidget(block)
        self._sync_drop_pad()

    def place_blocks(self, blocks: list[TaskBlock]) -> None:
        """Поставить карточки в том же порядке. Уже стоящие виджеты не создавать заново."""
        current: list[TaskBlock] = []
        for index in range(self._blocks_host.count()):
            widget = self._blocks_host.itemAt(index).widget()
            if isinstance(widget, TaskBlock):
                current.append(widget)
        if current == blocks:
            self._sync_drop_pad()
            return
        while self._blocks_host.count():
            item = self._blocks_host.takeAt(0)
            widget = item.widget()
            if isinstance(widget, TaskBlock) and widget not in blocks:
                widget.setParent(None)
        for block in blocks:
            block.show()
            self._blocks_host.addWidget(block)
        self._sync_drop_pad()

    def _sync_drop_pad(self) -> None:
        """Пустое поле оставляет полосу для drop и не растягивается на карточку."""
        self._drop_pad.setVisible(self._blocks_host.count() == 0)
        self.updateGeometry()

    def set_paint_highlight(self, on: bool) -> None:
        if on == self._paint_on:
            return
        self._paint_on = on
        self._apply_chrome()

    def set_drop_highlight(self, on: bool) -> None:
        if on == self._drop_on:
            return
        self._drop_on = on
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        if self._drop_on:
            self.setStyleSheet(
                "DropSection { background:#FFF8E1; border:2px solid #FF8C00; border-radius:4px; }"
            )
            self.title_lab.setStyleSheet("color:#E65100; font-weight:700;")
        elif self._paint_on:
            self.setStyleSheet(
                "DropSection { background:#E3F2FD; border:2px solid #1976D2; border-radius:4px; }"
            )
            self.title_lab.setStyleSheet("color:#1565C0; font-weight:700;")
        else:
            self.setStyleSheet(
                "DropSection { background:#FFFFFF; border:1px solid #DDDDDD; border-radius:4px; }"
            )
            self.title_lab.setStyleSheet("color:#333;")

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat("application/x-tanion-task") or event.mimeData().hasText():
            event.acceptProposedAction()
            self.set_drop_highlight(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_drop_highlight(False)
        mime = event.mimeData()
        tid = ""
        if mime.hasFormat("application/x-tanion-task"):
            tid = bytes(mime.data("application/x-tanion-task")).decode("utf-8")
        elif mime.hasText():
            tid = mime.text().strip()
        if tid:
            self.task_dropped.emit(tid, self.section)
            event.acceptProposedAction()
        else:
            event.ignore()


class DayColumnSection(QWidget):
    """Раздел колонки ДЕНЬ. Живёт, пока в нём есть задачи: карточки только переставляются."""

    def __init__(self, canvas: "DayTasksCanvas", kind: str, name: str) -> None:
        super().__init__(canvas)
        self.kind = kind
        self.name = name
        self.stretch = 1 if kind == "executor" else 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        head = QHBoxLayout()
        if kind == "executor":
            lab = QLabel(name)
            lab.setStyleSheet(f"color:{readable('#444444')}; font-weight:600;")
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.setToolTip(
                f"Кисть «{name}»: клик по задаче или drop сюда ставит исполнителя, "
                "снимает входящую и делает актуальной"
            )
            lab.mousePressEvent = (  # type: ignore[method-assign]
                lambda event, section=name: canvas._on_heading_press(event, "executor", section)
            )
            head.addWidget(lab, 1)
            canvas._executor_labels[name] = lab
            canvas._executor_widgets[name] = self
        elif name == UNTAGGED_SECTION:
            lab = QLabel(section_heading(name))
            lab.setStyleSheet(f"color:{readable('#444444')}; font-weight:600;")
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.mousePressEvent = (  # type: ignore[method-assign]
                lambda event, section=name: canvas._on_heading_press(event, "tag", section)
            )
            head.addWidget(lab, 1)
        else:
            symbol = display_symbol(name) or name[:2]
            circle = TagCircle(name, symbol, self, draggable=True, reorderable=False)
            circle.clicked.connect(lambda key=name: canvas.main.on_section_tag_circle(key))
            canvas._day_tag_circles[name] = circle
            head.addWidget(circle)
            lab = QLabel(section_heading(name))
            lab.setStyleSheet(f"color:{readable('#444444')}; font-weight:600;")
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.mousePressEvent = (  # type: ignore[method-assign]
                lambda event, section=name: canvas._on_heading_press(event, "tag", section)
            )
            head.addWidget(lab, 1)
        layout.addLayout(head)
        self._blocks = QVBoxLayout()
        self._blocks.setSpacing(6)
        layout.addLayout(self._blocks)
        if kind == "executor":
            send_btn = QPushButton("Отправить в Telegram")
            send_btn.setToolTip(f"Список задач «{name}» в чат PGD studio AI")
            send_btn.clicked.connect(
                lambda _checked=False, executor=name: canvas.main.send_executor_list(executor)
            )
            layout.addWidget(send_btn)
            layout.addStretch(1)

    def place_blocks(self, blocks: list[TaskBlock]) -> None:
        current: list[TaskBlock] = []
        for index in range(self._blocks.count()):
            widget = self._blocks.itemAt(index).widget()
            if isinstance(widget, TaskBlock):
                current.append(widget)
        if current == blocks:
            return
        while self._blocks.count():
            item = self._blocks.takeAt(0)
            widget = item.widget()
            if isinstance(widget, TaskBlock) and widget not in blocks:
                widget.setParent(None)
        for block in blocks:
            block.show()
            self._blocks.addWidget(block)


class DayTasksCanvas(QWidget):
    """Холст экрана Задачи дня."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main = main_window
        self.screen_id = "day_tasks"
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False
        self._blocks: list[TaskBlock] = []
        self._block_by_key: dict[tuple, TaskBlock] = {}
        self._layout_sig: tuple | None = None
        self._day_structure: tuple | None = None
        self._day_column_widgets: list[QWidget] = []
        self._day_sections: dict[tuple[str, str], DayColumnSection] = {}
        self._day_tag_circles: dict[str, TagCircle] = {}
        self._last_day_pack: tuple[int, int] | None = None
        self._day_relayouting = False
        self._in_rebuild = False
        self._rebuild_queued = False
        self._width_fix_pending = False
        self._force_col_count: int | None = None
        self._defer_inbox_hook = False
        self._section_ids: dict[tuple[str, str], list[str]] = {}
        self._executor_labels: dict[str, QLabel] = {}
        self._executor_widgets: dict[str, QWidget] = {}
        self._executor_drop: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.body = QWidget()
        self.root = QHBoxLayout(self.body)
        self.root.setContentsMargins(8, 8, 8, 8)
        self.root.setSpacing(COL_GAP)

        f = QFont("Segoe UI", 11)
        f.setBold(True)

        # Входящие
        self.inbox_wrap = QWidget()
        self.inbox_wrap.setFixedWidth(COL_W)
        inbox_l = QVBoxLayout(self.inbox_wrap)
        inbox_l.setContentsMargins(0, 0, 0, 0)
        inbox_title = QLabel("Входящие")
        inbox_title.setFont(f)
        inbox_title.setCursor(Qt.CursorShape.PointingHandCursor)
        inbox_title.setToolTip(
            "Кисть Завтра / Неделя / Месяц / Бэклог / Входящие / исполнитель — ко всем задачам раздела"
        )
        inbox_title.mousePressEvent = lambda event: self._on_heading_press(event, "inbox", "inbox")  # type: ignore[method-assign]
        inbox_l.addWidget(inbox_title)
        self.inbox_scroll = QScrollArea()
        self.inbox_scroll.setWidgetResizable(True)
        self.inbox_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inbox_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inbox_inner = QWidget()
        self.inbox_layout = QVBoxLayout(self.inbox_inner)
        self.inbox_layout.setContentsMargins(0, 0, 0, 0)
        self.inbox_layout.setSpacing(6)
        self.inbox_scroll.setWidget(self.inbox_inner)
        inbox_l.addWidget(self.inbox_scroll, 1)
        self.root.addWidget(self.inbox_wrap)

        # Контроль
        self.control_wrap = QWidget()
        self.control_wrap.setFixedWidth(COL_W)
        control_l = QVBoxLayout(self.control_wrap)
        control_l.setContentsMargins(0, 0, 0, 0)
        control_title = QLabel("Контроль")
        control_title.setFont(f)
        control_title.setCursor(Qt.CursorShape.PointingHandCursor)
        control_title.setToolTip(
            "Кисть Завтра / Неделя / Месяц / Бэклог / Входящие / исполнитель — ко всем задачам раздела"
        )
        control_title.mousePressEvent = lambda event: self._on_heading_press(  # type: ignore[method-assign]
            event, "control", "control"
        )
        control_l.addWidget(control_title)
        self.control_scroll = QScrollArea()
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.control_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.control_inner = QWidget()
        self.control_layout = QVBoxLayout(self.control_inner)
        self.control_layout.setContentsMargins(0, 0, 0, 0)
        self.control_layout.setSpacing(6)
        self.control_scroll.setWidget(self.control_inner)
        control_l.addWidget(self.control_scroll, 1)
        self.root.addWidget(self.control_wrap)

        # Приоритет
        self.prio_wrap = QWidget()
        self.prio_wrap.setFixedWidth(COL_W + 8)
        prio_outer = QVBoxLayout(self.prio_wrap)
        prio_outer.setContentsMargins(0, 0, 0, 0)
        prio_title = QLabel("Приоритет")
        prio_title.setFont(f)
        prio_outer.addWidget(prio_title)
        self.prio_scroll = QScrollArea()
        self.prio_scroll.setWidgetResizable(True)
        self.prio_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.prio_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.prio_inner = QWidget()
        self.prio_layout = QVBoxLayout(self.prio_inner)
        self.prio_layout.setContentsMargins(0, 0, 0, 0)
        self.prio_layout.setSpacing(8)
        self.sec_gorit = DropSection(SECTION_GORIT)
        self.sec_nuzhno = DropSection(SECTION_NUZHNO)
        self.sec_mozhno = DropSection(SECTION_MOZHNO)
        for sec in (self.sec_gorit, self.sec_nuzhno, self.sec_mozhno):
            sec.task_dropped.connect(self._on_section_drop)
            sec.title_clicked.connect(self.main.on_priority_pick)
            self.prio_layout.addWidget(sec)
        self.prio_layout.addStretch(1)
        self.prio_scroll.setWidget(self.prio_inner)
        prio_outer.addWidget(self.prio_scroll, 1)
        self.root.addWidget(self.prio_wrap)

        # ДЕНЬ
        day_wrap = QWidget()
        day_l = QVBoxLayout(day_wrap)
        day_l.setContentsMargins(0, 0, 0, 0)
        day_title = QLabel("ДЕНЬ")
        day_title.setFont(f)
        day_l.addWidget(day_title)
        self.day_scroll = QScrollArea()
        self.day_scroll.setWidgetResizable(True)
        self.day_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.day_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.day_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.day_inner = QWidget()
        self.day_layout = QHBoxLayout(self.day_inner)
        self.day_layout.setContentsMargins(0, 0, 0, 0)
        self.day_layout.setSpacing(COL_GAP)
        self.day_scroll.setWidget(self.day_inner)
        day_l.addWidget(self.day_scroll, 1)
        self.root.addWidget(day_wrap, 1)

        outer.addWidget(self.body, 1)

        self.tag_bar = TagBar(self)
        self.tag_bar.tag_clicked.connect(self.main.on_tag_pick)
        self.tag_bar.order_changed.connect(self.main.on_tag_order_changed)
        outer.addWidget(self.tag_bar)
        self.setProperty("tag_bar", self.tag_bar)

        self.setStyleSheet("background:#FAFAF7;")
        self._apply_side_margins()

    def _on_heading_press(self, event, kind: str, name: str) -> None:  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self.main.on_day_section_click(kind, name)
            event.accept()
            return
        event.ignore()

    def section_task_ids(self, kind: str, name: str) -> list[str]:
        return list(self._section_ids.get((kind, name), []))

    def _apply_side_margins(self, controls_on_left: bool | None = None) -> None:
        """Сдвиг контента от панели кнопок (не накладывать на задачи)."""
        if controls_on_left is None:
            on_left = bool(getattr(self.main, "_controls_on_left", False))
        else:
            on_left = controls_on_left
        left, right = content_side_margins(on_left)
        self.root.setContentsMargins(left, 8, right, 8)

    def _estimate_day_width(
        self, *, has_inbox: bool, has_control: bool, controls_on_left: bool
    ) -> int:
        """Ширина зоны ДЕНЬ без ожидания пересчёта layout после hide колонок."""
        left, right = content_side_margins(controls_on_left)
        total = max(self.width(), self.body.width(), 400)
        used = left + right
        if has_inbox:
            used += COL_W + COL_GAP
        if has_control:
            used += COL_W + COL_GAP
        used += (COL_W + 8) + COL_GAP  # Приоритет
        return max(COL_W, total - used)

    def tag_at_global(self, global_pos: QPoint) -> str | None:
        key = self.tag_bar.tag_at_global(global_pos)
        if key:
            return key
        for tag_key, circle in self._day_tag_circles.items():
            local = circle.mapFromGlobal(global_pos)
            if circle.rect().contains(local):
                return tag_key
        return None

    def set_tag_highlight(self, key: str | None) -> None:
        self.tag_bar.set_highlight(key)
        for tag_key, circle in self._day_tag_circles.items():
            circle.set_highlighted(tag_key == key)

    def set_priority_highlight(self, section: str | None) -> None:
        for sec in (self.sec_gorit, self.sec_nuzhno, self.sec_mozhno):
            sec.set_paint_highlight(sec.section == section)

    def set_executor_highlight(self, name: str | None) -> None:
        for key, lab in self._executor_labels.items():
            if name and key == name:
                lab.setStyleSheet(
                    "color:#1a5fb4; font-weight:700; background:#DCEBFF; padding:1px 4px;"
                )
            else:
                lab.setStyleSheet(f"color:{readable('#444444')}; font-weight:600;")

    def executor_at_global(self, global_pos: QPoint) -> str | None:
        for name, w in self._executor_widgets.items():
            local = w.mapFromGlobal(global_pos)
            if w.isVisible() and w.rect().contains(local):
                return name
        return None

    def set_executor_drop_highlight(self, name: str | None) -> None:
        if name == self._executor_drop:
            return
        self._executor_drop = name
        for key, w in self._executor_widgets.items():
            if name and key == name:
                w.setStyleSheet(
                    "background:#FFF8E1; border:2px solid #FF8C00; border-radius:4px;"
                )
            else:
                w.setStyleSheet("")

    def _card_fp(self, task: Task, linked: str) -> tuple:
        return (
            task.title,
            task.project,
            task.executor,
            task.role,
            tuple(task.tags or ()),
            task.start_at,
            task.due_at,
            task.completed_at,
            task.remind_at,
            int(task.deleted or 0),
            linked,
        )

    def _make_block(self, task: Task, linked: str) -> TaskBlock:
        block = TaskBlock(task, self, executor_names=self.main._executor_names())
        block.hide()
        block.dropped_on_tag.connect(lambda tid, key: self.main.apply_action_to_task(tid, key))
        block.tag_dropped.connect(lambda tid, key: self.main.apply_action_to_task(tid, key))
        block.double_clicked.connect(self.main.edit_task)
        block.project_clicked.connect(self.main.on_project_filter)
        block.clicked.connect(self.main.on_task_clicked)
        block.role_changed.connect(self.main.on_task_role)
        block.executor_changed.connect(self.main.on_assignment_executor)
        block.add_linked.connect(self.main.on_task_add_linked)
        block.set_linked_title(linked)
        block.set_marked(task.id == self.main.selected_task_id)
        block._day_fp = self._card_fp(task, linked)
        return block

    def _refresh_block(self, block: TaskBlock, task: Task, linked: str) -> None:
        marked = task.id == self.main.selected_task_id
        fp = self._card_fp(task, linked)
        if block.task is not task or getattr(block, "_day_fp", None) != fp:
            block.update_task(task)
            block.set_linked_title(linked)
            block._day_fp = fp
        if block._marked != marked:
            block.set_marked(marked)

    def _sync_blocks(self, slots: list[tuple[tuple, Task]], titles: dict[str, str]) -> None:
        from .project_roles import is_role_and_executor_task

        names = tuple(self.main._executor_names())
        wanted = {key: task for key, task in slots}
        for key in list(self._block_by_key):
            if key not in wanted:
                block = self._block_by_key.pop(key)
                block.hide()
                block.setParent(None)
                block.deleteLater()
        for key, task in wanted.items():
            linked = titles.get(task.id, "")
            shape = is_role_and_executor_task(task)
            block = self._block_by_key.get(key)
            if block is not None and (
                block._role_assignment != shape or tuple(block._executor_names) != names
            ):
                block.hide()
                block.setParent(None)
                block.deleteLater()
                block = None
            if block is None:
                block = self._make_block(task, linked)
                self._block_by_key[key] = block
            else:
                self._refresh_block(block, task, linked)
        self._blocks = list(self._block_by_key.values())

    def _blocks_lifted(self) -> bool:
        """Карточка снята с колонки на время drag — её надо вернуть в раскладку."""
        return any(block.parentWidget() is self for block in self._block_by_key.values())

    def _place_sequence(self, layout, blocks: list[TaskBlock], *, stretch: bool) -> None:
        current: list[TaskBlock] = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if isinstance(widget, TaskBlock):
                current.append(widget)
        if current == blocks:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if isinstance(widget, TaskBlock) and widget not in blocks:
                widget.setParent(None)
        for block in blocks:
            block.show()
            layout.addWidget(block)
        if stretch:
            layout.addStretch(1)

    def _section_blocks(self, kind: str, name: str, tasks: list[Task]) -> list[TaskBlock]:
        if kind == "inbox":
            return [self._block_by_key[("inbox", task.id)] for task in tasks]
        if kind == "control":
            return [self._block_by_key[("control", task.id)] for task in tasks]
        if kind == "priority":
            return [self._block_by_key[("priority", name, task.id)] for task in tasks]
        return [self._block_by_key[(kind, name, task.id)] for task in tasks]

    def _apply_paint(self) -> None:
        paint_key = None
        exec_paint = None
        pm = getattr(self.main, "paint_mode", None)
        if pm and pm[0] == "tag":
            paint_key = pm[1]
        elif pm and pm[0] == "executor":
            exec_paint = pm[1]
        self.tag_bar.rebuild_circles()
        self.tag_bar.set_active_filter(self.main.filter_tag)
        if paint_key is not None:
            self.tag_bar.set_highlight(paint_key)
            self.set_tag_highlight(paint_key)
        if exec_paint is not None:
            self.set_executor_highlight(exec_paint)
        if pm and pm[0] == "priority":
            self.set_priority_highlight(pm[1])
        else:
            self.set_priority_highlight(None)

    def _place_day(
        self,
        packed: list[list[tuple[str, list[Task]]]],
        exec_names: set[str],
        avail_h: int,
    ) -> None:
        columns_spec: list[list[tuple[str, str, list[Task]]]] = []
        for column in packed:
            spec: list[tuple[str, str, list[Task]]] = []
            for tag, tasks in column:
                kind = "executor" if tag in exec_names else "tag"
                spec.append((kind, tag, tasks))
            columns_spec.append(spec)
        structure = tuple(tuple((kind, name) for kind, name, _tasks in spec) for spec in columns_spec)
        if structure == self._day_structure and self._day_column_widgets:
            for column in self._day_column_widgets:
                column.setMinimumHeight(avail_h)
            for spec in columns_spec:
                for kind, name, tasks in spec:
                    self._day_sections[(kind, name)].place_blocks(
                        self._section_blocks(kind, name, tasks)
                    )
            return
        live = {(kind, name) for spec in columns_spec for kind, name, _tasks in spec}
        for key in list(self._day_sections):
            if key in live:
                continue
            section = self._day_sections.pop(key)
            if key[0] == "tag":
                self._day_tag_circles.pop(key[1], None)
            else:
                self._executor_labels.pop(key[1], None)
                self._executor_widgets.pop(key[1], None)
            section.hide()
            section.setParent(None)
            section.deleteLater()
        for section in self._day_sections.values():
            section.setParent(self)
            section.hide()
        while self.day_layout.count():
            item = self.day_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._day_column_widgets = []
        for spec in columns_spec:
            column = QWidget()
            column.setFixedWidth(COL_W)
            column.setMinimumHeight(avail_h)
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(0)
            for kind, name, tasks in spec:
                section = self._day_sections.get((kind, name))
                if section is None:
                    section = DayColumnSection(self, kind, name)
                    self._day_sections[(kind, name)] = section
                section.place_blocks(self._section_blocks(kind, name, tasks))
                section.show()
                column_layout.addWidget(section, section.stretch, Qt.AlignmentFlag.AlignTop)
            column_layout.addStretch(1)
            self.day_layout.addWidget(column, 0, Qt.AlignmentFlag.AlignTop)
            self._day_column_widgets.append(column)
        self.day_layout.addStretch(1)
        self._day_structure = structure

    def _note_day_width(self) -> None:
        """После раскладки один раз сверить число колонок с реальной шириной."""
        if self._width_fix_pending:
            return
        self._width_fix_pending = True
        QTimer.singleShot(0, self._fix_day_width)

    def _fix_day_width(self) -> None:
        self._width_fix_pending = False
        if not self.isVisible() or self._in_rebuild:
            return
        avail_w = max(COL_W, self.day_scroll.viewport().width() - 8)
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        prev = self._last_day_pack
        if prev is not None and col_count != prev[0]:
            self._force_col_count = col_count
            self.rebuild()

    def rebuild(self, *, defer_inbox_hook: bool = False) -> None:
        del defer_inbox_hook
        if self._in_rebuild:
            self._rebuild_queued = True
            return
        self._in_rebuild = True
        try:
            self._rebuild_now()
        finally:
            self._in_rebuild = False
        if self._rebuild_queued:
            self._rebuild_queued = False
            self.rebuild()
            return
        self._note_day_width()

    def _rebuild_now(self) -> None:
        today = date.today()
        if not self.main.demo_mode:
            changed = refresh_inbox_tags(self.main.store.tasks, today)
            if release_inbox_outside_inbox(self.main.store.tasks):
                changed = True
            if changed:
                self.main.request_save()
        all_tasks = self.main.visible_tasks()
        from .task_graph import linked_title_map

        titles = linked_title_map(all_tasks)
        tasks = without_day_hidden(all_tasks)
        inbox = inbox_tasks(tasks)
        control = control_tasks(tasks)
        sections = priority_sections(tasks)
        exec_sections = executor_sections(tasks)
        tag_sections = day_tag_counts(tasks)
        has_inbox = bool(inbox)
        has_control = bool(control)
        if hasattr(self.main, "on_day_inbox_changed"):
            self.main.on_day_inbox_changed(has_inbox, has_control)
        self._apply_side_margins()
        controls_on_left = bool(getattr(self.main, "_controls_on_left", False))
        avail_h = max(200, self.day_scroll.viewport().height() - 8)
        avail_w = self._estimate_day_width(
            has_inbox=has_inbox, has_control=has_control, controls_on_left=controls_on_left
        )
        viewport_w = max(0, self.day_scroll.viewport().width() - 8)
        if has_inbox or has_control:
            if viewport_w > 0:
                avail_w = max(avail_w, viewport_w)
        elif viewport_w > avail_w:
            avail_w = viewport_w
        col_count = self._force_col_count or max(1, avail_w // (COL_W + COL_GAP))
        self._force_col_count = None
        self._last_day_pack = (col_count, avail_h)

        slots: list[tuple[tuple, Task]] = []
        for task in inbox:
            slots.append((("inbox", task.id), task))
        for task in control:
            slots.append((("control", task.id), task))
        for name in (SECTION_GORIT, SECTION_NUZHNO, SECTION_MOZHNO):
            for task in sections[name]:
                slots.append((("priority", name, task.id), task))
        for name, group in exec_sections:
            for task in group:
                slots.append((("executor", name, task.id), task))
        for tag, group in tag_sections:
            for task in group:
                slots.append((("tag", tag, task.id), task))
        sig = (
            tuple(task.id for task in inbox),
            tuple(task.id for task in control),
            tuple(task.id for task in sections[SECTION_GORIT]),
            tuple(task.id for task in sections[SECTION_NUZHNO]),
            tuple(task.id for task in sections[SECTION_MOZHNO]),
            tuple((name, tuple(task.id for task in group)) for name, group in exec_sections),
            tuple((tag, tuple(task.id for task in group)) for tag, group in tag_sections),
            col_count,
            has_inbox,
            has_control,
        )
        self._sync_blocks(slots, titles)
        self._section_ids = {
            ("inbox", "inbox"): [task.id for task in inbox],
            ("control", "control"): [task.id for task in control],
            ("priority", SECTION_GORIT): [task.id for task in sections[SECTION_GORIT]],
            ("priority", SECTION_NUZHNO): [task.id for task in sections[SECTION_NUZHNO]],
            ("priority", SECTION_MOZHNO): [task.id for task in sections[SECTION_MOZHNO]],
        }
        for name, group in exec_sections:
            self._section_ids[("executor", name)] = [task.id for task in group]
        for tag, group in tag_sections:
            self._section_ids[("tag", tag)] = [task.id for task in group]
        if sig == self._layout_sig and not self._blocks_lifted():
            self._apply_paint()
            return
        self._layout_sig = sig
        self._executor_drop = ""
        self.set_executor_drop_highlight(None)
        self.inbox_wrap.setVisible(has_inbox)
        self._place_sequence(self.inbox_layout, self._section_blocks("inbox", "", inbox), stretch=True)
        self.control_wrap.setVisible(has_control)
        self._place_sequence(
            self.control_layout, self._section_blocks("control", "", control), stretch=True
        )
        self.sec_gorit.place_blocks(self._section_blocks("priority", SECTION_GORIT, sections[SECTION_GORIT]))
        self.sec_nuzhno.place_blocks(
            self._section_blocks("priority", SECTION_NUZHNO, sections[SECTION_NUZHNO])
        )
        self.sec_mozhno.place_blocks(
            self._section_blocks("priority", SECTION_MOZHNO, sections[SECTION_MOZHNO])
        )
        exec_names = {name for name, _group in exec_sections}
        packed = pack_day_columns(list(exec_sections) + list(tag_sections), col_count=col_count)
        self._place_day(packed, exec_names, avail_h)
        self._apply_paint()

    def _on_section_drop(self, task_id: str, section: str) -> None:
        if self.main.demo_mode:
            task = next((t for t in self.main.demo_tasks if t.id == task_id), None)
            if not task:
                return
            apply_priority_section(task, section)
            self.rebuild()
            return
        task = self.main.store.get(task_id)
        if not task:
            return
        from .activity_log import append_log, format_task_snapshot, snapshot_dict

        before = format_task_snapshot(task)
        before_state = snapshot_dict(task)
        apply_priority_section(task, section)
        self.main.request_save()
        append_log(
            "moved",
            task,
            before=before,
            detail=section,
            source="app",
            before_state=before_state,
        )
        if hasattr(self.main, "_note_task_change"):
            self.main._note_task_change(task, before=before_state)
        self.main._last_paint_key = None
        self.main.reload_boards()
        self.main._sync_history_buttons()

    def handle_task_drop_position(self, task_id: str, x: float, y: float) -> None:
        """Drop: Горит/Нужно/Можно или колонка исполнителя."""
        global_pos = self.mapToGlobal(QPoint(int(x + TASK_W / 2), int(y + TASK_BLOCK_H / 2)))
        for sec in (self.sec_gorit, self.sec_nuzhno, self.sec_mozhno):
            local = sec.mapFromGlobal(global_pos)
            if sec.rect().contains(local):
                self._on_section_drop(task_id, sec.section)
                return
        exec_name = self.executor_at_global(global_pos)
        if exec_name:
            if not self.main.apply_executor_to_tasks([task_id], exec_name):
                self.main.reload_boards()
            return
        # не попали — вернуть карточку на место
        self.main.reload_boards()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._swipe_armed = True
            child = self.childAt(event.position().toPoint())
            if child is None or child is self or child is self.body:
                if hasattr(self.main, "clear_paint_mode"):
                    self.main.clear_paint_mode()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._swipe_armed
            and self._press_pos is not None
            and self.swipe_callback is not None
        ):
            delta = event.position().toPoint().x() - self._press_pos.x()
            if abs(delta) > 80:
                self.swipe_callback(-1 if delta < 0 else 1)
        self._press_pos = None
        self._swipe_armed = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        from .theme import board_bg

        painter.fillRect(self.rect(), QColor(board_bg()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_side_margins()
        if not self.isVisible() or self._day_relayouting or self._in_rebuild:
            return
        avail_h = max(200, self.day_scroll.viewport().height() - 8)
        avail_w = max(COL_W, self.day_scroll.viewport().width() - 8)
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        prev = self._last_day_pack
        if prev is not None and col_count == prev[0]:
            if avail_h != prev[1]:
                for column in self._day_column_widgets:
                    column.setMinimumHeight(avail_h)
                self._last_day_pack = (col_count, avail_h)
            return
        self._day_relayouting = True
        try:
            self.rebuild()
        finally:
            self._day_relayouting = False
