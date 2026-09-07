"""Экран «Утренний разбор»: одна входящая и крупные кнопки вокруг."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .colors import border_color, font_color
from .layout_metrics import content_side_margins
from .models import Task
from .morning_review import (
    ACTION_BACKLOG,
    ACTION_DONE,
    ACTION_GORIT,
    ACTION_MONTH,
    ACTION_MOZHNO,
    ACTION_NUZHNO,
    ACTION_TOMORROW,
    ACTION_WEEK,
    FONT_STEP,
    MAX_FONT_PT,
    MIN_FONT_PT,
    MORNING_EXECUTORS,
    button_font_pt,
    clamp_font_pt,
    current_inbox_task,
    executor_action,
    load_font_pt,
    save_font_pt,
    task_card_size,
    task_font_pt,
    task_size_for_font,
)
from .tags import ACTUAL_TAG, DONE_TAG, IMPORTANT_TAG, URGENT_TAG, display_symbol, tags_to_cell
from .widgets import TagBar


class MorningButton(QPushButton):
    """Прямоугольная кнопка, размер которой задаёт шрифт экрана."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(True)
        self._drop_on = False
        self._pt = 36

    def set_drop_highlight(self, on: bool) -> None:
        if on == self._drop_on:
            return
        self._drop_on = on
        self._apply_chrome()

    def apply_font(self, pt: int) -> None:
        self._pt = pt
        font = QFont("Segoe UI Emoji", pt)
        if not font.exactMatch():
            font = QFont("Segoe UI", pt)
        font.setBold(True)
        self.setFont(font)
        fm = QFontMetrics(font)
        pad_y = max(8, pt // 3)
        pad_x = max(16, pt)
        w = fm.horizontalAdvance(self.text()) + pad_x * 2
        h = fm.height() + pad_y * 2
        self.setMinimumSize(w, h)
        self._apply_chrome()

    def _apply_chrome(self) -> None:
        pad_y = max(8, self._pt // 3)
        pad_x = max(16, self._pt)
        if self._drop_on:
            self.setStyleSheet(
                "QPushButton {"
                " background:#FFF8E1; color:#E65100; border:3px solid #FF8C00; border-radius:4px;"
                f" padding:{pad_y}px {pad_x}px;"
                " }"
            )
            return
        self.setStyleSheet(
            "QPushButton {"
            " background:#FFFFFF; color:#222; border:2px solid #555; border-radius:4px;"
            f" padding:{pad_y}px {pad_x}px;"
            " }"
            "QPushButton:hover { background:#F3F3F3; }"
            "QPushButton:pressed { background:#E8E8E8; }"
            "QPushButton:disabled { color:#999; border-color:#CCC; background:#F7F7F7; }"
        )


class MorningTaskCard(QWidget):
    double_clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task: Task | None = None
        self._font_pt = 36
        self._tw, self._th = task_size_for_font(self._font_pt)
        self.setFixedSize(self._tw, self._th)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._fg = QColor("#000000")
        self._bd = QColor("#CCCCCC")
        self._drag_start: QPoint | None = None
        self._dragging = False

    def set_metrics(self, pt: int, width: int, height: int) -> None:
        self._font_pt = pt
        self._tw = max(1, int(width))
        self._th = max(1, int(height))
        self.setFixedSize(self._tw, self._th)
        self._refresh_style()
        self.update()

    def set_font_pt(self, pt: int) -> None:
        tw, th = task_size_for_font(pt)
        self.set_metrics(pt, tw, th)

    def set_task(self, task: Task | None) -> None:
        self.task = task
        self._refresh_style()
        self.update()

    def _refresh_style(self) -> None:
        today = date.today()
        if self.task is None:
            self._fg = QColor("#888888")
            self._bd = QColor("#CCCCCC")
            return
        self._fg = QColor(font_color(self.task, today))
        self._bd = QColor(border_color(self.task, today) or "#CCCCCC")

    def _project_band(self) -> int:
        scale = self._font_pt / 9
        return max(12, round(16 * scale))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self._bd, max(2, self._font_pt // 12)))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRect(1, 1, self._tw - 2, self._th - 2)

        if self.task is None:
            painter.setPen(self._fg)
            font = QFont("Segoe UI", self._font_pt)
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(8, 8, -8, -8),
                int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                "Нет входящих",
            )
            return

        project = (self.task.project or "").strip()
        top = 4
        if project:
            band = self._project_band()
            painter.setPen(QColor("#555555"))
            pfont = QFont("Segoe UI", max(8, round(self._font_pt * 8 / 9)))
            pfont.setBold(True)
            painter.setFont(pfont)
            painter.drawText(
                4,
                2,
                self._tw - 8,
                band,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                project,
            )
            top = band + 2

        painter.setPen(self._fg)
        font = QFont("Segoe UI Emoji", self._font_pt)
        if not font.exactMatch():
            font = QFont("Segoe UI", self._font_pt)
        painter.setFont(font)
        tags_text = tags_to_cell(self.task.tags)
        label = f"{tags_text} {self.task.title}".strip()
        painter.drawText(
            self.rect().adjusted(8, top, -8, -6),
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap
            ),
            label,
        )

    def _canvas(self) -> MorningReviewCanvas | None:
        widget = self.parentWidget()
        while widget is not None:
            if getattr(widget, "screen_id", None) == "morning_review":
                return widget  # type: ignore[return-value]
            widget = widget.parentWidget()
        return None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.task is not None:
            self._drag_start = None
            self._dragging = False
            self.double_clicked.emit(self.task.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.task is not None:
            self._drag_start = event.position().toPoint()
            self._dragging = False
            self.raise_()
            event.accept()
            return
        super().mousePressEvent(event)

    def _lift_to_canvas(self) -> MorningReviewCanvas | None:
        canvas = self._canvas()
        if canvas is None or self.task is None:
            return None
        if self.parentWidget() is not canvas:
            global_top = self.mapToGlobal(QPoint(0, 0))
            if canvas.grid.indexOf(self) >= 0:
                placeholder = QWidget()
                placeholder.setFixedSize(self._tw, self._th)
                canvas.grid.removeWidget(self)
                canvas.grid.addWidget(
                    placeholder, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter
                )
                canvas._card_placeholder = placeholder
            self.setParent(canvas)
            self.move(canvas.mapFromGlobal(global_top))
            self.show()
            self.raise_()
            self.grabMouse()
            canvas._swipe_armed = False
            canvas._press_pos = None
        return canvas

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None or self.task is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.position().toPoint() - self._drag_start
        if not self._dragging and delta.manhattanLength() < 8:
            return
        first = not self._dragging
        self._dragging = True
        canvas = self._lift_to_canvas() if first else self._canvas()
        if canvas is None:
            return
        if first and QWidget.mouseGrabber() is not self:
            self.grabMouse()
        new_pos = self.mapToParent(event.position().toPoint()) - self._drag_start
        x = max(0, min(new_pos.x(), max(0, canvas.width() - self._tw)))
        y = max(0, min(new_pos.y(), max(0, canvas.height() - self._th // 2)))
        self.move(int(x), int(y))
        self.raise_()
        center = self.mapToGlobal(self.rect().center())
        bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height() - 2))
        tag = canvas.tag_at_global(center) or canvas.tag_at_global(bottom)
        action = None if tag else (
            canvas.action_at_global(center) or canvas.action_at_global(bottom)
        )
        canvas.set_drop_highlight(action)
        canvas.set_tag_highlight(tag)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        canvas = self._canvas()
        if self._dragging and canvas is not None:
            center = self.mapToGlobal(self.rect().center())
            bottom = self.mapToGlobal(QPoint(self.width() // 2, self.height() - 2))
            tag = canvas.tag_at_global(center) or canvas.tag_at_global(bottom)
            action = None if tag else (
                canvas.action_at_global(center) or canvas.action_at_global(bottom)
            )
            canvas.set_drop_highlight(None)
            canvas._restore_tag_highlight()
            self._drag_start = None
            self._dragging = False
            if tag and self.task is not None:
                canvas._on_tag_drop(self.task.id, tag)
            elif action:
                canvas._on_action(action)
            else:
                canvas._ensure_card_in_grid()
            event.accept()
            return
        self._drag_start = None
        self._dragging = False
        if self.task is not None and canvas is not None:
            canvas._on_card_click(self.task.id)
        super().mouseReleaseEvent(event)


class MorningReviewCanvas(QWidget):
    """Холст экрана Утренний разбор."""

    def __init__(self, main_window) -> None:
        super().__init__()
        self.main = main_window
        self.screen_id = "morning_review"
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False
        self._font_pt = load_font_pt()
        self._buttons: dict[str, MorningButton] = {}
        self._card_placeholder: QWidget | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.content = QWidget()
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(8)

        zoom_row = QHBoxLayout()
        zoom_row.addStretch(1)
        self.btn_minus = QPushButton("−")
        self.btn_plus = QPushButton("+")
        for btn in (self.btn_minus, self.btn_plus):
            btn.setFixedSize(48, 48)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { font-size:22px; font-weight:700; background:#FFFFFF;"
                " border:2px solid #555; border-radius:4px; }"
                "QPushButton:hover { background:#F3F3F3; }"
                "QPushButton:disabled { color:#AAA; border-color:#CCC; }"
            )
        self.btn_minus.setToolTip("Мельче шрифт только на этом экране")
        self.btn_plus.setToolTip("Крупнее шрифт только на этом экране")
        self.btn_minus.clicked.connect(lambda: self._nudge_font(-FONT_STEP))
        self.btn_plus.clicked.connect(lambda: self._nudge_font(FONT_STEP))
        zoom_row.addWidget(self.btn_minus)
        zoom_row.addWidget(self.btn_plus)
        self._content_layout.addLayout(zoom_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inner = QWidget()
        self.inner.mousePressEvent = self._host_press  # type: ignore[method-assign]
        self.inner.mouseReleaseEvent = self._host_release  # type: ignore[method-assign]
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(12, 4, 12, 12)
        self.scroll.setWidget(self.inner)
        self._content_layout.addWidget(self.scroll, 1)
        outer.addWidget(self.content, 1)

        self.tag_bar = TagBar(self)
        self.tag_bar.tag_clicked.connect(self.main.on_tag_pick)
        self.tag_bar.order_changed.connect(self.main.on_tag_order_changed)
        outer.addWidget(self.tag_bar)
        self.setProperty("tag_bar", self.tag_bar)

        urgent = display_symbol(URGENT_TAG)
        important = display_symbol(IMPORTANT_TAG)
        actual = display_symbol(ACTUAL_TAG)
        done = display_symbol(DONE_TAG)

        self.btn_gorit = self._make_action(ACTION_GORIT, f"ГОРИТ {urgent}")
        self.btn_nuzhno = self._make_action(ACTION_NUZHNO, f"НУЖНО {important}")
        self.btn_mozhno = self._make_action(ACTION_MOZHNO, f"МОЖНО {actual}")
        top = QWidget()
        self._top_layout = QHBoxLayout(top)
        self._top_layout.setContentsMargins(0, 0, 0, 0)
        self._top_layout.addWidget(self.btn_gorit)
        self._top_layout.addWidget(self.btn_nuzhno)
        self._top_layout.addWidget(self.btn_mozhno)
        self.grid.addWidget(top, 0, 1, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)

        self.card = MorningTaskCard(self.inner)
        self.card.double_clicked.connect(self._on_card_double)
        self.grid.addWidget(self.card, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        left = QWidget()
        self._left_layout = QVBoxLayout(left)
        self._left_layout.setContentsMargins(0, 0, 0, 0)
        for name in MORNING_EXECUTORS:
            self._left_layout.addWidget(self._make_action(executor_action(name), name))
        self.grid.addWidget(left, 1, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.btn_done = self._make_action(ACTION_DONE, f"ВЫПОЛНЕНА {done}")
        self.grid.addWidget(self.btn_done, 2, 1, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        right = QWidget()
        self._right_layout = QVBoxLayout(right)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.addWidget(self._make_action(ACTION_TOMORROW, "ЗАВТРА"))
        self._right_layout.addWidget(self._make_action(ACTION_WEEK, "НЕДЕЛЯ"))
        self._right_layout.addWidget(self._make_action(ACTION_MONTH, "МЕСЯЦ"))
        self._right_layout.addWidget(self._make_action(ACTION_BACKLOG, "БЕКЛОГ"))
        self.grid.addWidget(right, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 0)
        self.grid.setColumnStretch(2, 1)
        self.grid.setRowStretch(0, 1)
        self.grid.setRowStretch(1, 0)
        self.grid.setRowStretch(2, 1)

        self._apply_font()

    def _make_action(self, action: str, label: str) -> MorningButton:
        btn = MorningButton(label, self.inner)
        btn.clicked.connect(lambda _=False, key=action: self._on_action(key))
        self._buttons[action] = btn
        return btn

    def _nudge_font(self, delta: int) -> None:
        self._font_pt = clamp_font_pt(self._font_pt + delta)
        save_font_pt(self._font_pt)
        self._apply_font()

    def _apply_font(self) -> None:
        gap = max(8, self._font_pt // 3)
        self.grid.setHorizontalSpacing(gap)
        self.grid.setVerticalSpacing(gap)
        self._top_layout.setSpacing(gap)
        self._left_layout.setSpacing(gap)
        self._right_layout.setSpacing(gap)
        btn_pt = button_font_pt(self._font_pt)
        for btn in self._buttons.values():
            btn.apply_font(btn_pt)
        max_w = 1
        max_h = 1
        for btn in self._buttons.values():
            hint = btn.sizeHint()
            max_w = max(max_w, hint.width())
            max_h = max(max_h, hint.height())
        tw, th = task_card_size(self._font_pt, max_w, max_h)
        self.card.set_metrics(task_font_pt(self._font_pt), tw, th)
        self.btn_minus.setEnabled(self._font_pt > MIN_FONT_PT)
        self.btn_plus.setEnabled(self._font_pt < MAX_FONT_PT)

    def _on_action(self, action: str) -> None:
        if hasattr(self.main, "apply_morning_review_action"):
            self.main.apply_morning_review_action(action)

    def _on_tag_drop(self, task_id: str, tag_key: str) -> None:
        if hasattr(self.main, "apply_action_to_task"):
            self.main.apply_action_to_task(task_id, tag_key)

    def _on_card_click(self, task_id: str) -> None:
        if hasattr(self.main, "on_task_clicked"):
            self.main.on_task_clicked(task_id)

    def tag_at_global(self, global_pos: QPoint) -> str | None:
        return self.tag_bar.tag_at_global(global_pos)

    def set_tag_highlight(self, key: str | None) -> None:
        self.tag_bar.set_highlight(key)

    def _restore_tag_highlight(self) -> None:
        pm = getattr(self.main, "paint_mode", None)
        if pm and pm[0] == "tag":
            self.set_tag_highlight(pm[1])
        else:
            self.set_tag_highlight(None)

    def action_at_global(self, global_pos: QPoint) -> str | None:
        for action, btn in self._buttons.items():
            if not btn.isVisible() or not btn.isEnabled():
                continue
            local = btn.mapFromGlobal(global_pos)
            if btn.rect().contains(local):
                return action
        return None

    def set_drop_highlight(self, action: str | None) -> None:
        for key, btn in self._buttons.items():
            btn.set_drop_highlight(key == action)

    def _ensure_card_in_grid(self) -> None:
        if self._card_placeholder is not None:
            self.grid.removeWidget(self._card_placeholder)
            self._card_placeholder.deleteLater()
            self._card_placeholder = None
        if self.grid.indexOf(self.card) < 0:
            self.grid.addWidget(self.card, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        self.card.show()

    def _on_card_double(self, task_id: str) -> None:
        if hasattr(self.main, "edit_task"):
            self.main.edit_task(task_id)

    def rebuild(self) -> None:
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=8)
        self._content_layout.setContentsMargins(left_m, 8, right_m, 0)
        tasks = self.main.visible_tasks() if hasattr(self.main, "visible_tasks") else []
        task = current_inbox_task(tasks)
        self._ensure_card_in_grid()
        self.card.set_task(task)
        enabled = task is not None
        for btn in self._buttons.values():
            btn.setEnabled(enabled)
        self._apply_font()
        self.tag_bar.rebuild_circles()
        self.tag_bar.set_active_filter(getattr(self.main, "filter_tag", None))
        self._restore_tag_highlight()

    def _host_press(self, event) -> None:  # noqa: ANN001
        self.mousePressEvent(event)

    def _host_release(self, event) -> None:  # noqa: ANN001
        self.mouseReleaseEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._swipe_armed = True
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
