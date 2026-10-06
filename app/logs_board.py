"""Экран «Логи»: колонки по дням (сегодня → вчера → …)."""

from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .activity_log import (
    LogEntry,
    day_sections,
    format_entry_line,
    load_days,
    now_local,
)
from .layout_metrics import content_side_margins

COL_W = 280
COL_GAP = 16
TOP = 48
DAYS = 14


def _day_title(day: date, today: date) -> str:
    if day == today:
        return f"Сегодня ({day.isoformat()})"
    if day == today - timedelta(days=1):
        return f"Вчера ({day.isoformat()})"
    weekdays = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
    return f"{weekdays[day.weekday()]} {day.isoformat()}"


class DayLogColumn(QWidget):
    def __init__(
        self,
        day: date,
        entries: list[LogEntry],
        today: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumWidth(COL_W)
        self.setMaximumWidth(COL_W + 40)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(4)

        title = QLabel(_day_title(day, today))
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color:#333;")
        title.setWordWrap(True)
        layout.addWidget(title)

        completed, changed, all_entries = day_sections(entries)

        def add_section(caption: str, items: list[LogEntry], kind: str) -> None:
            head = QLabel(caption)
            head.setStyleSheet("color:#666; font-weight:600; margin-top:8px;")
            layout.addWidget(head)
            if not items:
                empty = QLabel("—")
                empty.setStyleSheet("color:#aaa;")
                layout.addWidget(empty)
                return
            for e in items:
                if kind == "changed" and e.before and e.after:
                    text = f"{e.before}\n→ {e.after}"
                elif kind == "completed":
                    text = e.after or e.before or f"#{e.task_id}"
                else:
                    text = format_entry_line(e)
                lab = QLabel(text)
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                if kind == "completed":
                    lab.setStyleSheet("color:#2E7D32; font-size:11px;")
                elif kind == "changed":
                    lab.setStyleSheet("color:#1565C0; font-size:11px;")
                else:
                    lab.setStyleSheet("color:#222; font-size:11px;")
                layout.addWidget(lab)

        add_section("Выполненные", completed, "completed")
        add_section("Изменённые", changed, "changed")
        add_section("Все действия", all_entries, "all")
        layout.addStretch(1)


class LogsCanvas(QWidget):
    def __init__(self, main_window, root=None) -> None:
        super().__init__()
        self.main = main_window
        self.root = root
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.inner = QWidget()
        self.inner_layout = QHBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(16, TOP, 16, 16)
        self.inner_layout.setSpacing(COL_GAP)
        self.scroll.setWidget(self.inner)
        outer.addWidget(self.scroll)
        self.setStyleSheet("background:#FAFAF7;")

    def _apply_side_margins(self) -> None:
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=16)
        self.inner_layout.setContentsMargins(left_m, TOP, right_m, 16)

    def rebuild(self) -> None:
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._apply_side_margins()
        today = now_local().date()
        avail_h = max(240, self.scroll.viewport().height() - TOP - 24)
        for day, entries in load_days(DAYS, today=today, root=self.root):
            col = DayLogColumn(day, entries, today, self.inner)
            col.setMinimumHeight(avail_h)
            self.inner_layout.addWidget(col, 0, Qt.AlignmentFlag.AlignTop)
        self.inner_layout.addStretch(1)

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
        painter.setPen(QColor("#666666"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(16, 28, "Логи")
