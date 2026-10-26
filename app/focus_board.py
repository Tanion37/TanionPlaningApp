"""Экран «Фокус»: тот же разбор, что утром, с крупной карточкой и кругом «Позже»."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from .focus import ACTION_LATER, focus_queue, load_font_pt, next_index, save_font_pt
from .morning_review import button_font_pt, clamp_font_pt
from .morning_review_board import MorningReviewCanvas
from .models import Task
from .morning_review import task_size_for_font


class FocusCanvas(MorningReviewCanvas):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.screen_id = "focus"
        self._font_pt = load_font_pt()
        self._cursor = 0
        self._pinned_id: str | None = None
        self.card.empty_text = "Нет задач"

        self.grid.removeWidget(self.btn_done)
        bottom = QWidget(self.inner)
        self._bottom_layout = QHBoxLayout(bottom)
        self._bottom_layout.setContentsMargins(0, 0, 0, 0)
        self._bottom_layout.addWidget(self.btn_done)
        self.btn_later = self._make_action(ACTION_LATER, "ПОЗЖЕ")
        self.btn_later.setToolTip("Показать следующую невыполненную задачу. Круг возвращается к первой.")
        self._bottom_layout.addWidget(self.btn_later)
        self.grid.addWidget(
            bottom,
            2,
            1,
            alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )
        self._apply_font()

    def _nudge_font(self, delta: int) -> None:
        self._font_pt = clamp_font_pt(self._font_pt + delta)
        save_font_pt(self._font_pt)
        self._apply_font()

    def _apply_font(self) -> None:
        super()._apply_font()
        layout = getattr(self, "_bottom_layout", None)
        if layout is not None:
            layout.setSpacing(max(8, self._font_pt // 3))

    def _task_metrics(self, max_w: int, max_h: int) -> tuple[int, int, int]:
        pt = button_font_pt(self._font_pt)
        tw, th = task_size_for_font(pt)
        return pt, max(tw, max_w * 2), max(th * 2, max_h * 2)

    def _queue(self) -> list[Task]:
        tasks = self.main.visible_tasks() if hasattr(self.main, "visible_tasks") else []
        return focus_queue(tasks)

    def shown_task(self) -> Task | None:
        items = self._queue()
        if not items:
            return None
        if self._pinned_id:
            for task in items:
                if task.id == self._pinned_id:
                    return task
        return items[self._cursor % len(items)]

    def defer_current(self) -> None:
        items = self._queue()
        ids = [task.id for task in items]
        self._cursor = next_index(ids, self._pinned_id)
        self._pinned_id = ids[self._cursor] if ids else None
        self.rebuild()

    def _on_action(self, action: str) -> None:
        if action == ACTION_LATER:
            self.defer_current()
            return
        if hasattr(self.main, "apply_focus_action"):
            self.main.apply_focus_action(action)

    def rebuild(self) -> None:
        items = self._queue()
        if not items:
            self._cursor = 0
            self._pinned_id = None
        elif self._pinned_id in {task.id for task in items}:
            self._cursor = [task.id for task in items].index(self._pinned_id)
        else:
            self._cursor = self._cursor % len(items)
            self._pinned_id = items[self._cursor].id
        super().rebuild()

    def _current_task(self) -> Task | None:
        return self.shown_task()
