"""Главное окно планировщика: экраны, свайп, fullscreen."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import uuid

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .annotations import AnnotationStore, LabelAnn, RectAnn
from .activity_log import (
    append_log,
    apply_state_to_task,
    find_redo_target,
    find_undo_target,
    find_redo_targets,
    find_undo_targets,
    format_task_snapshot,
    snapshot_dict,
    task_from_state,
)
from .create_presets import PRESET_DONE, PRESET_INBOX, apply_preset_to_new_task_data
from .day_hide import hide_task as hide_task_on_day
from .day_tasks import (
    apply_inbox_to_task,
    apply_priority_section,
    refresh_inbox_tags,
)
from .day_tasks_board import DayTasksCanvas
from .executors_store import DEFAULT_EXECUTOR, ExecutorsStore
from .layout_metrics import content_left, content_right
from .lists_board import ListsCanvas
from .lists_store import ListsStore
from .logs_board import LogsCanvas
from .models import Task
from .notion_sync import NotionSyncManager
from .period_roll import spawn_periodic_copies
from .sorting import SCREENS, TRIAGE_COLUMNS, apply_task_to_triage_column
from .tags import (
    ACTUAL_TAG,
    ANSWERS_TAG,
    BACKLOG_TAG,
    BY_KEY,
    CANCEL_TAG,
    CONTROL_TAG,
    DONE_CHECK_ACTION,
    DONE_TAG,
    IMPORTANT_TAG,
    INBOX_TAG,
    SOCIAL_TAG,
    SPECIAL_ACTION_KEYS,
    TODAY_ACTION,
    TOMORROW_ACTION,
    URGENT_TAG,
    WEEK_ACTION,
    canonicalize_tag_key,
    clear_actual_tag,
)
from .widgets import (
    CIRCLE,
    TASK_H,
    TASK_W,
    CircleButton,
    EditTaskDialog,
    NewTaskDialog,
    TagBar,
    TagCircle,
    TaskBlock,
)
from .xlsx_store import TaskStore


def apply_status_tag(task, tag_key: str) -> None:
    """Назначить выполнена / отменена / беклог / контроль с побочными эффектами."""
    from .sorting import apply_backlog_deferral
    from .tags import BACKLOG_TAG, CONTROL_TAG, apply_control_tag

    key = canonicalize_tag_key(tag_key)
    if key == DONE_TAG:
        task.remove_tag(CANCEL_TAG)
        task.add_tag(DONE_TAG)
        if task.completed_at is None:
            task.completed_at = date.today()
        return
    if key == CANCEL_TAG:
        task.remove_tag(DONE_TAG)
        task.add_tag(CANCEL_TAG)
        return
    if key == BACKLOG_TAG:
        task.add_tag(BACKLOG_TAG)
        apply_backlog_deferral(task)
        return
    if key == CONTROL_TAG:
        apply_control_tag(task)
        return
    task.add_tag(key)


def move_task_to_today(task, today: date | None = None) -> None:
    """Как drop в колонку ДЕЛАЕМ."""
    from .sorting import apply_task_to_triage_column

    apply_task_to_triage_column(task, "ДЕЛАЕМ", today)


def move_task_to_tomorrow(task, today: date | None = None) -> None:
    """Как drop в колонку ЗАВТРА."""
    from .sorting import apply_task_to_triage_column

    apply_task_to_triage_column(task, "ЗАВТРА", today)


def move_task_by_week(task, today: date | None = None) -> None:
    """Как drop в колонку НЕДЕЛЯ."""
    from .sorting import apply_task_to_triage_column

    apply_task_to_triage_column(task, "НЕДЕЛЯ", today)


def apply_answers_tag(task, today: date | None = None) -> None:
    from .tags import CORRESPONDENCE_TAG, assign_start_at

    today = today or date.today()
    task.add_tag(CORRESPONDENCE_TAG)
    assign_start_at(task, today + timedelta(days=7))


def _demo_tasks(today: date | None = None) -> list[Task]:
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    return [
        Task(
            id="demo-1",
            title="Накормить кота философией",
            project="Котоплан",
            tags=[IMPORTANT_TAG, URGENT_TAG, ACTUAL_TAG],
            start_at=today,
            due_at=today,
        ),
        Task(
            id="demo-2",
            title="Найти смысл кнопки «ещё»",
            project="UX абсурд",
            tags=[URGENT_TAG, IMPORTANT_TAG, ACTUAL_TAG, "геймдизайн"],
            start_at=today - timedelta(days=2),
            due_at=today,
        ),
        Task(
            id="demo-3",
            title="Погладить кактус осторожно",
            project="Флора",
            tags=[IMPORTANT_TAG, ACTUAL_TAG, "личная"],
            start_at=tomorrow,
        ),
        Task(
            id="demo-4",
            title="Пересчитать облака",
            project="Метео",
            tags=["быстрая", INBOX_TAG],
            start_at=today + timedelta(days=3),
        ),
        Task(
            id="demo-5",
            title="Написать письмо будущему себе",
            project="Тайм-капс",
            tags=["обдумываемая", ACTUAL_TAG],
            start_at=today,
        ),
        Task(
            id="demo-6",
            title="Изобрести вечный дедлайн",
            project="R&D шуток",
            tags=[BACKLOG_TAG, "сложная"],
        ),
        Task(
            id="demo-7",
            title="Выгулять дракона по расписанию",
            project="Мифология",
            tags=["уличная", INBOX_TAG],
            start_at=today,
        ),
        Task(
            id="demo-8",
            title="Починить вчера (аккуратно)",
            project="Ретро",
            tags=["сложная", ACTUAL_TAG],
            start_at=today - timedelta(days=1),
        ),
    ]


class LabelBlock(QWidget):
    moved = pyqtSignal(str, float, float)
    selected = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, item: LabelAnn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._drag_start: QPoint | None = None
        self._dragging = False
        self._selected = False
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._relayout()

    def _relayout(self) -> None:
        font = QFont("Segoe UI", 11)
        metrics = QFontMetrics(font)
        w = max(40, metrics.horizontalAdvance(self.item.text) + 16)
        h = max(24, metrics.height() + 8)
        self.setFixedSize(w, h)
        self.update()

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bd = QColor("#1976D2") if self._selected else QColor("#888888")
        p.setPen(QPen(bd, 2 if self._selected else 1))
        p.setBrush(QColor("#FFFDE7"))
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 4, 4)
        p.setPen(QColor("#222222"))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.item.text)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.selected.emit(self.item.id)
            self.raise_()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 6:
            return
        self._dragging = True
        parent = self.parentWidget()
        if parent is None:
            return
        pos = self.mapToParent(event.position().toPoint()) - self._drag_start
        self.move(max(0, pos.x()), max(0, pos.y()))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self.moved.emit(self.item.id, float(self.x()), float(self.y()))
        self._drag_start = None
        self._dragging = False


class RectBlock(QWidget):
    moved = pyqtSignal(str, float, float)
    selected = pyqtSignal(str)

    def __init__(self, item: RectAnn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._drag_start: QPoint | None = None
        self._dragging = False
        self._selected = False
        self.setFixedSize(max(40, int(item.w)), max(30, int(item.h)))
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bd = QColor("#D32F2F") if self._selected else QColor("#666666")
        p.setPen(QPen(bd, 2))
        p.setBrush(QColor(100, 100, 100, 30))
        p.drawRect(1, 1, self.width() - 2, self.height() - 2)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.selected.emit(self.item.id)
            self.raise_()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 6:
            return
        self._dragging = True
        parent = self.parentWidget()
        if parent is None:
            return
        pos = self.mapToParent(event.position().toPoint()) - self._drag_start
        self.move(max(0, pos.x()), max(0, pos.y()))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self.moved.emit(self.item.id, float(self.x()), float(self.y()))
        self._drag_start = None
        self._dragging = False


class ColumnScroll(QScrollArea):
    """Колонка фиксированной ширины задачи со скроллом колесом."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(TASK_W + 12)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidgetResizable(True)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.setWidget(self._inner)

    def clear_tasks(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def add_block(self, block: TaskBlock) -> None:
        # stretch is last
        self._layout.insertWidget(self._layout.count() - 1, block)


class BoardCanvas(QWidget):
    """Холст одного экрана с колонками задач и панелью тегов."""

    def __init__(
        self,
        store: TaskStore,
        screen_id: str,
        main: "MainWindow",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.screen_id = screen_id
        self.main = main
        self.blocks: dict[str, TaskBlock] = {}
        self.label_blocks: dict[str, LabelBlock] = {}
        self.rect_blocks: dict[str, RectBlock] = {}
        self._column_scrolls: list[ColumnScroll] = []
        self.setMinimumSize(900, 600)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self.tag_bar = TagBar(self)
        self.tag_bar.tag_clicked.connect(self.main.on_tag_pick)
        self.tag_bar.order_changed.connect(self.main.on_tag_order_changed)
        self.setProperty("tag_bar", self.tag_bar)

        self._press_pos: QPoint | None = None
        self._swipe_armed = False
        self.swipe_callback = None
        self._column_titles: list[tuple[str, int, bool]] = []
        self._rect_drag_origin: QPoint | None = None
        self._rect_rubber: QRect | None = None
        # (title, x_left, x_right) for triage drop hit-test
        self._column_bounds: list[tuple[str, int, int]] = []
        self._gorit_task_ids: set[str] = set()
        self._column_task_ids: dict[str, list[str]] = {}

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.tag_bar.setGeometry(
            0, self.height() - self.tag_bar.height(), self.width(), self.tag_bar.height()
        )
        self.tag_bar.raise_()
        if self.screen_id == "triage" and not self.main.filter_tag and self.main.filter_project is None:
            self.rebuild()

    def _visible_tasks(self) -> list[Task]:
        return self.main.visible_tasks()

    def rebuild(self) -> None:
        for block in list(self.blocks.values()):
            block.setParent(None)
            block.deleteLater()
        self.blocks.clear()
        for col in self._column_scrolls:
            col.setParent(None)
            col.deleteLater()
        self._column_scrolls.clear()
        for w in list(self.label_blocks.values()) + list(self.rect_blocks.values()):
            w.setParent(None)
            w.deleteLater()
        self.label_blocks.clear()
        self.rect_blocks.clear()

        filter_tag = self.main.filter_tag
        filter_project = self.main.filter_project
        self.tag_bar.set_active_filter(filter_tag)
        tasks_all = self._visible_tasks()

        if filter_tag == DONE_TAG:
            tasks_pool = [t for t in tasks_all if t.is_done()]
            columns = [("Выполнена", tasks_pool)]
            center_titles = True
            use_scroll = False
        elif filter_tag == CANCEL_TAG:
            tasks_pool = [t for t in tasks_all if t.is_cancelled()]
            columns = [("Отменена", tasks_pool)]
            center_titles = True
            use_scroll = False
        elif filter_tag:
            tasks_pool = [
                t
                for t in tasks_all
                if t.has_tag(filter_tag) and not t.is_hidden_from_boards()
            ]
            columns = [(f"Тег: {filter_tag}", tasks_pool)]
            center_titles = False
            use_scroll = False
        elif filter_project is not None:
            from .projects import resolve_project_name, same_project

            needle = filter_project.strip()
            display = resolve_project_name(needle, tasks_all) or needle or "без проекта"
            tasks_pool = [t for t in tasks_all if same_project(t.project, needle)]
            tasks_pool.sort(
                key=lambda t: (
                    0 if not t.is_hidden_from_boards() else 1,
                    0 if t.is_done() else 1 if t.is_cancelled() else 0,
                    t.title.casefold(),
                )
            )
            columns = [(display, tasks_pool)]
            center_titles = True
            use_scroll = False
        elif self.screen_id == "backlog":
            from .sorting import screen_backlog

            columns = screen_backlog(tasks_all)
            center_titles = False
            use_scroll = True
        else:
            layout_fn = next(fn for sid, _title, fn in SCREENS if sid == self.screen_id)
            columns = layout_fn(tasks_all)
            center_titles = self.screen_id == "projects"
            use_scroll = self.screen_id == "triage"

        self._column_task_ids = {
            title: [t.id for t in lst] for title, lst in columns
        }
        col_gap = 20 if self.screen_id == "triage" else 24
        top = 48
        usable_h = max(100, self.height() - self.tag_bar.height() - top - 16)
        self._column_bounds = []
        self._gorit_task_ids = set()
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m = content_left(on_left, base=16)
        right_m = content_right(on_left, base=16)
        content_w = max(TASK_W, self.width() - left_m - right_m)

        if use_scroll and self.screen_id == "triage" and columns:
            # Справа: ДЕЛАЕМ…ТУМАН; слева: свободная зона ГОРИТ
            gorit_title, gorit_tasks = columns[0]
            other_cols = columns[1:]
            n_other = len(other_cols)
            other_w = n_other * TASK_W + max(0, n_other - 1) * col_gap
            other_start = max(
                left_m + TASK_W + col_gap,
                left_m + content_w - other_w,
            )

            title_xs: list[int] = []
            # ГОРИТ zone: [left_m .. other_start)
            title_xs.append(left_m)
            self._column_bounds.append((gorit_title, left_m, other_start))
            self._gorit_task_ids = {t.id for t in gorit_tasks}
            stack_y = top
            stack_x = left_m
            max_x = max(left_m, other_start - TASK_W)
            for task in gorit_tasks:
                block = self._make_block(task)
                if (
                    task.pos_x is not None
                    and task.pos_y is not None
                    and not self.main.demo_mode
                    and left_m <= int(task.pos_x) < other_start
                ):
                    bx = min(max(left_m, int(task.pos_x)), max_x)
                    by = int(task.pos_y)
                else:
                    bx, by = stack_x, stack_y
                    stack_y += TASK_H + 8
                    if stack_y + TASK_H > top + usable_h:
                        stack_y = top
                        stack_x += TASK_W + 8
                        if stack_x > max_x:
                            stack_x = left_m
                        bx = stack_x
                block.move(bx, by)
                block.show()
                self.blocks[task.id] = block

            for col_idx, (title, tasks) in enumerate(other_cols):
                x = other_start + col_idx * (TASK_W + col_gap)
                title_xs.append(x)
                x_right = x + TASK_W + (col_gap if col_idx < n_other - 1 else right_m)
                if col_idx == n_other - 1:
                    x_right = self.width() - right_m
                self._column_bounds.append((title, x, x_right))
                scroll = ColumnScroll(self)
                scroll.setGeometry(x, top, TASK_W + 12, usable_h)
                for task in tasks:
                    block = self._make_block(task)
                    scroll.add_block(block)
                    self.blocks[task.id] = block
                scroll.show()
                self._column_scrolls.append(scroll)

            self._column_titles = [
                (c[0], title_xs[i], False) for i, c in enumerate(columns)
            ]
        elif use_scroll:
            n = len(columns)
            total_w = n * TASK_W + max(0, n - 1) * col_gap
            start_x = max(left_m, left_m + content_w - total_w)
            title_xs = []
            for col_idx, (title, tasks) in enumerate(columns):
                x = start_x + col_idx * (TASK_W + col_gap)
                title_xs.append(x)
                scroll = ColumnScroll(self)
                scroll.setGeometry(x, top, TASK_W + 12, usable_h)
                for task in tasks:
                    block = self._make_block(task)
                    scroll.add_block(block)
                    self.blocks[task.id] = block
                scroll.show()
                self._column_scrolls.append(scroll)
            self._column_titles = [
                (c[0], title_xs[i], center_titles) for i, c in enumerate(columns)
            ]
        else:
            left = left_m
            max_task_x = max(left_m, self.width() - right_m - TASK_W)
            for col_idx, (title, tasks) in enumerate(columns):
                x = left + col_idx * (TASK_W + col_gap)
                y = top
                for task in tasks:
                    block = self._make_block(task)
                    if (
                        task.pos_x is not None
                        and task.pos_y is not None
                        and self.screen_id == "urgency"
                        and not filter_tag
                        and filter_project is None
                        and not self.main.demo_mode
                    ):
                        bx = min(max(left_m, int(task.pos_x)), max_task_x)
                        by = int(task.pos_y)
                    else:
                        bx = min(x, max_task_x)
                        by = y
                        y += TASK_H + 8
                        if y + TASK_H > top + usable_h:
                            y = top
                            x += TASK_W + col_gap
                            bx = min(x, max_task_x)
                    block.move(bx, by)
                    block.show()
                    self.blocks[task.id] = block
            self._column_titles = [
                (c[0], left + i * (TASK_W + col_gap), center_titles)
                for i, c in enumerate(columns)
            ]

        if not self.main.demo_mode:
            self._rebuild_annotations()
        self.tag_bar.raise_()
        self.update()

    def column_at(self, x: int) -> str | None:
        for title, left, right in self._column_bounds:
            if left <= x < right:
                return title
        return None

    def handle_task_drop_position(self, task_id: str, x: float, y: float) -> None:
        """После drag на triage: колонка → мутация полей; в ГОРИТ ещё и pos."""
        if self.screen_id != "triage":
            return
        if self.main.filter_tag or self.main.filter_project is not None:
            return
        col = self.column_at(int(x + TASK_W / 2))
        if not col or col not in TRIAGE_COLUMNS:
            self.main.reload_boards()
            return
        if self.main.demo_mode:
            task = next((t for t in self.main.demo_tasks if t.id == task_id), None)
            if not task:
                return
            apply_task_to_triage_column(task, col)
            if col == "ГОРИТ":
                task.pos_x = x
                task.pos_y = y
            self.main.reload_boards()
            return
        task = self.store.get(task_id)
        if not task:
            return
        before = format_task_snapshot(task)
        before_state = snapshot_dict(task)
        apply_task_to_triage_column(task, col)
        if col == "ГОРИТ":
            task.pos_x = x
            task.pos_y = y
        else:
            task.pos_x = None
            task.pos_y = None
        self.store.save()
        append_log(
            "moved",
            task,
            before=before,
            detail=col,
            source="app",
            before_state=before_state,
        )
        self.main._last_paint_key = None
        self.main.reload_boards()
        self.main._sync_history_buttons()

    def _make_block(self, task: Task) -> TaskBlock:
        block = TaskBlock(task, self)
        block.moved.connect(self._on_moved)
        block.dropped_on_tag.connect(self._on_tag_drop)
        block.tag_dropped.connect(self._on_tag_drop)
        block.double_clicked.connect(self.main.edit_task)
        block.project_clicked.connect(self.main.on_project_filter)
        block.clicked.connect(self.main.on_task_clicked)
        return block

    def _rebuild_annotations(self) -> None:
        labels, rects = self.main.annotations.for_screen(self.screen_id)
        for item in labels:
            w = LabelBlock(item, self)
            w.move(int(item.x), int(item.y))
            w.moved.connect(self._on_label_moved)
            w.selected.connect(self.main.on_annotation_selected)
            w.show()
            self.label_blocks[item.id] = w
        for item in rects:
            w = RectBlock(item, self)
            w.move(int(item.x), int(item.y))
            w.moved.connect(self._on_rect_moved)
            w.selected.connect(self.main.on_annotation_selected)
            w.show()
            self.rect_blocks[item.id] = w

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FAFAF7"))
        painter.setPen(QColor("#666666"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for title, x, centered in getattr(self, "_column_titles", []):
            if centered:
                text_w = metrics.horizontalAdvance(title)
                tx = x + (TASK_W - text_w) // 2
                painter.drawText(max(x, tx), 28, title)
            else:
                painter.drawText(x, 28, title)
        if self._rect_rubber is not None:
            painter.setPen(QPen(QColor("#D32F2F"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(211, 47, 47, 40))
            painter.drawRect(self._rect_rubber)

    def _on_moved(self, task_id: str, x: float, y: float) -> None:
        if self.main.demo_mode:
            if self.screen_id == "triage":
                self.handle_task_drop_position(task_id, x, y)
            return
        if self.screen_id == "triage":
            self.handle_task_drop_position(task_id, x, y)
            return
        task = self.store.get(task_id)
        if not task:
            return
        if y + TASK_H > self.height() - self.tag_bar.height():
            return
        task.pos_x = x
        task.pos_y = y
        self.store.save()

    def _on_label_moved(self, ann_id: str, x: float, y: float) -> None:
        for item in self.main.annotations.labels:
            if item.id == ann_id:
                item.x = x
                item.y = y
                self.main.annotations.update_label(item)
                break

    def _on_rect_moved(self, ann_id: str, x: float, y: float) -> None:
        for item in self.main.annotations.rects:
            if item.id == ann_id:
                item.x = x
                item.y = y
                self.main.annotations.update_rect(item)
                break

    def _on_tag_drop(self, task_id: str, tag_key: str) -> None:
        self.main.apply_action_to_task(task_id, tag_key)

    def _column_title_at(self, x: int) -> str | None:
        for title, left, right in self._column_bounds:
            if left <= x < right:
                return title
        for title, tx, _centered in self._column_titles:
            if tx <= x < tx + TASK_W + 24:
                return title
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if pos.y() <= 40 and getattr(self.main, "paint_mode", None):
            title = self._column_title_at(pos.x())
            if title:
                ids = self._column_task_ids.get(title) or []
                if self.main._apply_current_brush_to_ids(ids):
                    return
        child = self.childAt(pos)

        if self.main.place_label_mode:
            self.main.begin_label_at(self.screen_id, pos)
            return
        if self.main.draw_rect_mode:
            self._rect_drag_origin = pos
            self._rect_rubber = QRect(pos, pos)
            self.update()
            return

        if child is None:
            self._press_pos = pos
            self._swipe_armed = True
            self.main.on_annotation_selected("")
            if self.main.paint_mode:
                self.main.clear_paint_mode()
        elif isinstance(child, TagBar):
            self._press_pos = None
            self._swipe_armed = False
        else:
            self._press_pos = None
            self._swipe_armed = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._rect_drag_origin is not None and self.main.draw_rect_mode:
            cur = event.position().toPoint()
            self._rect_rubber = QRect(self._rect_drag_origin, cur).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._rect_drag_origin is not None and self._rect_rubber is not None:
            r = self._rect_rubber
            self._rect_drag_origin = None
            self._rect_rubber = None
            self.update()
            if r.width() >= 20 and r.height() >= 20:
                self.main.finish_rect(
                    self.screen_id, float(r.x()), float(r.y()), float(r.width()), float(r.height())
                )
            else:
                self.main.cancel_draw_modes()
            return
        if self._press_pos is None:
            return
        delta = event.position().toPoint() - self._press_pos
        self._press_pos = None
        if abs(delta.x()) > 80 and abs(delta.x()) > abs(delta.y()):
            if self.swipe_callback and self._swipe_armed:
                self.swipe_callback(-1 if delta.x() < 0 else 1)


class MainWindow(QMainWindow):
    def __init__(self, store: TaskStore, annotations: AnnotationStore | None = None) -> None:
        super().__init__()
        self.store = store
        self.lists_store = ListsStore(store.path)
        self.executors_store = ExecutorsStore(store.path)
        self.executors_store.load()
        self.annotations = annotations or AnnotationStore.load()
        self.filter_tag: str | None = None
        self.filter_project: str | None = None
        self.selected_task_id: str | None = None
        self.selected_ann_id: str | None = None
        self.demo_mode = False
        self.demo_tasks: list[Task] = []
        self.place_label_mode = False
        self.draw_rect_mode = False
        self._label_editor: QLineEdit | None = None
        # Режим «кисти»: ("tag", key) | ("action", key) | None
        self.paint_mode: tuple[str, str] | None = None
        self._last_paint_key: tuple[str, str] | None = None  # (task_id, action) для повторного клика
        self._controls_on_left = False
        self.setWindowTitle("TanionPlaning")
        self.resize(1280, 800)
        self._fullscreen = False

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chrome = QWidget()
        chrome_layout = QHBoxLayout(self.chrome)
        self.title_label = QLabel("TanionPlaning")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600; padding: 8px;")
        chrome_layout.addWidget(self.title_label)
        chrome_layout.addStretch(1)

        self.screen_label = QLabel("")
        chrome_layout.addWidget(self.screen_label)

        self.filter_label = QLabel("")
        self.filter_label.setStyleSheet("color: #886600; padding: 4px;")
        chrome_layout.addWidget(self.filter_label)

        self.btn_clear_filter = QPushButton("Сбросить фильтр")
        self.btn_clear_filter.clicked.connect(self.clear_filters)
        self.btn_clear_filter.hide()
        chrome_layout.addWidget(self.btn_clear_filter)

        layout.addWidget(self.chrome)

        self.stack = QStackedWidget()
        self.boards: list[BoardCanvas] = []
        # Логи → Бэклог → Списки → Задачи дня → triage…
        self.logs_board = LogsCanvas(self)
        self.logs_board.swipe_callback = self._on_swipe
        self.stack.addWidget(self.logs_board)
        self.backlog_board = BoardCanvas(store, "backlog", self)
        self.backlog_board.swipe_callback = self._on_swipe
        self.stack.addWidget(self.backlog_board)
        self.lists_board = ListsCanvas(self.lists_store, self, self.executors_store)
        self.lists_board.swipe_callback = self._on_swipe
        self.stack.addWidget(self.lists_board)
        self.day_board = DayTasksCanvas(self)
        self.day_board.swipe_callback = self._on_swipe
        self.stack.addWidget(self.day_board)
        self.screen_titles: list[tuple[str, str]] = [
            ("logs", "Логи"),
            ("backlog", "Бэклог"),
            ("lists", "Списки"),
            ("day_tasks", "Задачи дня"),
        ]
        for screen_id, title, _fn in SCREENS:
            board = BoardCanvas(store, screen_id, self)
            board.swipe_callback = self._on_swipe
            self.boards.append(board)
            self.stack.addWidget(board)
            self.screen_titles.append((screen_id, title))
        layout.addWidget(self.stack, 1)

        self.controls = QWidget(self)
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)
        self.btn_new_global = CircleButton("+")
        self.btn_new_global.setToolTip("Новая задача")
        self.btn_new_global.clicked.connect(self.new_task)
        controls_layout.addWidget(self.btn_new_global)
        self.btn_fullscreen = CircleButton("⛶")
        self.btn_fullscreen.setToolTip("Полный экран")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        controls_layout.addWidget(self.btn_fullscreen)
        self.btn_restart = CircleButton("↻")
        self.btn_restart.setToolTip("Перезапустить приложение в полном экране (подтянуть обновления)")
        self.btn_restart.clicked.connect(self.restart_app_fullscreen)
        controls_layout.addWidget(self.btn_restart)
        self.btn_undo = CircleButton("↶")
        self.btn_undo.setToolTip("Отменить последнее действие")
        self.btn_undo.clicked.connect(self.history_undo)
        controls_layout.addWidget(self.btn_undo)
        self.btn_redo = CircleButton("↷")
        self.btn_redo.setToolTip("Повторить отменённое действие")
        self.btn_redo.clicked.connect(self.history_redo)
        controls_layout.addWidget(self.btn_redo)
        self.btn_done_dup = TagCircle(
            DONE_TAG, "✅", self.controls, draggable=True, reorderable=False
        )
        self.btn_done_dup.setToolTip("Выполнена")
        self.btn_done_dup.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_done_dup)

        self.btn_cancel_dup = TagCircle(
            CANCEL_TAG, "🗑", self.controls, draggable=True, reorderable=False
        )
        self.btn_cancel_dup.setToolTip("Отменена")
        self.btn_cancel_dup.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_cancel_dup)

        self.btn_today = TagCircle(
            TODAY_ACTION, "Сег", self.controls, draggable=True, reorderable=False
        )
        self.btn_today.setToolTip("Сегодня: спрятать с экрана «Задачи дня» на 4 часа")
        self.btn_today.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_today)

        self.btn_tomorrow = TagCircle(
            TOMORROW_ACTION, "З", self.controls, draggable=True, reorderable=False
        )
        self.btn_tomorrow.setToolTip("Завтра: кисть; по разделу — все задачи раздела")
        self.btn_tomorrow.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_tomorrow)

        self.btn_week = TagCircle(
            WEEK_ACTION, "Нед", self.controls, draggable=True, reorderable=False
        )
        self.btn_week.setToolTip("Неделя: кисть; по разделу — все задачи раздела")
        self.btn_week.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_week)

        backlog_symbol = BY_KEY[BACKLOG_TAG].symbol
        self.btn_backlog = TagCircle(
            BACKLOG_TAG, backlog_symbol, self.controls, draggable=True, reorderable=False
        )
        self.btn_backlog.setToolTip("Бэклог: кисть; по разделу — все задачи раздела")
        self.btn_backlog.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_backlog)

        inbox_symbol = BY_KEY[INBOX_TAG].symbol
        self.btn_inbox = TagCircle(
            INBOX_TAG, inbox_symbol, self.controls, draggable=True, reorderable=False
        )
        self.btn_inbox.setToolTip("Во входящие: кисть; по разделу — все задачи раздела")
        self.btn_inbox.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_inbox)

        self.btn_done_check = TagCircle(
            DONE_CHECK_ACTION, "✅👁", self.controls, draggable=True, reorderable=False
        )
        self.btn_done_check.setToolTip("Сделано и проверить: выполнена + копия «Проверить …» на завтра")
        self.btn_done_check.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_done_check)

        answers_symbol = BY_KEY[ANSWERS_TAG].symbol
        self.btn_answers = TagCircle(
            ANSWERS_TAG, answers_symbol, self.controls, draggable=True, reorderable=False
        )
        self.btn_answers.setToolTip("Переписка: старт через неделю")
        self.btn_answers.clicked.connect(self._on_action_tool_clicked)
        controls_layout.addWidget(self.btn_answers)

        self.btn_label = CircleButton("Aa")
        self.btn_label.setToolTip("Создать надпись: следующий клик на экране")
        self.btn_label.clicked.connect(self._toggle_place_label)
        controls_layout.addWidget(self.btn_label)

        self.btn_rect = CircleButton("▢")
        self.btn_rect.setToolTip("Очертить область: протяните прямоугольник")
        self.btn_rect.clicked.connect(self._toggle_draw_rect)
        controls_layout.addWidget(self.btn_rect)

        self._action_circles = (
            self.btn_done_dup,
            self.btn_cancel_dup,
            self.btn_today,
            self.btn_tomorrow,
            self.btn_week,
            self.btn_backlog,
            self.btn_inbox,
            self.btn_done_check,
            self.btn_answers,
        )
        self.controls.show()

        self.btn_left = CircleButton("◀")
        self.btn_left.setToolTip("Предыдущий экран")
        self.btn_left.clicked.connect(lambda: self._on_swipe(1))
        self.btn_left.setParent(self)
        self.btn_left.show()
        self.btn_right = CircleButton("▶")
        self.btn_right.setToolTip("Следующий экран")
        self.btn_right.clicked.connect(lambda: self._on_swipe(-1))
        self.btn_right.setParent(self)
        self.btn_right.show()

        self.btn_demo = QPushButton("ДЕМО", self)
        self.btn_demo.setToolTip("Демо-режим со смешными задачами")
        self.btn_demo.setFixedSize(72, 36)
        self.btn_demo.clicked.connect(self.toggle_demo)
        self.btn_demo.show()

        self.stack.currentChanged.connect(self._on_screen_changed)
        # Главный экран — Задачи дня
        if not self.demo_mode:
            refresh_inbox_tags(self.store.tasks)
            self.store.save()
        day_index = 3
        self.stack.setCurrentIndex(day_index)
        self._update_screen_label(day_index)
        self.reload_boards()
        self._place_floating_controls()

        self.notion_sync = NotionSyncManager(
            self.store,
            on_applied=self._on_notion_applied,
            on_conflicts=self._on_notion_conflicts,
            parent_timer_host=self,
        )
        QTimer.singleShot(1500, self.notion_sync.sync_now)
        self.lists_store.on_change = self._note_lists_change
        self._periodic_timer = QTimer(self)
        self._periodic_timer.setInterval(30 * 60 * 1000)
        self._periodic_timer.timeout.connect(self.reload_boards)
        self._periodic_timer.start()

    def _executor_names(self) -> list[str]:
        self.executors_store.load()
        return list(self.executors_store.names)

    def _note_task_change(
        self,
        task,
        *,
        before: dict | None = None,
        action: str = "upsert",
    ) -> None:
        sync = getattr(self, "notion_sync", None)
        if sync is None:
            return
        sync.notify_local_change(task, action=action, before=before)

    def _note_lists_change(self) -> None:
        sync = getattr(self, "notion_sync", None)
        if sync is None:
            return
        sync.notify_lists_change()

    def _on_notion_applied(self) -> None:
        self.reload_boards()

    def _on_notion_conflicts(self, conflicts: list) -> None:
        if not conflicts:
            return
        for item in conflicts[:12]:
            tid = item.get("task_id") or ""
            title = item.get("title") or tid
            fields = ", ".join(item.get("fields") or [])
            msg = (
                f"Расхождение по задаче «{title}» (#{tid}).\n"
                f"Поля: {fields}\n\n"
                f"Локально: {item.get('local')}\n"
                f"Notion: {item.get('remote')}\n\n"
                "Да = взять локальное, Нет = взять Notion, Отмена = пропустить."
            )
            box = QMessageBox(self)
            box.setWindowTitle("Сверка с Notion")
            box.setText(msg)
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel
            )
            box.button(QMessageBox.StandardButton.Yes).setText("Локальное")
            box.button(QMessageBox.StandardButton.No).setText("Notion")
            box.button(QMessageBox.StandardButton.Cancel).setText("Пропустить")
            reply = box.exec()
            if reply == QMessageBox.StandardButton.Yes:
                self.notion_sync.resolve_conflict(tid, prefer="local")
            elif reply == QMessageBox.StandardButton.No:
                self.notion_sync.resolve_conflict(tid, prefer="remote")
        self.reload_boards()

    def reload(self) -> None:
        self.store.load()
        self.reload_boards()

    def reload_boards(self) -> None:
        if not self.demo_mode:
            created = spawn_periodic_copies(self.store)
            if created:
                self.store.save()
                for task in created:
                    append_log(
                        "created",
                        task,
                        source="app",
                        detail="периодичность",
                        before_state=None,
                    )
                    self._note_task_change(task, action="upsert")
        self.logs_board.rebuild()
        self.backlog_board.rebuild()
        self.lists_board.rebuild()
        self.day_board.rebuild()
        for board in self.boards:
            board.rebuild()
        self._sync_day_controls_visibility()
        self._sync_history_buttons()

    def _update_screen_label(self, index: int) -> None:
        n = len(self.screen_titles)
        if 0 <= index < n:
            self.screen_label.setText(
                f"  {self.screen_titles[index][1]}  ({index + 1}/{n})  "
            )

    def _on_screen_changed(self, index: int) -> None:
        self._update_screen_label(index)
        self._sync_day_controls_visibility()
        if index == 0:
            self.logs_board.rebuild()
            return
        if index == 1:
            self.backlog_board.rebuild()
            return
        if index == 2:
            self.lists_board.rebuild()
            return
        if index == 3:
            self.day_board.rebuild()
            return
        board_idx = index - 4
        if 0 <= board_idx < len(self.boards):
            self.boards[board_idx].rebuild()

    def _is_day_screen(self) -> bool:
        return self.stack.currentIndex() == 3

    def _sync_day_controls_visibility(self) -> None:
        on_day = self._is_day_screen()
        self.btn_answers.setVisible(not on_day)
        self.btn_label.setVisible(not on_day)
        self.btn_rect.setVisible(not on_day)
        if on_day:
            self.place_label_mode = False
            self.draw_rect_mode = False
            self.btn_label.set_active(False)
            self.btn_rect.set_active(False)
        if not on_day and self._controls_on_left:
            self._controls_on_left = False
            self._place_floating_controls()

    def on_day_inbox_changed(self, has_inbox: bool) -> None:
        want_left = has_inbox and self._is_day_screen()
        side_changed = want_left != self._controls_on_left
        prev = getattr(self, "_day_has_inbox", None)
        inbox_changed = prev is not None and prev != has_inbox
        self._day_has_inbox = has_inbox
        if side_changed:
            self._controls_on_left = want_left
            self._place_floating_controls()
        elif self._is_day_screen():
            self._place_floating_controls()
        if self._is_day_screen():
            self.day_board._apply_side_margins(want_left)
            # после hide/show входящих ширина ДЕНЬ меняется — пересобрать на следующем тике
            if side_changed or inbox_changed:
                QTimer.singleShot(0, self._deferred_day_rebuild)

    def _deferred_day_rebuild(self) -> None:
        if not self._is_day_screen():
            return
        self.day_board.rebuild(defer_inbox_hook=True)

    def _on_swipe(self, direction: int) -> None:
        idx = self.stack.currentIndex()
        n = len(self.screen_titles)
        nxt = (idx + (1 if direction < 0 else -1)) % n
        self.stack.setCurrentIndex(nxt)

    def _show_filter_ui(self, text: str) -> None:
        self.filter_label.setText(text)
        self.btn_clear_filter.show()

    def on_tag_order_changed(self) -> None:
        for board in self.boards:
            active = self.filter_tag
            board.tag_bar.rebuild_circles()
            board.tag_bar.set_active_filter(active)
        self.day_board.tag_bar.rebuild_circles()
        self.day_board.tag_bar.set_active_filter(self.filter_tag)

    def on_tag_filter(self, tag_key: str) -> None:
        key = canonicalize_tag_key(tag_key)
        if not key:
            return
        if self.filter_tag == key and self.filter_project is None:
            self.clear_filters()
            return
        self.filter_tag = key
        self.filter_project = None
        self._show_filter_ui(f"Фильтр: {key}")
        self.reload_boards()

    def clear_paint_mode(self) -> None:
        self.paint_mode = None
        self.set_action_highlight(None)
        for board in self.boards:
            board.tag_bar.set_highlight(None)
        self.day_board.set_tag_highlight(None)
        self.day_board.set_priority_highlight(None)
        self.day_board.set_executor_highlight(None)
        QApplication.restoreOverrideCursor()
        self.unsetCursor()

    def on_section_tag_circle(self, tag_key: str) -> None:
        """Кружок тега в заголовке раздела Дня: кисть красит раздел, иначе берёт тег."""
        look = canonicalize_tag_key(tag_key) if tag_key not in SPECIAL_ACTION_KEYS else tag_key
        ids = self.day_board.section_task_ids("tag", look or tag_key)
        if self._apply_current_brush_to_ids(ids):
            return
        self.on_tag_pick(tag_key)

    def on_tag_pick(self, tag_key: str) -> None:
        """Клик по кружку тега внизу/сбоку: взять кисть, не красить раздел."""
        key = canonicalize_tag_key(tag_key) if tag_key not in SPECIAL_ACTION_KEYS else tag_key
        if not key and tag_key not in SPECIAL_ACTION_KEYS:
            # для обычных тегов
            key = tag_key
        if self.paint_mode == ("tag", key):
            self.clear_paint_mode()
            return
        self.paint_mode = ("tag", key)
        self.set_action_highlight(None)
        self.day_board.set_priority_highlight(None)
        self.day_board.set_executor_highlight(None)
        for board in self.boards:
            board.tag_bar.set_highlight(key)
        self.day_board.set_tag_highlight(key)
        QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def on_priority_pick(self, section: str) -> None:
        """Клик по заголовку Горит/Нужно/Можно: кисть как drop в раздел."""
        ids = self.day_board.section_task_ids("priority", section)
        if self._apply_current_brush_to_ids(ids):
            return
        if self.paint_mode == ("priority", section):
            self.clear_paint_mode()
            return
        self.paint_mode = ("priority", section)
        self.set_action_highlight(None)
        for board in self.boards:
            board.tag_bar.set_highlight(None)
        self.day_board.set_tag_highlight(None)
        self.day_board.set_executor_highlight(None)
        self.day_board.set_priority_highlight(section)
        QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _on_action_tool_clicked(self, action_key: str) -> None:
        """Боковой кружок: взять кисть, не красить раздел."""
        if self.paint_mode == ("action", action_key):
            self.clear_paint_mode()
            return
        self.paint_mode = ("action", action_key)
        self.set_action_highlight(action_key)
        for board in self.boards:
            board.tag_bar.set_highlight(None)
        self.day_board.set_tag_highlight(None)
        self.day_board.set_priority_highlight(None)
        self.day_board.set_executor_highlight(None)
        QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)

    def on_executor_pick(self, name: str) -> None:
        """Клик по разделу исполнителя: кисть «этот исполнитель»."""
        who = (name or "").strip()
        if not who:
            return
        ids = self.day_board.section_task_ids("executor", who)
        if self.paint_mode and self.paint_mode[0] != "executor":
            if self._apply_current_brush_to_ids(ids):
                return
        if self.paint_mode == ("executor", who):
            self.clear_paint_mode()
            return
        self.paint_mode = ("executor", who)
        self.set_action_highlight(None)
        for board in self.boards:
            board.tag_bar.set_highlight(None)
        self.day_board.set_tag_highlight(None)
        self.day_board.set_priority_highlight(None)
        self.day_board.set_executor_highlight(who)
        QApplication.restoreOverrideCursor()
        QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def section_brush_key(self) -> str | None:
        """Ключ кисти кнопки/тега для покраски раздела (не исполнитель)."""
        pm = self.paint_mode
        if not pm:
            return None
        if pm[0] in {"action", "tag"}:
            return pm[1]
        return None

    def _apply_current_brush_to_ids(self, ids: list[str]) -> bool:
        """Покрасить список задач текущей кистью. False, если кисти нет."""
        pm = self.paint_mode
        if not pm or not ids:
            return False
        kind, key = pm
        if kind == "executor":
            self.apply_executor_to_tasks(ids, key, mass=True)
            return True
        if kind == "priority":
            from .day_tasks import apply_priority_section

            batch = str(uuid.uuid4())
            changed = False
            for tid in ids:
                task = (
                    next((t for t in self.demo_tasks if t.id == tid), None)
                    if self.demo_mode
                    else self.store.get(tid)
                )
                if not task:
                    continue
                before_state = snapshot_dict(task)
                before_text = format_task_snapshot(task)
                apply_priority_section(task, key)
                if snapshot_dict(task) == before_state:
                    continue
                changed = True
                if not self.demo_mode:
                    self._log_action_result(task, key, before_text, before_state, batch=batch)
                    self._note_task_change(task, before=before_state)
            if changed and not self.demo_mode:
                self.store.save()
            if changed:
                self._last_paint_key = None
                self.reload_boards()
                self._sync_history_buttons()
            return True
        if kind in {"action", "tag"}:
            self.apply_brush_to_tasks(ids, key, mass=True)
            return True
        return False

    def apply_brush_to_tasks(
        self, task_ids: list[str], action_key: str, *, mass: bool = False
    ) -> None:
        ids = [tid for tid in task_ids if tid]
        if not ids:
            return
        batch = str(uuid.uuid4()) if mass else None
        changed = False
        for tid in ids:
            if self.demo_mode:
                task = next((t for t in self.demo_tasks if t.id == tid), None)
            else:
                task = self.store.get(tid)
            if not task:
                continue
            before_state = snapshot_dict(task)
            before_text = format_task_snapshot(task)
            self._apply_action(task, action_key)
            if action_key != TODAY_ACTION and snapshot_dict(task) == before_state:
                continue
            changed = True
            if not self.demo_mode:
                self._log_action_result(
                    task, action_key, before_text, before_state, batch=batch
                )
                self._note_task_change(task, before=before_state)
        if changed and not self.demo_mode:
            self.store.save()
        if changed:
            self._last_paint_key = None
            self.reload_boards()
            self._sync_history_buttons()

    def apply_executor_to_tasks(
        self, task_ids: list[str], executor: str, *, mass: bool = False
    ) -> None:
        name = (executor or "").strip()
        if not name:
            return
        ids = [tid for tid in task_ids if tid]
        if not ids:
            return
        batch = str(uuid.uuid4()) if mass else None
        changed = False
        for tid in ids:
            if self.demo_mode:
                task = next((t for t in self.demo_tasks if t.id == tid), None)
            else:
                task = self.store.get(tid)
            if not task:
                continue
            old = (getattr(task, "executor", "") or "").strip()
            if old == name:
                continue
            before_state = snapshot_dict(task)
            before_text = format_task_snapshot(task)
            task.executor = name
            changed = True
            if not self.demo_mode:
                append_log(
                    "changed",
                    task,
                    before=before_text,
                    detail=f"исполнитель {name}",
                    source="app",
                    before_state=before_state,
                    batch=batch,
                )
                self._note_task_change(task, before=before_state)
        if changed and not self.demo_mode:
            self.store.save()
        if changed:
            self._last_paint_key = None
            self.reload_boards()
            self._sync_history_buttons()

    def on_day_section_click(self, kind: str, name: str) -> None:
        ids = self.day_board.section_task_ids(kind, name)
        if self.paint_mode and not (kind == "executor" and self.paint_mode[0] == "executor"):
            if self._apply_current_brush_to_ids(ids):
                return
        if kind == "executor":
            self.on_executor_pick(name)
            return

    def _snapshot_task(self, task: Task) -> dict:
        return snapshot_dict(task)

    def _restore_task(self, task: Task, snap: dict) -> None:
        apply_state_to_task(task, snap)

    def _sync_history_buttons(self) -> None:
        if self.demo_mode:
            self.btn_undo.setEnabled(False)
            self.btn_redo.setEnabled(False)
            return
        self.btn_undo.setEnabled(find_undo_target() is not None)
        self.btn_redo.setEnabled(find_redo_target() is not None)

    def history_undo(self) -> None:
        if self.demo_mode:
            return
        targets = find_undo_targets()
        if not targets:
            self._sync_history_buttons()
            return
        for target in targets:
            self._undo_one(target)
        self.store.save()
        self.reload_boards()
        self._sync_history_buttons()

    def _undo_one(self, target) -> None:
        tid = (target.task_id or "").strip()
        current = self.store.get(tid) if tid else None
        current_snap = snapshot_dict(current) if current else None

        if target.action == "created":
            if tid:
                self.store.remove_task(tid)
            append_log(
                "changed",
                task_id=tid,
                before=format_task_snapshot(current) if current else target.after,
                after="(удалено)",
                detail="undo",
                source="app",
                before_state=current_snap or target.after_state,
                after_state=None,
                undoes_ts=target.ts_key,
            )
            return
        if not target.before_state:
            return
        if current is None:
            restored = task_from_state(target.before_state)
            if restored.id:
                self.store.insert_task(restored)
                current = restored
        else:
            self._restore_task(current, target.before_state)
        append_log(
            "changed",
            current,
            before=format_task_snapshot(task_from_state(target.after_state))
            if target.after_state
            else (target.after or ""),
            detail="undo",
            source="app",
            before_state=target.after_state or current_snap,
            after_state=target.before_state,
            undoes_ts=target.ts_key,
        )

    def history_redo(self) -> None:
        if self.demo_mode:
            return
        targets = find_redo_targets()
        if not targets:
            self._sync_history_buttons()
            return
        for undo_entry in targets:
            self._redo_one(undo_entry)
        self.store.save()
        self.reload_boards()
        self._sync_history_buttons()

    def _redo_one(self, undo_entry) -> None:
        tid = (undo_entry.task_id or "").strip()
        # undo_entry.before_state = состояние после исходного действия
        # undo_entry.after_state = состояние до исходного (куда откатили)
        forward = undo_entry.before_state
        current = self.store.get(tid) if tid else None

        if forward is None and tid and current is not None:
            before_snap = snapshot_dict(current)
            self.store.remove_task(tid)
            append_log(
                "changed",
                task_id=tid,
                before=format_task_snapshot(current),
                after="(удалено)",
                detail="redo",
                source="app",
                before_state=before_snap,
                after_state=None,
                undoes_ts=undo_entry.undoes_ts,
            )
            return
        if forward is None:
            return
        restored = task_from_state(forward)
        if not restored.id and tid:
            restored.id = tid
        if self.store.get(restored.id) is None:
            self.store.insert_task(restored)
            current = restored
        else:
            current = self.store.get(restored.id)
            assert current is not None
            self._restore_task(current, forward)
        append_log(
            "changed",
            current,
            before=format_task_snapshot(task_from_state(undo_entry.after_state))
            if undo_entry.after_state
            else (undo_entry.after or ""),
            detail="redo",
            source="app",
            before_state=undo_entry.after_state,
            after_state=forward,
            undoes_ts=undo_entry.undoes_ts,
        )

    def _undo_last_paint(self) -> None:
        self.history_undo()

    def _apply_paint_to_task(self, task_id: str) -> None:
        if not self.paint_mode:
            return
        kind, key = self.paint_mode
        # Повторный клик по той же задаче той же кистью — отмена
        if (
            self._last_paint_key
            and self._last_paint_key[0] == task_id
            and self._last_paint_key[1] == key
            and not self.demo_mode
        ):
            self.history_undo()
            self._last_paint_key = None
            return
        if self.demo_mode:
            task = next((t for t in self.demo_tasks if t.id == task_id), None)
        else:
            task = self.store.get(task_id)
        if not task:
            return
        before_state = self._snapshot_task(task)
        before_text = format_task_snapshot(task)
        if kind == "tag":
            from .tags import CANCEL_TAG, CONTROL_TAG, DONE_TAG, apply_control_tag

            log_action = "changed"
            log_detail = f"toggle {key}"
            if key == CONTROL_TAG:
                if task.has_tag(CONTROL_TAG):
                    task.remove_tag(CONTROL_TAG)
                else:
                    apply_control_tag(task)
            elif key == DONE_TAG:
                if task.is_done():
                    task.remove_tag(DONE_TAG)
                    task.completed_at = None
                else:
                    apply_status_tag(task, DONE_TAG)
                    log_action = "completed"
                    log_detail = ""
            elif key == CANCEL_TAG:
                if task.is_cancelled():
                    task.remove_tag(CANCEL_TAG)
                else:
                    apply_status_tag(task, CANCEL_TAG)
                    log_action = "cancelled"
                    log_detail = ""
            else:
                task.toggle_tag(key)
            if not self.demo_mode:
                self.store.save()
                append_log(
                    log_action,
                    task,
                    before=before_text,
                    detail=log_detail,
                    source="app",
                    before_state=before_state,
                )
                self._note_task_change(task, before=before_state)
                self._last_paint_key = (task_id, key)
            self.reload_boards()
            self._sync_history_buttons()
            return
        if kind == "priority":
            apply_priority_section(task, key)
            if not self.demo_mode:
                self.store.save()
                append_log(
                    "moved",
                    task,
                    before=before_text,
                    detail=key,
                    source="app",
                    before_state=before_state,
                )
                self._note_task_change(task, before=before_state)
                self._last_paint_key = (task_id, key)
            self.reload_boards()
            self._sync_history_buttons()
            return
        if kind == "executor":
            old = (getattr(task, "executor", "") or "").strip()
            if old == key:
                return
            task.executor = key
            if not self.demo_mode:
                self.store.save()
                append_log(
                    "changed",
                    task,
                    before=before_text,
                    detail=f"исполнитель {key}",
                    source="app",
                    before_state=before_state,
                )
                self._note_task_change(task, before=before_state)
                self._last_paint_key = (task_id, key)
            self.reload_boards()
            self._sync_history_buttons()
            return
        # action
        self._apply_action(task, key)
        if not self.demo_mode:
            self.store.save()
            self._log_action_result(task, key, before_text, before_state)
            self._note_task_change(task, before=before_state)
            self._last_paint_key = (task_id, key)
        self.reload_boards()
        self._sync_history_buttons()

    def on_project_filter(self, project: str) -> None:
        from .projects import resolve_project_name, same_project

        name = resolve_project_name(project, self.visible_tasks()) or project.strip()
        if same_project(self.filter_project or "", name) and self.filter_tag is None:
            self.clear_filters()
            return
        self.filter_project = name
        self.filter_tag = None
        self._show_filter_ui(f"Проект: {name}")
        self.reload_boards()

    def _nav_contains_global(self, global_pos: QPoint) -> bool:
        for btn in (self.btn_left, self.btn_right):
            local = btn.mapFromGlobal(global_pos)
            if btn.rect().contains(local):
                return True
        return False

    def action_at_global(self, global_pos: QPoint) -> str | None:
        if self._nav_contains_global(global_pos):
            return None
        for circle in self._action_circles:
            local = circle.mapFromGlobal(global_pos)
            if circle.rect().contains(local):
                return circle.tag_key
        return None

    def set_action_highlight(self, key: str | None) -> None:
        for circle in self._action_circles:
            circle.set_highlighted(circle.tag_key == key)

    def apply_action_to_task(self, task_id: str, action_key: str) -> None:
        if self.demo_mode:
            task = next((t for t in self.demo_tasks if t.id == task_id), None)
            if not task:
                return
            self._apply_action(task, action_key)
            self.reload_boards()
            return
        task = self.store.get(task_id)
        if not task:
            return
        before_snap = format_task_snapshot(task)
        before_state = snapshot_dict(task)
        before_tags = list(task.tags)
        before_completed = task.completed_at
        before_start = task.start_at
        before_due = task.due_at
        before_remind = task.remind_at
        self._apply_action(task, action_key)
        changed = (
            action_key in (TODAY_ACTION, DONE_CHECK_ACTION)
            or task.tags != before_tags
            or task.completed_at != before_completed
            or task.start_at != before_start
            or task.due_at != before_due
            or task.remind_at != before_remind
        )
        if changed:
            self.store.save()
            self._log_action_result(task, action_key, before_snap, before_state)
            self._last_paint_key = None
            self.reload_boards()
            self._sync_history_buttons()

    def _log_action_result(
        self,
        task: Task,
        action_key: str,
        before: str,
        before_state: dict | None = None,
        *,
        batch: str | None = None,
    ) -> None:
        key = canonicalize_tag_key(action_key) if action_key not in SPECIAL_ACTION_KEYS else action_key
        kwargs = {"before": before, "source": "app", "before_state": before_state, "batch": batch}
        if key == DONE_TAG or key == DONE_CHECK_ACTION:
            append_log("completed", task, **kwargs)
        elif key == CANCEL_TAG:
            append_log("cancelled", task, **kwargs)
        elif key == TODAY_ACTION:
            append_log("moved", task, detail="скрыта на 4 часа", **kwargs)
        elif key == TOMORROW_ACTION:
            append_log("moved", task, detail="ЗАВТРА", **kwargs)
        elif key == WEEK_ACTION:
            append_log("moved", task, detail="НЕДЕЛЯ", **kwargs)
        elif key == INBOX_TAG:
            append_log("moved", task, detail="ВХОДЯЩИЕ", **kwargs)
        elif key == BACKLOG_TAG:
            append_log("moved", task, detail="БЭКЛОГ", **kwargs)
        else:
            append_log(
                "changed",
                task,
                detail=str(action_key),
                **kwargs,
            )

    def _apply_action(self, task: Task, action_key: str) -> None:
        key = action_key
        if key == TODAY_ACTION:
            if not self.demo_mode:
                hide_task_on_day(task.id, hours=4)
        elif key == DONE_CHECK_ACTION:
            apply_status_tag(task, DONE_TAG)
            clear_actual_tag(task)
            if not self.demo_mode:
                self._spawn_verify_task(task)
        elif key == TOMORROW_ACTION:
            move_task_to_tomorrow(task)
        elif key == WEEK_ACTION:
            move_task_by_week(task)
        elif key == INBOX_TAG:
            apply_inbox_to_task(task)
        elif key == ANSWERS_TAG:
            apply_answers_tag(task)
        else:
            apply_status_tag(task, key)

    def _spawn_verify_task(self, source: Task) -> None:
        tags = [
            t
            for t in source.tags
            if t not in {DONE_TAG, CANCEL_TAG, ACTUAL_TAG}
        ]
        title = (source.title or "").strip()
        if not title.casefold().startswith("проверить "):
            title = f"Проверить {title}"
        tomorrow = date.today() + timedelta(days=1)
        new = self.store.add_task(
            title=title,
            created_at=date.today(),
            start_at=tomorrow,
            tags=tags,
            project=source.project,
            executor=source.executor or DEFAULT_EXECUTOR,
            description=source.description,
            author=source.author,
        )
        append_log("created", new, source="app", before_state=None)
        self._note_task_change(new, action="upsert")

    def on_task_clicked(self, task_id: str) -> None:
        if self.paint_mode:
            self._apply_paint_to_task(task_id)
            return
        self.selected_task_id = task_id
        self.selected_ann_id = None

    def on_annotation_selected(self, ann_id: str) -> None:
        self.selected_ann_id = ann_id or None
        self.selected_task_id = None
        idx = self.stack.currentIndex()
        board_idx = idx - 4
        if board_idx < 0 or board_idx >= len(self.boards):
            return
        board = self.boards[board_idx]
        for lid, w in board.label_blocks.items():
            w.set_selected(lid == ann_id)
        for rid, w in board.rect_blocks.items():
            w.set_selected(rid == ann_id)

    def clear_filters(self) -> None:
        self.filter_tag = None
        self.filter_project = None
        self.filter_label.setText("")
        self.btn_clear_filter.hide()
        self.reload_boards()

    def clear_tag_filter(self) -> None:
        self.clear_filters()

    def toggle_demo(self) -> None:
        self.demo_mode = not self.demo_mode
        if self.demo_mode:
            self.demo_tasks = _demo_tasks()
            self.filter_tag = None
            self.filter_project = None
            self.filter_label.setText("ДЕМО")
            self.btn_clear_filter.hide()
            self.btn_demo.setStyleSheet("background:#FFECB3; font-weight:600;")
        else:
            self.demo_tasks = []
            self.btn_demo.setStyleSheet("")
            if not self.filter_tag and self.filter_project is None:
                self.filter_label.setText("")
        self.reload_boards()

    def visible_tasks(self) -> list[Task]:
        """Единственный источник задач для UI."""
        if self.demo_mode:
            return list(self.demo_tasks)
        return list(self.store.tasks)

    def _project_names(self) -> list[str]:
        from .projects import project_key
        from .tag_order import projects_by_usage_frequency

        names = projects_by_usage_frequency(self.visible_tasks())
        return [n for n in names if project_key(n) != SOCIAL_TAG]

    def send_executor_list(self, executor: str) -> None:
        from .day_hide import without_hidden
        from .day_tasks import executor_sections
        from .studio_notify import send_executor_tasks

        if self.demo_mode:
            QMessageBox.information(self, "ДЕМО", "В демо-режиме отправка в Telegram отключена.")
            return
        tasks = without_hidden(self.visible_tasks())
        found: list[Task] = []
        for name, lst in executor_sections(tasks):
            if name == executor:
                found = lst
                break
        try:
            send_executor_tasks(executor, found)
        except Exception as exc:  # noqa: BLE001 — показать текст API пользователю
            QMessageBox.warning(self, "Telegram", str(exc))
            return
        QMessageBox.information(
            self,
            "Telegram",
            f"Список «{executor}» отправлен в чат PGD studio AI.",
        )

    def cancel_draw_modes(self) -> None:
        self.place_label_mode = False
        self.draw_rect_mode = False
        self.btn_label.set_active(False)
        self.btn_rect.set_active(False)

    def _toggle_place_label(self) -> None:
        self.draw_rect_mode = False
        self.btn_rect.set_active(False)
        self.place_label_mode = not self.place_label_mode
        self.btn_label.set_active(self.place_label_mode)

    def _toggle_draw_rect(self) -> None:
        self.place_label_mode = False
        self.btn_label.set_active(False)
        self.draw_rect_mode = not self.draw_rect_mode
        self.btn_rect.set_active(self.draw_rect_mode)

    def begin_label_at(self, screen_id: str, pos: QPoint) -> None:
        board_idx = self.stack.currentIndex() - 4
        if board_idx < 0 or board_idx >= len(self.boards):
            return
        board = self.boards[board_idx]
        if self._label_editor is not None:
            self._label_editor.deleteLater()
        editor = QLineEdit(board)
        editor.setGeometry(pos.x(), pos.y(), 180, 28)
        editor.setPlaceholderText("Текст надписи…")
        editor.show()
        editor.setFocus()
        self._label_editor = editor
        self.place_label_mode = False
        self.btn_label.set_active(False)

        def commit() -> None:
            text = editor.text().strip()
            editor.deleteLater()
            self._label_editor = None
            if not text or self.demo_mode:
                return
            item = self.annotations.add_label(text, float(pos.x()), float(pos.y()), screen_id)
            board.rebuild()
            self.on_annotation_selected(item.id)

        editor.returnPressed.connect(commit)

    def finish_rect(self, screen_id: str, x: float, y: float, w: float, h: float) -> None:
        self.draw_rect_mode = False
        self.btn_rect.set_active(False)
        if self.demo_mode:
            return
        item = self.annotations.add_rect(x, y, w, h, screen_id)
        self.reload_boards()
        self.on_annotation_selected(item.id)

    def enter_fullscreen(self) -> None:
        self._fullscreen = True
        self.chrome.hide()
        self.btn_left.hide()
        self.btn_right.hide()
        self.showFullScreen()
        self._place_floating_controls()
        self._raise_floating()
        self.reload_boards()

    def exit_fullscreen(self) -> None:
        self._fullscreen = False
        self.chrome.show()
        self.btn_left.show()
        self.btn_right.show()
        self.showNormal()
        self._place_floating_controls()
        self._raise_floating()
        self.reload_boards()

    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def restart_app_fullscreen(self) -> None:
        """Закрыть текущий процесс и открыть новый в полном экране (для обновлений кода)."""
        import sys
        from pathlib import Path

        from PyQt6.QtCore import QProcess

        from .paths import app_root

        root = str(app_root())
        if getattr(sys, "frozen", False):
            ok = QProcess.startDetached(sys.executable, ["--fullscreen"], root)
        else:
            exe = sys.executable
            if exe.lower().endswith("python.exe"):
                cand = exe[:-10] + "pythonw.exe"
                if Path(cand).exists():
                    exe = cand
            ok = QProcess.startDetached(exe, ["-m", "app", "--fullscreen"], root)
        if not ok:
            QMessageBox.warning(
                self,
                "Перезапуск",
                "Не удалось запустить новый процесс. Закрой приложение вручную и открой снова.",
            )
            return
        QApplication.instance().quit()

    def _place_floating_controls(self) -> None:
        gap = 8
        cy = max(80, self.height() // 2 - CIRCLE // 2)
        if self._fullscreen:
            self.btn_left.hide()
            self.btn_right.hide()
            right_geom = QRect()  # нет пересечения со стрелкой
        else:
            self.btn_left.show()
            self.btn_right.show()
            self.btn_left.setGeometry(12, cy, CIRCLE, CIRCLE)
            right_x = self.width() - CIRCLE - 12
            self.btn_right.setGeometry(right_x, cy, CIRCLE, CIRCLE)
            right_geom = self.btn_right.geometry()

        panel_x = 16 if self._controls_on_left else self.width() - CIRCLE - 16
        left_geom = self.btn_left.geometry() if not self._fullscreen else QRect()
        nav_geom = left_geom if self._controls_on_left else right_geom
        children: list[QWidget] = []
        layout = self.controls.layout()
        if layout is not None:
            layout.setEnabled(False)
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget() if item else None
                if w is not None and not w.isHidden():
                    children.append(w)

        y = 16
        shifted = False
        for w in children:
            win_rect = QRect(panel_x, y, CIRCLE, CIRCLE)
            if not shifted and nav_geom.isValid() and win_rect.intersects(nav_geom):
                y = nav_geom.bottom() + gap
                shifted = True
            local_y = y - 16
            w.setGeometry(0, local_y, CIRCLE, CIRCLE)
            w.show()
            y += CIRCLE + gap

        panel_h = max(CIRCLE, y - 16)
        self.controls.setGeometry(panel_x, 16, CIRCLE, panel_h)
        demo_w, demo_h = 72, 36
        self.btn_demo.setGeometry(
            self.width() - demo_w - CIRCLE - 24,
            self.height() - demo_h - 12,
            demo_w,
            demo_h,
        )

    def _raise_floating(self) -> None:
        self.controls.raise_()
        self.btn_demo.raise_()
        if not self._fullscreen:
            self.btn_left.raise_()
            self.btn_right.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_floating_controls()
        self._raise_floating()

    def new_task(self) -> None:
        self.new_task_at(None, None)

    def new_task_at(self, x: float | None, y: float | None) -> None:
        if self.demo_mode:
            QMessageBox.information(self, "ДЕМО", "В демо-режиме создание задач отключено.")
            return
        day_screen = self._is_day_screen()
        dlg_kwargs: dict = {
            "project_names": self._project_names(),
            "all_tasks": self.visible_tasks(),
            "executor_names": self._executor_names(),
        }
        if day_screen:
            dlg_kwargs["default_start"] = date.today()
            dlg_kwargs["default_tags"] = INBOX_TAG
        dlg = NewTaskDialog(self, **dlg_kwargs)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            QMessageBox.warning(self, "Ошибка", "Название обязательно.")
            return
        data["executor"] = (data.get("executor") or "").strip() or DEFAULT_EXECUTOR
        if x is not None and y is not None:
            data["pos_x"] = x
            data["pos_y"] = y
        preset = data.pop("create_preset", None) or dlg.create_preset()
        tags = [canonicalize_tag_key(t) for t in data.get("tags") or []]
        tags = [t for t in tags if t]
        data["tags"] = list(dict.fromkeys(tags))
        if day_screen and not preset:
            data["start_at"] = date.today()
            if INBOX_TAG not in data["tags"]:
                data["tags"].insert(0, INBOX_TAG)
        elif day_screen and preset == PRESET_INBOX:
            data["start_at"] = date.today()
        data = apply_preset_to_new_task_data(data, preset)
        if preset and preset != PRESET_INBOX:
            data["tags"] = [t for t in data["tags"] if t != INBOX_TAG]
        task = self.store.add_task(**data)
        if task.is_done() and task.completed_at is None:
            task.completed_at = date.today()
            self.store.save()
        append_log("created", task, source="app", before_state=None)
        if task.is_done():
            before_done = snapshot_dict(task)
            append_log("completed", task, source="app", before_state=before_done)
        self._note_task_change(task, action="upsert")
        self._last_paint_key = None
        self.reload()
        self._sync_history_buttons()

    def edit_task(self, task_id: str) -> None:
        if self.demo_mode:
            QMessageBox.information(self, "ДЕМО", "В демо-режиме редактирование отключено.")
            return
        task = self.store.get(task_id)
        if not task:
            return
        dlg = EditTaskDialog(
            task,
            self,
            project_names=self._project_names(),
            all_tasks=self.visible_tasks(),
            executor_names=self._executor_names(),
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        data = dlg.result_data()
        if not data:
            QMessageBox.warning(self, "Ошибка", "Название обязательно.")
            return
        preset = data.pop("create_preset", None)
        data = apply_preset_to_new_task_data(data, preset)
        if preset and preset != PRESET_DONE and DONE_TAG not in (data.get("tags") or []):
            data["completed_at"] = None
        before = format_task_snapshot(task)
        before_state = snapshot_dict(task)
        was_done = task.is_done()
        was_cancelled = task.is_cancelled()
        old_start = task.start_at
        task.title = data["title"]
        from .projects import resolve_project_name
        from .tags import CONTROL_TAG, apply_control_tag, clear_inbox_tag

        task.project = resolve_project_name(data["project"], self.store.tasks)
        task.description = data["description"]
        task.author = data["author"]
        task.executor = str(data.get("executor") or "").strip()
        task.created_at = data["created_at"]
        task.completed_at = data["completed_at"]
        new_start = data["start_at"]
        if new_start != old_start:
            clear_inbox_tag(task)
        task.start_at = new_start
        task.due_at = data["due_at"]
        task.remind_at = data["remind_at"]
        task.remind_time = str(data.get("remind_time") or "").strip()
        task.remind_period = data["remind_period"]
        from .period_roll import ensure_task_series

        ensure_task_series(task)
        tags = [canonicalize_tag_key(t) for t in data["tags"]]
        if new_start != old_start:
            tags = [t for t in tags if t and t != INBOX_TAG and t != "входящие"]
        had_backlog = task.is_backlog()
        had_control = task.has_tag(CONTROL_TAG)
        task.tags = list(dict.fromkeys(tags))
        if new_start != old_start:
            clear_inbox_tag(task)
        if task.is_backlog() and not had_backlog:
            from .sorting import apply_backlog_deferral

            apply_backlog_deferral(task)
        if task.has_tag(CONTROL_TAG) and not had_control:
            apply_control_tag(task)
        if task.is_done():
            task.remove_tag(CANCEL_TAG)
            if DONE_TAG not in task.tags:
                task.tags.append(DONE_TAG)
        elif task.is_cancelled():
            task.remove_tag(DONE_TAG)
            if CANCEL_TAG not in task.tags:
                task.tags.append(CANCEL_TAG)
        self.store.save()
        if task.is_done() and not was_done:
            append_log(
                "completed",
                task,
                before=before,
                source="app",
                before_state=before_state,
            )
        elif task.is_cancelled() and not was_cancelled:
            append_log(
                "cancelled",
                task,
                before=before,
                source="app",
                before_state=before_state,
            )
        else:
            after = format_task_snapshot(task)
            if after != before:
                append_log(
                    "changed",
                    task,
                    before=before,
                    after=after,
                    source="app",
                    before_state=before_state,
                )
        self._note_task_change(task, before=before_state, action="upsert")
        self._last_paint_key = None
        self.reload_boards()
        self._sync_history_buttons()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_ann_id and not self.demo_mode:
                if self.annotations.remove(self.selected_ann_id):
                    self.selected_ann_id = None
                    self.reload_boards()
                return
        if event.key() == Qt.Key.Key_Escape:
            if self.place_label_mode or self.draw_rect_mode:
                self.cancel_draw_modes()
                return
            if self.filter_tag or self.filter_project is not None:
                self.clear_filters()
                return
            if self._fullscreen:
                self.exit_fullscreen()
                return
        if event.key() == Qt.Key.Key_Left:
            self._on_swipe(1)
            return
        if event.key() == Qt.Key.Key_Right:
            self._on_swipe(-1)
            return
        super().keyPressEvent(event)


def run_app(xlsx_path: Path | None = None) -> int:
    import sys

    from .icons import app_icon, set_windows_app_id
    from .tag_order import load_order

    set_windows_app_id("Tanion37.TanionPlaning")

    app = QApplication(sys.argv)
    from .paths import app_root

    root = app_root()
    icon = app_icon(root)
    app.setWindowIcon(icon)
    load_order(root)
    store = TaskStore(xlsx_path)
    store.load()
    annotations = AnnotationStore.load(root)
    window = MainWindow(store, annotations)
    window.setWindowIcon(icon)
    window.show()
    if "--fullscreen" in sys.argv:
        window.enter_fullscreen()
    return app.exec()
