"""Виджеты задач и панели тегов."""

from __future__ import annotations

import re
from datetime import date

from PyQt6.QtCore import QDate, QEvent, QMimeData, QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QFont, QKeyEvent, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .colors import border_color, font_color
from .models import Task, parse_date
from .tags import REMIND_PERIODS, tags_to_cell

TASK_W = 200
TASK_H = 50
CIRCLE = 50
# Компактные значки тегов в диалогах создания/правки
TAG_ICON = 32
MIME_TAG = "application/x-tanion-tag"


class TaskBlock(QWidget):
    moved = pyqtSignal(str, float, float)  # id, x, y
    dropped_on_tag = pyqtSignal(str, str)  # task_id, tag_key
    tag_dropped = pyqtSignal(str, str)  # task_id, tag_key (тег на задачу)
    double_clicked = pyqtSignal(str)  # task_id
    project_clicked = pyqtSignal(str)  # project name
    clicked = pyqtSignal(str)  # task_id

    PROJECT_BAND = 16

    def __init__(self, task: Task, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task = task
        self.setFixedSize(TASK_W, TASK_H)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setAcceptDrops(True)
        self._drag_start: QPoint | None = None
        self._dragging = False
        self._refresh_style()

    def update_task(self, task: Task) -> None:
        self.task = task
        self._refresh_style()
        self.update()

    def _refresh_style(self) -> None:
        today = date.today()
        fg = font_color(self.task, today)
        bd = border_color(self.task, today) or "#CCCCCC"
        self._fg = QColor(fg)
        self._bd = QColor(bd)

    def _project_name(self) -> str:
        return (self.task.project or "").strip()

    def _project_rect(self):
        from PyQt6.QtCore import QRect

        if not self._project_name():
            return QRect()
        return QRect(4, 2, TASK_W - 8, self.PROJECT_BAND)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self._bd, 2))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRect(1, 1, TASK_W - 2, TASK_H - 2)

        project = self._project_name()
        top = 4
        if project:
            painter.setPen(
                QColor("#555555")
                if not self.task.is_hidden_from_boards()
                else self._fg
            )
            pfont = QFont("Segoe UI", 8)
            pfont.setBold(True)
            if self.task.is_cancelled():
                pfont.setStrikeOut(True)
            painter.setFont(pfont)
            painter.drawText(
                self._project_rect(),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                project,
            )
            top = self.PROJECT_BAND + 2

        tags_text = tags_to_cell(self.task.tags)
        label = f"{tags_text} {self.task.title}".strip()
        painter.setPen(self._fg)
        font = QFont("Segoe UI Emoji", 9)
        if not font.exactMatch():
            font = QFont("Segoe UI", 9)
        if self.task.is_cancelled():
            font.setStrikeOut(True)
        painter.setFont(font)
        painter.drawText(
            self.rect().adjusted(6, top, -6, -4),
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap
            ),
            label,
        )

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self._dragging = False
            self.double_clicked.emit(self.task.id)
            event.accept()

    def _find_drag_canvas(self) -> QWidget | None:
        canvas = self.parentWidget()
        while canvas is not None and not hasattr(canvas, "tag_bar"):
            canvas = canvas.parentWidget()
        return canvas

    def _lift_to_canvas(self) -> QWidget | None:
        """Снять с layout/скролла на холст и вернуть захват мыши (иначе drag обрывается)."""
        parent = self.parentWidget()
        if parent is None:
            return None
        canvas = self._find_drag_canvas()
        host = canvas or parent
        if canvas is not None and self.parentWidget() is not canvas:
            global_top = self.mapToGlobal(QPoint(0, 0))
            lay = parent.layout()
            if lay is not None:
                lay.removeWidget(self)
            self.setParent(canvas)
            self.move(canvas.mapFromGlobal(global_top))
            self.show()
            self.raise_()
            self.grabMouse()
            host = canvas
        return host

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.raise_()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.position().toPoint() - self._drag_start
        if not self._dragging and delta.manhattanLength() < 8:
            return
        first = not self._dragging
        self._dragging = True
        host = self._lift_to_canvas() if first else (self._find_drag_canvas() or self.parentWidget())
        if host is None:
            return
        # если уже на холсте (повторный drag без rebuild) — всё равно держим grab
        if first and QWidget.mouseGrabber() is not self:
            self.grabMouse()
        new_pos = self.mapToParent(event.position().toPoint()) - self._drag_start
        main = getattr(host, "main", None)
        from .layout_metrics import content_left, content_right

        on_left = bool(getattr(main, "_controls_on_left", False)) if main else False
        min_x = content_left(on_left, base=0)
        max_x = max(min_x, host.width() - content_right(on_left, base=0) - TASK_W)
        x = max(min_x, min(new_pos.x(), max_x))
        y = max(0, min(new_pos.y(), max(0, host.height() - TASK_H // 2)))
        self.move(int(x), int(y))
        self.raise_()

        global_pos = self.mapToGlobal(self.rect().center())
        bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height() - 2))
        tag_key = None
        if hasattr(host, "tag_at_global"):
            tag_key = host.tag_at_global(global_pos) or host.tag_at_global(bottom)
            if hasattr(host, "set_tag_highlight"):
                host.set_tag_highlight(tag_key)
        else:
            bar = host.property("tag_bar") if host else None
            if bar is not None:
                tag_key = bar.tag_at_global(global_pos) or bar.tag_at_global(bottom)
                bar.set_highlight(tag_key)
        if main is not None:
            action_key = main.action_at_global(global_pos) or main.action_at_global(bottom)
            main.set_action_highlight(action_key)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if self._dragging:
            global_pos = self.mapToGlobal(self.rect().center())
            bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height() - 2))
            tag_key = None
            action_key = None
            host = self._find_drag_canvas() or self.parentWidget()
            main = getattr(host, "main", None) if host else None
            if host is not None and hasattr(host, "tag_at_global"):
                tag_key = host.tag_at_global(global_pos) or host.tag_at_global(bottom)
                if hasattr(host, "set_tag_highlight"):
                    host.set_tag_highlight(None)
            else:
                bar = host.property("tag_bar") if host else None
                if bar is not None:
                    tag_key = bar.tag_at_global(global_pos) or bar.tag_at_global(bottom)
                    bar.set_highlight(None)
            if main is not None:
                action_key = main.action_at_global(global_pos) or main.action_at_global(bottom)
                main.set_action_highlight(None)
            key = tag_key or action_key
            if key:
                self.dropped_on_tag.emit(self.task.id, key)
            else:
                screen_id = getattr(host, "screen_id", None)
                if host is not None and hasattr(host, "handle_task_drop_position") and screen_id in (
                    "triage",
                    "day_tasks",
                ):
                    pos_on_canvas = self.mapTo(host, QPoint(0, 0))
                    host.handle_task_drop_position(
                        self.task.id, float(pos_on_canvas.x()), float(pos_on_canvas.y())
                    )
                elif host is not None and hasattr(host, "tag_bar") and screen_id == "urgency":
                    self.moved.emit(self.task.id, float(self.x()), float(self.y()))
                elif main is not None:
                    main.reload_boards()
        else:
            # клик без перетаскивания – возможно по проекту
            project = self._project_name()
            if project and self._project_rect().contains(event.position().toPoint()):
                self.project_clicked.emit(project)
            else:
                self.clicked.emit(self.task.id)
        self._drag_start = None
        self._dragging = False

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_TAG):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(MIME_TAG):
            event.ignore()
            return
        key = bytes(event.mimeData().data(MIME_TAG)).decode("utf-8")
        if key:
            self.tag_dropped.emit(self.task.id, key)
            event.acceptProposedAction()
        else:
            event.ignore()

    def start_external_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(self.task.id)
        mime.setData("application/x-tanion-task", self.task.id.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


class TagCircle(QWidget):
    clicked = pyqtSignal(str)  # tag_key
    tag_swapped = pyqtSignal()  # порядок изменился

    def __init__(
        self,
        tag_key: str,
        symbol: str,
        parent: QWidget | None = None,
        *,
        selectable: bool = False,
        draggable: bool = True,
        reorderable: bool = True,
        size: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.tag_key = tag_key
        self.symbol = symbol
        self.highlighted = False
        self.selected = False
        self.selectable = selectable
        self.draggable = draggable
        self.reorderable = reorderable
        self._size = size if size is not None else CIRCLE
        self.setFixedSize(self._size, self._size)
        self.setToolTip(tag_key)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(reorderable)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._press: QPoint | None = None
        self._did_drag = False

    def set_highlighted(self, value: bool) -> None:
        self.highlighted = value
        self.update()

    def set_selected(self, value: bool) -> None:
        self.selected = value
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._size
        if self.highlighted or self.selected:
            color = QColor("#FFD700")
        else:
            color = QColor("#F0F0F0")
        pen = QPen(QColor("#333333"), 2 if s >= 40 else 1)
        painter.setPen(pen)
        painter.setBrush(color)
        painter.drawEllipse(1, 1, s - 2, s - 2)
        if self.tag_key == "ПРОГД":
            painter.setPen(QColor("#1565C0"))
            font = QFont("Segoe UI", 11 if s >= 40 else 8)
            font.setBold(True)
        else:
            painter.setPen(QColor("#000000"))
            font = QFont("Segoe UI Emoji", 14 if s >= 40 else 11)
        painter.setFont(font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.symbol)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._did_drag = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self.draggable or self._press is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 10:
            return
        self._did_drag = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TAG, self.tag_key.encode("utf-8"))
        mime.setText(self.tag_key)
        drag.setMimeData(mime)
        # превью «копии» – оригинал остаётся на месте
        preview = QPixmap(self.size())
        preview.fill(Qt.GlobalColor.transparent)
        self.render(preview)
        drag.setPixmap(preview)
        drag.setHotSpot(self._press)
        drag.exec(Qt.DropAction.CopyAction)
        self._press = None

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if (
            not self._did_drag
            and self._press is not None
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit(self.tag_key)
        self._press = None
        self._did_drag = False

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_TAG):
            event.acceptProposedAction()
            self.set_highlighted(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_highlighted(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_highlighted(False)
        raw = bytes(event.mimeData().data(MIME_TAG)).decode("utf-8")
        if not raw or raw == self.tag_key:
            event.ignore()
            return
        from .tag_order import swap_tags

        swap_tags(raw, self.tag_key)
        event.acceptProposedAction()
        self.tag_swapped.emit()


class TagBar(QWidget):
    tag_clicked = pyqtSignal(str)
    order_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(CIRCLE + 12)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._inner = QWidget()
        self._layout = QHBoxLayout(self._inner)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(6)
        self.circles: dict[str, TagCircle] = {}
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll)
        self.rebuild_circles()

    def rebuild_circles(self) -> None:
        from .tag_order import ordered_tag_defs

        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.circles.clear()
        for tag in ordered_tag_defs(for_bar=True):
            circle = TagCircle(tag.key, tag.symbol, self._inner, draggable=True)
            circle.clicked.connect(self.tag_clicked.emit)
            circle.tag_swapped.connect(self._on_swap)
            self.circles[tag.key] = circle
            self._layout.addWidget(circle)
        self._layout.addStretch(1)

    def _on_swap(self) -> None:
        self.rebuild_circles()
        self.order_changed.emit()

    def tag_at_global(self, global_pos: QPoint) -> str | None:
        for key, circle in self.circles.items():
            local = circle.mapFromGlobal(global_pos)
            if circle.rect().contains(local):
                return key
        return None

    def set_highlight(self, key: str | None) -> None:
        for k, circle in self.circles.items():
            circle.set_highlighted(k == key)

    def set_active_filter(self, key: str | None) -> None:
        for k, circle in self.circles.items():
            circle.set_selected(k == key)


class CircleButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self._active = False
        self.setFixedSize(CIRCLE, CIRCLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_active(self, value: bool) -> None:
        self._active = value
        self.update()

    def setEnabled(self, value: bool) -> None:  # noqa: N802
        super().setEnabled(value)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if value
            else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        pen = QColor("#333333") if enabled else QColor("#AAAAAA")
        if not enabled:
            brush = QColor("#F0F0F0")
        elif self._active:
            brush = QColor("#BBDEFB")
        else:
            brush = QColor("#FFFFFF")
        painter.setPen(QPen(pen, 2))
        painter.setBrush(brush)
        painter.drawEllipse(1, 1, CIRCLE - 2, CIRCLE - 2)
        painter.setPen(QColor("#000000") if enabled else QColor("#999999"))
        font = QFont("Segoe UI", 16)
        painter.setFont(font)
        painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.label)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self.isEnabled()
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()


def _opt_date(widget: QDateEdit):
    qdate = widget.date()
    if qdate == widget.minimumDate():
        return None
    return date(qdate.year(), qdate.month(), qdate.day())


def _set_opt_date(widget: QDateEdit, value: date | None) -> None:
    if value is None:
        widget.setDate(widget.minimumDate())
    else:
        widget.setDate(QDate(value.year, value.month, value.day))


def _dialog_default_size(
    dialog: QDialog, parent: QWidget | None, width: int, height: int
) -> None:
    """Стартовый размер ≤ окно приложения; ресайз Windows не блокируем."""
    host = parent.window() if parent is not None else None
    max_w = (host.width() - 24) if host is not None and host.width() > 0 else width
    max_w = max(360, max_w)
    dialog.resize(min(width, max_w), height)
    dialog.setMinimumWidth(320)
    dialog.setMinimumHeight(280)
    screen = dialog.screen() or (
        QApplication.primaryScreen() if QApplication.instance() else None
    )
    if screen is not None:
        geo = screen.availableGeometry()
        dialog.setMaximumSize(geo.width(), geo.height())
    dialog.setSizeGripEnabled(True)


def _project_buttons_row(
    project_edit: QLineEdit, project_names: list[str] | None
) -> QWidget:
    """Кнопки проектов в горизонтальном скролле (без stretch — иначе скролл не появится)."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(False)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setFixedHeight(44)
    scroll.setMinimumWidth(0)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    inner = QWidget()
    layout = QHBoxLayout(inner)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(6)
    names = list(project_names or [])
    for name in names:
        btn = QPushButton(name)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, n=name: project_edit.setText(n))
        layout.addWidget(btn)
    inner.adjustSize()
    hint = inner.sizeHint()
    inner.setFixedSize(max(hint.width(), 1), max(hint.height(), 36))
    scroll.setWidget(inner)
    return scroll


class _ClearableDateEdit(QDateEdit):
    """Delete очищает; пустой календарь открывается на сегодня; годы 2000–2100."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setMinimumDate(QDate(2000, 1, 1))
        self.setMaximumDate(QDate(2100, 12, 31))
        self.setSpecialValueText("–")
        cal = self.calendarWidget()
        if cal is not None:
            cal.setMinimumDate(QDate(2000, 1, 1))
            cal.setMaximumDate(QDate(2100, 12, 31))
            cal.setGridVisible(True)
            cal.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.calendarWidget() and event.type() == QEvent.Type.Show:
            # Жёстко держим диапазон — иначе стрелки года упираются в «сегодня»
            obj.setMinimumDate(QDate(2000, 1, 1))
            obj.setMaximumDate(QDate(2100, 12, 31))
            if self.date() == self.minimumDate():
                today = QDate.currentDate()
                # Только страница календаря — НЕ setSelectedDate (синхронизирует edit → красный валидатор)
                obj.setCurrentPage(today.year(), today.month())
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            _set_opt_date(self, None)
            event.accept()
            return
        super().keyPressEvent(event)


def _make_clearable_date(value: date | None = None) -> _ClearableDateEdit:
    widget = _ClearableDateEdit()
    _set_opt_date(widget, value)
    return widget


def _make_clearable_time(value: str | None = None) -> QLineEdit:
    """Время напоминания ЧЧ:ММ; пусто = уведомление не шлётся."""
    widget = QLineEdit()
    widget.setPlaceholderText("ЧЧ:ММ")
    widget.setMaximumWidth(72)
    widget.setClearButtonEnabled(True)
    if value and str(value).strip():
        widget.setText(str(value).strip()[:5])
    return widget


def _opt_time(widget: QLineEdit) -> str | None:
    raw = widget.text().strip()
    if not raw:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return None
    h, m = int(match.group(1)), int(match.group(2))
    if h > 23 or m > 59:
        return None
    return f"{h:02d}:{m:02d}"


class TagIconsPicker(QWidget):
    """Горизонтальный ряд небольших значков всех тегов (вкл/выкл кликом)."""

    changed = pyqtSignal()

    def __init__(
        self,
        selected: list[str] | None = None,
        parent: QWidget | None = None,
        *,
        all_tasks: list[Task] | None = None,
        icon_size: int = TAG_ICON,
    ) -> None:
        super().__init__(parent)
        from .tag_order import tags_by_usage_frequency
        from .tags import canonicalize_tag_key

        self._tags = [
            canonicalize_tag_key(t) for t in (selected or []) if canonicalize_tag_key(t)
        ]
        # уникальные, порядок сохранён
        seen: set[str] = set()
        uniq: list[str] = []
        for k in self._tags:
            if k not in seen:
                seen.add(k)
                uniq.append(k)
        self._tags = uniq

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel("Теги – нажми на значок, чтобы включить/выключить:")
        layout.addWidget(hint)

        self.status = QLabel("")
        layout.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(icon_size + 16)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(0)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        inner = QWidget()
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(2, 2, 2, 2)
        inner_layout.setSpacing(4)
        self._circles: dict[str, TagCircle] = {}
        tag_defs = tags_by_usage_frequency(all_tasks or [])
        for tag in tag_defs:
            circle = TagCircle(
                tag.key,
                tag.symbol,
                inner,
                selectable=True,
                draggable=False,
                reorderable=False,
                size=icon_size,
            )
            circle.set_selected(tag.key in self._tags)
            circle.clicked.connect(self._toggle)
            self._circles[tag.key] = circle
            inner_layout.addWidget(circle)
        n = len(tag_defs)
        gap = 4
        content_w = 4 + n * icon_size + max(0, n - 1) * gap
        inner.setFixedSize(max(content_w, 1), icon_size + 4)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self._refresh_status()

    def selected_keys(self) -> list[str]:
        return list(self._tags)

    def _toggle(self, key: str) -> None:
        if key in self._tags:
            self._tags.remove(key)
        else:
            self._tags.append(key)
        circle = self._circles.get(key)
        if circle is not None:
            circle.set_selected(key in self._tags)
        self._refresh_status()
        self.changed.emit()

    def _refresh_status(self) -> None:
        self.status.setText(tags_to_cell(self._tags) or "(нет тегов)")


class _DatePairGuard:
    """Проверка due >= start только при accept (не мешает стрелкам года в календаре)."""

    def __init__(self, start: QDateEdit, due: QDateEdit) -> None:
        self.start = start
        self.due = due

    def validate_or_flash(self) -> bool:
        start_v = _opt_date(self.start)
        due_v = _opt_date(self.due)
        if start_v is not None and due_v is not None and due_v < start_v:
            prev = self.due.styleSheet()
            self.due.setStyleSheet("QDateEdit { background: #ffcccc; }")
            QTimer.singleShot(1000, lambda: self.due.setStyleSheet(prev))
            return False
        return True


class NewTaskDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        project_names: list[str] | None = None,
        *,
        default_start: date | None = None,
        default_tags: str = "",
        all_tasks: list[Task] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новая задача")
        self.setModal(True)
        _dialog_default_size(self, parent, 520, 620)
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.title_edit = QLineEdit()
        form.addRow("Название *", self.title_edit)

        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("необязательно")
        form.addRow("Проект", self.project_edit)
        form.addRow("", _project_buttons_row(self.project_edit, project_names))

        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Расширенное описание (необязательно)")
        self.description_edit.setMinimumHeight(100)
        form.addRow("Описание", self.description_edit)

        self.created = _make_clearable_date(None)
        form.addRow("Дата постановки", self.created)

        from datetime import timedelta

        start_default = default_start if default_start is not None else date.today() + timedelta(days=1)

        self.start = _make_clearable_date(start_default)
        form.addRow("Можно приступать", self.start)

        self.due = _make_clearable_date(None)
        form.addRow("Надо закончить", self.due)

        remind_default = start_default
        self.remind = _make_clearable_date(remind_default)
        self.remind_time = _make_clearable_time(None)
        remind_row = QWidget()
        remind_lay = QHBoxLayout(remind_row)
        remind_lay.setContentsMargins(0, 0, 0, 0)
        remind_lay.setSpacing(8)
        remind_lay.addWidget(self.remind, 1)
        remind_lay.addWidget(self.remind_time)
        form.addRow("Напоминание", remind_row)

        self._date_pair = _DatePairGuard(self.start, self.due)

        self.period = QComboBox()
        self.period.addItems(list(REMIND_PERIODS))
        form.addRow("Периодичность", self.period)

        self.author = QLineEdit()
        form.addRow("Кто поставил", self.author)

        root.addLayout(form)

        from .tags import parse_tags_cell

        initial_tags = parse_tags_cell(default_tags) if default_tags else []
        self.tag_picker = TagIconsPicker(
            initial_tags, self, all_tasks=all_tasks, icon_size=TAG_ICON
        )
        root.addWidget(self.tag_picker)

        hint = QLabel(
            "Обязательно только название. Остальные поля можно оставить пустыми."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _try_accept(self) -> None:
        if not self._date_pair.validate_or_flash():
            return
        self.accept()

    def result_data(self) -> dict | None:
        title = self.title_edit.text().strip()
        if not title:
            return None
        return {
            "title": title,
            "project": self.project_edit.text().strip(),
            "description": self.description_edit.toPlainText().strip(),
            "created_at": _opt_date(self.created),
            "completed_at": None,
            "start_at": _opt_date(self.start),
            "due_at": _opt_date(self.due),
            "remind_at": _opt_date(self.remind),
            "remind_time": _opt_time(self.remind_time) or "",
            "remind_period": self.period.currentText(),
            "author": self.author.text().strip(),
            "tags": self.tag_picker.selected_keys(),
        }


class EditTaskDialog(QDialog):
    """Двойной клик: название, проект, описание, теги кликом по значкам."""

    def __init__(
        self,
        task: Task,
        parent: QWidget | None = None,
        project_names: list[str] | None = None,
        all_tasks: list[Task] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Задача #{task.id}")
        self.setModal(True)
        _dialog_default_size(self, parent, 560, 640)

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.title_edit = QLineEdit(task.title)
        form.addRow("Название *", self.title_edit)

        self.project_edit = QLineEdit(task.project)
        self.project_edit.setPlaceholderText("необязательно")
        form.addRow("Проект", self.project_edit)
        form.addRow("", _project_buttons_row(self.project_edit, project_names))

        self.description_edit = QPlainTextEdit(task.description)
        self.description_edit.setPlaceholderText("Расширенное описание")
        self.description_edit.setMinimumHeight(140)
        form.addRow("Описание", self.description_edit)

        self.author = QLineEdit(task.author)
        form.addRow("Кто поставил", self.author)

        self.created = _make_clearable_date(task.created_at)
        form.addRow("Дата постановки", self.created)

        self.completed_text = QLineEdit(
            task.completed_at.isoformat() if task.completed_at else ""
        )
        self.completed_text.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Дата выполнения", self.completed_text)

        self.start = _make_clearable_date(task.start_at)
        form.addRow("Можно приступать", self.start)

        self.due = _make_clearable_date(task.due_at)
        form.addRow("Надо закончить", self.due)

        self.remind = _make_clearable_date(task.remind_at)
        self.remind_time = _make_clearable_time(getattr(task, "remind_time", "") or None)
        remind_row = QWidget()
        remind_lay = QHBoxLayout(remind_row)
        remind_lay.setContentsMargins(0, 0, 0, 0)
        remind_lay.setSpacing(8)
        remind_lay.addWidget(self.remind, 1)
        remind_lay.addWidget(self.remind_time)
        form.addRow("Напоминание", remind_row)

        self._date_pair = _DatePairGuard(self.start, self.due)

        self.period = QComboBox()
        self.period.addItems(list(REMIND_PERIODS))
        idx = self.period.findText(task.remind_period)
        if idx >= 0:
            self.period.setCurrentIndex(idx)
        form.addRow("Периодичность", self.period)

        root.addLayout(form)

        self.tag_picker = TagIconsPicker(
            list(task.tags), self, all_tasks=all_tasks, icon_size=TAG_ICON
        )
        root.addWidget(self.tag_picker)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _try_accept(self) -> None:
        if not self._date_pair.validate_or_flash():
            return
        self.accept()

    def result_data(self) -> dict | None:
        title = self.title_edit.text().strip()
        if not title:
            return None
        return {
            "title": title,
            "project": self.project_edit.text().strip(),
            "description": self.description_edit.toPlainText(),
            "author": self.author.text().strip(),
            "created_at": _opt_date(self.created),
            "completed_at": parse_date(self.completed_text.text().strip()),
            "start_at": _opt_date(self.start),
            "due_at": _opt_date(self.due),
            "remind_at": _opt_date(self.remind),
            "remind_time": _opt_time(self.remind_time) or "",
            "remind_period": self.period.currentText(),
            "tags": self.tag_picker.selected_keys(),
        }
