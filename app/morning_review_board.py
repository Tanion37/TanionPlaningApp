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
    clamp_font_pt,
    current_inbox_task,
    executor_action,
    load_font_pt,
    save_font_pt,
    task_size_for_font,
)
from .tags import ACTUAL_TAG, DONE_TAG, IMPORTANT_TAG, URGENT_TAG, display_symbol


class MorningButton(QPushButton):
    """Прямоугольная кнопка, размер которой задаёт шрифт экрана."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

    def apply_font(self, pt: int) -> None:
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
        self._fg = QColor("#000000")
        self._bd = QColor("#CCCCCC")

    def set_font_pt(self, pt: int) -> None:
        self._font_pt = pt
        self._tw, self._th = task_size_for_font(pt)
        self.setFixedSize(self._tw, self._th)
        self._refresh_style()
        self.update()

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
        painter.drawText(
            self.rect().adjusted(8, top, -8, -6),
            int(
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap
            ),
            self.task.title,
        )

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.task is not None:
            self.double_clicked.emit(self.task.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

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
        outer.addLayout(zoom_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.inner = QWidget()
        self.inner.mousePressEvent = self._host_press  # type: ignore[method-assign]
        self.inner.mouseReleaseEvent = self._host_release  # type: ignore[method-assign]
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(12, 4, 12, 12)
        self.scroll.setWidget(self.inner)
        outer.addWidget(self.scroll, 1)

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
        self.grid.addWidget(top, 0, 1, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.card = MorningTaskCard(self.inner)
        self.card.double_clicked.connect(self._on_card_double)
        self.grid.addWidget(self.card, 1, 1, alignment=Qt.AlignmentFlag.AlignHCenter)

        left = QWidget()
        self._left_layout = QVBoxLayout(left)
        self._left_layout.setContentsMargins(0, 0, 0, 0)
        for name in MORNING_EXECUTORS:
            self._left_layout.addWidget(self._make_action(executor_action(name), name))
        self._left_layout.addStretch(1)
        self.grid.addWidget(left, 2, 0, 4, 1, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.btn_done = self._make_action(ACTION_DONE, f"ВЫПОЛНЕНА {done}")
        self.grid.addWidget(self.btn_done, 2, 1, alignment=Qt.AlignmentFlag.AlignHCenter)

        right = QWidget()
        self._right_layout = QVBoxLayout(right)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.addWidget(self._make_action(ACTION_TOMORROW, "ЗАВТРА"))
        self._right_layout.addWidget(self._make_action(ACTION_WEEK, "НЕДЕЛЯ"))
        self._right_layout.addWidget(self._make_action(ACTION_MONTH, "МЕСЯЦ"))
        self._right_layout.addWidget(self._make_action(ACTION_BACKLOG, "БЕКЛОГ"))
        self._right_layout.addStretch(1)
        self.grid.addWidget(right, 2, 2, 4, 1, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 0)
        self.grid.setColumnStretch(2, 1)
        self.grid.setRowStretch(3, 1)

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
        self.card.set_font_pt(self._font_pt)
        for btn in self._buttons.values():
            btn.apply_font(self._font_pt)
        self.btn_minus.setEnabled(self._font_pt > MIN_FONT_PT)
        self.btn_plus.setEnabled(self._font_pt < MAX_FONT_PT)

    def _on_action(self, action: str) -> None:
        if hasattr(self.main, "apply_morning_review_action"):
            self.main.apply_morning_review_action(action)

    def _on_card_double(self, task_id: str) -> None:
        if hasattr(self.main, "edit_task"):
            self.main.edit_task(task_id)

    def rebuild(self) -> None:
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=8)
        self.layout().setContentsMargins(left_m, 8, right_m, 8)
        tasks = self.main.visible_tasks() if hasattr(self.main, "visible_tasks") else []
        task = current_inbox_task(tasks)
        self.card.set_task(task)
        enabled = task is not None
        for btn in self._buttons.values():
            btn.setEnabled(enabled)
        self._apply_font()

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
