"""Экран списков: колонки без границ ячеек."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .layout_metrics import content_side_margins
from .lists_store import ListColumn, ListsStore

COL_W = 160
COL_GAP = 20
TOP = 48


class ListColumnBody(QWidget):
    """Всё под заголовком: пункты + пустое место; любой клик → добавить."""

    clicked = pyqtSignal()

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        for item in items:
            lab = QLabel(f"• {item}")
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#222222; font-size:12px;")
            lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(lab)
        layout.addStretch(1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ListColumnWidget(QWidget):
    """Одна колонка: заголовок сверху, под ним кликабельная область списка."""

    add_requested = pyqtSignal(str)

    def __init__(self, column: ListColumn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.column = column
        self.setMinimumWidth(COL_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        title = QLabel(column.name)
        title.setWordWrap(True)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color:#333333;")
        layout.addWidget(title)

        if column.aliases:
            aliases = QLabel(", ".join(column.aliases))
            aliases.setWordWrap(True)
            aliases.setStyleSheet("color:#888888; font-size:10px;")
            layout.addWidget(aliases)

        body = ListColumnBody(column.items, self)
        body.clicked.connect(lambda: self.add_requested.emit(self.column.name))
        layout.addWidget(body, 1)


class ListsCanvas(QWidget):
    """Экран списков со свайпом как у досок задач."""

    def __init__(self, store: ListsStore, main_window) -> None:
        super().__init__()
        self.store = store
        self.main = main_window
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False
        self._column_widgets: list[ListColumnWidget] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.inner = QWidget()
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll)

        self.setStyleSheet("background:#FAFAF7;")

    def rebuild(self) -> None:
        self.store.load()
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        row = QWidget(self.inner)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        h = QHBoxLayout(row)
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=16)
        h.setContentsMargins(left_m, TOP, right_m, 16)
        h.setSpacing(COL_GAP)
        h.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        avail_h = max(200, self.scroll.viewport().height() - TOP - 24)

        self._column_widgets = []
        for col in self.store.columns:
            w = ListColumnWidget(col, row)
            w.setFixedWidth(COL_W)
            w.setMinimumHeight(avail_h)
            w.add_requested.connect(self._on_add)
            h.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
            self._column_widgets.append(w)
        h.addStretch(1)

        self.inner_layout.addWidget(row, 1)

    def _on_add(self, list_name: str) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        text, ok = QInputDialog.getText(self, f"Список «{list_name}»", "Новый пункт:")
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        _col, err = self.store.add_item(list_name, text)
        if err and err != "already":
            return
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
            and self.swipe_callback is not None
        ):
            delta = event.position().toPoint().x() - self._press_pos.x()
            if abs(delta) > 80:
                self.swipe_callback(-1 if delta < 0 else 1)
        self._press_pos = None
        self._swipe_armed = False
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        avail_h = max(200, self.scroll.viewport().height() - TOP - 24)
        for w in self._column_widgets:
            w.setMinimumHeight(avail_h)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FAFAF7"))
        painter.setPen(QColor("#666666"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(16, 28, "Списки")
