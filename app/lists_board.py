"""Экран списков: колонки без границ ячеек + исполнители."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .executors_store import DEMO_EXECUTORS, ExecutorsStore
from .layout_metrics import content_side_margins
from .lists_store import ListColumn, ListItem, ListsStore

COL_W = 180
COL_GAP = 20
TOP = 48


def _pack_columns(items: list, col_count: int, load_of) -> list[list]:
    """Как pack_day_columns: в колонку с наименьшей нагрузкой."""
    if not items:
        return []
    n = max(1, min(col_count, len(items)))
    columns: list[list] = [[] for _ in range(n)]
    loads = [0] * n
    for item in items:
        i = min(range(n), key=lambda j: (loads[j], j))
        columns[i].append(item)
        loads[i] += int(load_of(item))
    return columns


class ListItemRow(QWidget):
    toggled = pyqtSignal(int)
    edit_requested = pyqtSignal(int)

    def __init__(self, index: int, item: ListItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._btn = QPushButton("☑" if item.done else "☐")
        self._btn.setFixedWidth(28)
        self._btn.setFlat(True)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setToolTip("Отметить выполненным / снять отметку")
        self._btn.clicked.connect(lambda: self.toggled.emit(self.index))
        lab = QLabel(item.text)
        lab.setWordWrap(True)
        font = QFont("Segoe UI", 10)
        font.setStrikeOut(item.done)
        lab.setFont(font)
        lab.setStyleSheet("color:#888888;" if item.done else "color:#222222;")
        lab.setToolTip("Изменить пункт")
        layout.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(lab, 1)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is self._btn:
                return super().mouseReleaseEvent(event)
            self.edit_requested.emit(self.index)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ListColumnBody(QWidget):
    """Всё под заголовком: пункты + пустое место; клик по пустому → добавить."""

    clicked = pyqtSignal()
    item_clicked = pyqtSignal(str)
    item_toggled = pyqtSignal(int)
    item_edit_requested = pyqtSignal(int)

    def __init__(
        self,
        items: list[tuple[int, ListItem]] | list[str],
        parent: QWidget | None = None,
        *,
        item_removable: bool = False,
        checkable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(72)
        self._item_removable = item_removable
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        for entry in items:
            if checkable and isinstance(entry, tuple):
                idx, item = entry
                row = ListItemRow(idx, item, self)
                row.toggled.connect(self.item_toggled.emit)
                row.edit_requested.connect(self.item_edit_requested.emit)
                layout.addWidget(row)
                continue
            text = entry if isinstance(entry, str) else entry[1].text
            lab = QLabel(f"• {text}")
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#222222; font-size:12px;")
            if item_removable:
                lab.setCursor(Qt.CursorShape.PointingHandCursor)
                lab.mouseReleaseEvent = (  # type: ignore[method-assign]
                    lambda event, value=text: self._on_item_click(event, value)
                )
            else:
                lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(lab)
        pad = QWidget()
        pad.setFixedHeight(28)
        pad.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(pad)

    def _on_item_click(self, event, text: str) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.item_clicked.emit(text)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child is not None and child is not self:
                return super().mouseReleaseEvent(event)
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ListColumnWidget(QWidget):
    """Одна колонка: заголовок сверху, под ним кликабельная область списка."""

    add_requested = pyqtSignal(str)  # canonical list name
    remove_item_requested = pyqtSignal(str, str)  # list name, item
    toggle_item_requested = pyqtSignal(str, int)
    edit_item_requested = pyqtSignal(str, int)
    hide_done_toggled = pyqtSignal(str, bool)

    def __init__(
        self,
        column: ListColumn,
        parent: QWidget | None = None,
        *,
        item_removable: bool = False,
        accent: bool = False,
        checkable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.column = column
        self.setFixedWidth(COL_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        if checkable:
            eye = QPushButton("👁")
            eye.setCheckable(True)
            eye.setChecked(not column.hide_done)
            eye.setFixedWidth(28)
            eye.setFlat(True)
            eye.setToolTip("Показать или скрыть зачёркнутые пункты")
            eye.clicked.connect(
                lambda checked=False: self.hide_done_toggled.emit(self.column.name, not checked)
            )
            head.addWidget(eye, 0, Qt.AlignmentFlag.AlignTop)

        title = QLabel(column.name)
        title.setWordWrap(True)
        font = QFont("Segoe UI", 11)
        font.setBold(True)
        title.setFont(font)
        title.setStyleSheet("color:#1565C0;" if accent else "color:#333333;")
        head.addWidget(title, 1)
        layout.addLayout(head)

        if column.aliases:
            aliases = QLabel(", ".join(column.aliases))
            aliases.setWordWrap(True)
            aliases.setStyleSheet("color:#888888; font-size:10px;")
            layout.addWidget(aliases)

        visible: list[tuple[int, ListItem]] | list[str]
        if checkable:
            visible = column.visible_items()
        else:
            visible = [item.text if isinstance(item, ListItem) else str(item) for item in column.items]
        body = ListColumnBody(
            visible,
            self,
            item_removable=item_removable,
            checkable=checkable,
        )
        body.clicked.connect(lambda: self.add_requested.emit(self.column.name))
        if item_removable:
            body.item_clicked.connect(
                lambda text: self.remove_item_requested.emit(self.column.name, text)
            )
        if checkable:
            body.item_toggled.connect(
                lambda index: self.toggle_item_requested.emit(self.column.name, index)
            )
            body.item_edit_requested.connect(
                lambda index: self.edit_item_requested.emit(self.column.name, index)
            )
        layout.addWidget(body, 1)


class ListsCanvas(QWidget):
    """Экран списков со свайпом как у досок задач."""

    def __init__(
        self,
        store: ListsStore,
        main_window,
        executors: ExecutorsStore | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.executors = executors or ExecutorsStore(store.path)
        self.main = main_window
        self.swipe_callback = None
        self._press_pos: QPoint | None = None
        self._swipe_armed = False
        self._column_widgets: list[ListColumnWidget] = []
        self._last_pack: int | None = None
        self._relayouting = False

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
        self.executors.load()
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        row = QWidget(self.inner)
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        h = QHBoxLayout(row)
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=16)
        h.setContentsMargins(left_m, TOP, right_m, 16)
        h.setSpacing(COL_GAP)
        h.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        avail_w = max(COL_W, self.scroll.viewport().width() - left_m - right_m)
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        avail_h = max(200, self.scroll.viewport().height() - TOP - 24)
        self._last_pack = col_count

        specs: list[tuple[object, int]] = []
        exec_names = (
            list(DEMO_EXECUTORS)
            if getattr(self.main, "demo_mode", False)
            else list(self.executors.names)
        )
        exec_col = ListColumn(
            name="Исполнители",
            aliases=["отдельный список"],
            items=[ListItem(text=name) for name in exec_names],
        )
        specs.append((("exec", exec_col), max(1, len(exec_names))))
        for col in self.store.columns:
            specs.append((("list", col), max(1, len(col.visible_items()))))

        packed = _pack_columns(specs, col_count, lambda spec: spec[1])
        self._column_widgets = []

        for col_specs in packed:
            col_w = QWidget(row)
            col_w.setFixedWidth(COL_W)
            col_w.setMinimumHeight(avail_h)
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(12)
            for kind_col, _load in col_specs:
                kind, col = kind_col
                if kind == "exec":
                    w = ListColumnWidget(
                        col, col_w, item_removable=True, accent=True, checkable=False
                    )
                    w.add_requested.connect(self._on_add_executor)
                    w.remove_item_requested.connect(self._on_remove_executor)
                else:
                    w = ListColumnWidget(col, col_w, checkable=True)
                    w.add_requested.connect(self._on_add)
                    w.toggle_item_requested.connect(self._on_toggle)
                    w.edit_item_requested.connect(self._on_edit)
                    w.hide_done_toggled.connect(self._on_hide_done)
                col_l.addWidget(w, 0, Qt.AlignmentFlag.AlignTop)
                self._column_widgets.append(w)
            col_l.addStretch(1)
            h.addWidget(col_w, 0, Qt.AlignmentFlag.AlignTop)
        h.addStretch(1)

        self.inner_layout.addWidget(row, 1)

    def _on_add(self, list_name: str) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        text, ok = QInputDialog.getText(
            self, f"Список «{list_name}»", "Новый пункт (несколько через ;):"
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        _col, err = self.store.add_item(list_name, text)
        if err and err != "already":
            return
        self.rebuild()

    def _on_edit(self, list_name: str, index: int) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        col = self.store.resolve(list_name)
        if col is None or index < 0 or index >= len(col.items):
            return
        current = col.items[index].text
        text, ok = QInputDialog.getText(
            self, f"Список «{list_name}»", "Пункт:", text=current
        )
        if not ok:
            return
        _col, err = self.store.set_item_text(list_name, index, text)
        if err and err not in {"already", "empty"}:
            return
        self.rebuild()

    def add_new_list(self) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        text, ok = QInputDialog.getText(
            self, "Новый список", "Имя (алиасы через запятую):"
        )
        if not ok:
            return
        _col, err = self.store.add_list(text)
        if err == "already":
            QMessageBox.information(self, "Списки", "Такой список уже есть.")
            return
        if err:
            QMessageBox.warning(self, "Списки", err)
            return
        self.rebuild()

    def _on_toggle(self, list_name: str, index: int) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        if self.store.toggle_item(list_name, index) is None:
            return
        self.rebuild()

    def _on_hide_done(self, list_name: str, hide: bool) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        if self.store.set_hide_done(list_name, hide) is None:
            return
        self.rebuild()

    def _on_add_executor(self, _list_name: str) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        text, ok = QInputDialog.getText(
            self, "Исполнители", "Новый исполнитель (несколько через ;):"
        )
        if not ok:
            return
        ok_add, err = self.executors.add(text)
        if not ok_add and err != "already":
            return
        self.rebuild()

    def _on_remove_executor(self, _list_name: str, name: str) -> None:
        if getattr(self.main, "demo_mode", False):
            return
        reply = QMessageBox.question(
            self,
            "Исполнители",
            f"Удалить «{name}» из списка исполнителей?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.executors.remove(name)
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
        if not self.isVisible() or self._relayouting:
            return
        on_left = bool(getattr(self.main, "_controls_on_left", False))
        left_m, right_m = content_side_margins(on_left, base=16)
        avail_w = max(COL_W, self.scroll.viewport().width() - left_m - right_m)
        col_count = max(1, avail_w // (COL_W + COL_GAP))
        if col_count != self._last_pack:
            self._relayouting = True
            try:
                self.rebuild()
            finally:
                self._relayouting = False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FAFAF7"))
        painter.setPen(QColor("#666666"))
        font = QFont("Segoe UI", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(16, 28, "Списки")
