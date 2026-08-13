"""Экран «Задачи дня»: Входящие | Горит/Нужно/Можно | ДЕНЬ."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .day_tasks import (
    SECTION_GORIT,
    SECTION_MOZHNO,
    SECTION_NUZHNO,
    UNTAGGED_SECTION,
    apply_priority_section,
    day_tag_counts,
    inbox_tasks,
    pack_day_columns,
    priority_sections,
    refresh_inbox_tags,
    section_heading,
)
from .layout_metrics import content_side_margins
from .models import Task
from .tags import display_symbol
from .widgets import TASK_H, TASK_W, TagBar, TagCircle, TaskBlock

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
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)
        self.title_lab = QLabel(title)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        self.title_lab.setFont(font)
        self.title_lab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title_lab.setToolTip(f"Кисть «{title}»: клик по задачам = как drop сюда")
        self.title_lab.mousePressEvent = self._on_title_press  # type: ignore[method-assign]
        self._layout.addWidget(self.title_lab)
        self._blocks_host = QVBoxLayout()
        self._blocks_host.setSpacing(6)
        self._layout.addLayout(self._blocks_host)
        self._layout.addStretch(1)
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

    def add_block(self, block: TaskBlock) -> None:
        self._blocks_host.addWidget(block)

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
        self._day_tag_circles: dict[str, TagCircle] = {}
        self._last_day_pack: tuple[int, int] | None = None
        self._day_relayouting = False
        self._defer_inbox_hook = False

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

    def _apply_side_margins(self, controls_on_left: bool | None = None) -> None:
        """Сдвиг контента от панели кнопок (не накладывать на задачи)."""
        if controls_on_left is None:
            on_left = bool(getattr(self.main, "_controls_on_left", False))
        else:
            on_left = controls_on_left
        left, right = content_side_margins(on_left)
        self.root.setContentsMargins(left, 8, right, 8)

    def _estimate_day_width(self, *, has_inbox: bool, controls_on_left: bool) -> int:
        """Ширина зоны ДЕНЬ без ожидания пересчёта layout после hide inbox."""
        left, right = content_side_margins(controls_on_left)
        total = max(self.width(), self.body.width(), 400)
        used = left + right
        if has_inbox:
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

    def _clear_blocks(self) -> None:
        for block in self._blocks:
            block.setParent(None)
            block.deleteLater()
        self._blocks.clear()
        # висящие после reparent при drag
        for child in list(self.findChildren(TaskBlock)):
            child.setParent(None)
            child.deleteLater()

    def _make_block(self, task: Task) -> TaskBlock:
        block = TaskBlock(task, self)
        block.dropped_on_tag.connect(lambda tid, key: self.main.apply_action_to_task(tid, key))
        block.tag_dropped.connect(lambda tid, key: self.main.apply_action_to_task(tid, key))
        block.double_clicked.connect(self.main.edit_task)
        block.project_clicked.connect(self.main.on_project_filter)
        block.clicked.connect(self.main.on_task_clicked)
        self._blocks.append(block)
        return block

    def rebuild(self, *, defer_inbox_hook: bool = False) -> None:
        today = date.today()
        tasks = self.main.visible_tasks()
        if not self.main.demo_mode:
            if refresh_inbox_tags(self.main.store.tasks, today):
                self.main.store.save()
                tasks = self.main.visible_tasks()

        inbox = inbox_tasks(tasks)
        has_inbox = bool(inbox)
        # панель слева только при непустых входящих на этом экране
        want_left = has_inbox and (
            self.main._is_day_screen() if hasattr(self.main, "_is_day_screen") else True
        )
        self._apply_side_margins(want_left)
        self._clear_blocks()
        self._day_tag_circles.clear()

        # Входящие
        while self.inbox_layout.count():
            item = self.inbox_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.inbox_wrap.setVisible(has_inbox)
        for task in inbox:
            self.inbox_layout.addWidget(self._make_block(task))
        self.inbox_layout.addStretch(1)

        # Приоритет
        for sec in (self.sec_gorit, self.sec_nuzhno, self.sec_mozhno):
            sec.clear_tasks()
        sections = priority_sections(tasks)
        for task in sections[SECTION_GORIT]:
            self.sec_gorit.add_block(self._make_block(task))
        for task in sections[SECTION_NUZHNO]:
            self.sec_nuzhno.add_block(self._make_block(task))
        for task in sections[SECTION_MOZHNO]:
            self.sec_mozhno.add_block(self._make_block(task))

        for sec, key in (
            (self.sec_gorit, SECTION_GORIT),
            (self.sec_nuzhno, SECTION_NUZHNO),
            (self.sec_mozhno, SECTION_MOZHNO),
        ):
            n = len(sections[key])
            sec.setMinimumHeight(36 + max(1, n) * (TASK_H + 6) + 12)

        # ДЕНЬ
        while self.day_layout.count():
            item = self.day_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        tag_sections = day_tag_counts(tasks)
        avail_h = max(200, self.day_scroll.viewport().height() - 8)
        avail_w = self._estimate_day_width(has_inbox=has_inbox, controls_on_left=want_left)
        viewport_w = max(0, self.day_scroll.viewport().width() - 8)
        if has_inbox:
            # при видимых входящих viewport обычно актуален
            if viewport_w > 0:
                avail_w = max(avail_w, viewport_w)
        elif viewport_w > avail_w:
            # layout уже успел расширить ДЕНЬ после hide
            avail_w = viewport_w
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        self._last_day_pack = (col_count, avail_h)
        columns = pack_day_columns(tag_sections, col_count=col_count)
        paint_key = None
        if getattr(self.main, "paint_mode", None) and self.main.paint_mode[0] == "tag":
            paint_key = self.main.paint_mode[1]
        for col_sections in columns:
            col_w = QWidget()
            col_w.setFixedWidth(COL_W)
            col_w.setMinimumHeight(avail_h)
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(0)
            for tag, tag_tasks in col_sections:
                sec = QWidget()
                sec_l = QVBoxLayout(sec)
                sec_l.setContentsMargins(0, 0, 0, 0)
                sec_l.setSpacing(6)
                head = QHBoxLayout()
                if tag == UNTAGGED_SECTION:
                    lab = QLabel(section_heading(tag))
                    lab.setStyleSheet("color:#444; font-weight:600;")
                    head.addWidget(lab, 1)
                else:
                    symbol = display_symbol(tag) or tag[:2]
                    circle = TagCircle(
                        tag, symbol, sec, draggable=True, reorderable=False
                    )
                    circle.clicked.connect(self.main.on_tag_pick)
                    self._day_tag_circles[tag] = circle
                    if paint_key is not None:
                        circle.set_highlighted(tag == paint_key)
                    head.addWidget(circle)
                    lab = QLabel(section_heading(tag))
                    lab.setStyleSheet("color:#444; font-weight:600;")
                    head.addWidget(lab, 1)
                sec_l.addLayout(head)
                for task in tag_tasks:
                    sec_l.addWidget(self._make_block(task))
                col_l.addWidget(sec, 0, Qt.AlignmentFlag.AlignTop)
                col_l.addStretch(1)
            self.day_layout.addWidget(col_w, 0, Qt.AlignmentFlag.AlignTop)
        self.day_layout.addStretch(1)

        self.tag_bar.rebuild_circles()
        self.tag_bar.set_active_filter(self.main.filter_tag)
        if paint_key is not None:
            self.tag_bar.set_highlight(paint_key)

        pm = getattr(self.main, "paint_mode", None)
        if pm and pm[0] == "priority":
            self.set_priority_highlight(pm[1])
        else:
            self.set_priority_highlight(None)

        if (
            not defer_inbox_hook
            and not self._defer_inbox_hook
            and hasattr(self.main, "on_day_inbox_changed")
        ):
            self.main.on_day_inbox_changed(has_inbox)

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
        self.main.store.save()
        append_log(
            "moved",
            task,
            before=before,
            detail=section,
            source="app",
            before_state=before_state,
        )
        self.main._last_paint_key = None
        self._clear_blocks()
        self.main.reload_boards()
        self.main._sync_history_buttons()

    def handle_task_drop_position(self, task_id: str, x: float, y: float) -> None:
        """Если дропнули над секцией приоритета — применить секцию."""
        global_pos = self.mapToGlobal(QPoint(int(x + TASK_W / 2), int(y + TASK_H / 2)))
        for sec in (self.sec_gorit, self.sec_nuzhno, self.sec_mozhno):
            local = sec.mapFromGlobal(global_pos)
            if sec.rect().contains(local):
                self._on_section_drop(task_id, sec.section)
                return
        # не попали — убрать «призрак» и пересобрать
        self._clear_blocks()
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
        painter.fillRect(self.rect(), QColor("#FAFAF7"))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_side_margins()
        if not self.isVisible() or self._day_relayouting:
            return
        avail_h = max(200, self.day_scroll.viewport().height() - 8)
        avail_w = max(COL_W, self.day_scroll.viewport().width() - 8)
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        pack = (col_count, avail_h)
        if pack != self._last_day_pack:
            self._day_relayouting = True
            try:
                self.rebuild()
            finally:
                self._day_relayouting = False
