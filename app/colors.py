"""Цвета шрифта и рамки задач."""

from __future__ import annotations

from datetime import date

from .models import Task

GRAY = "#808080"
ORANGE = "#FF8C00"
RED = "#CC0000"
GREEN = "#228B22"
BLACK = "#000000"
BLUE = "#1E90FF"


def font_color(task: Task, today: date | None = None) -> str:
    """Приоритет: выполнена/отменена → серый → оранжевый → красный → зелёный → чёрный."""
    today = today or date.today()
    if task.is_done() or task.is_cancelled():
        return GRAY
    start_future = task.start_at is not None and task.start_at > today

    if task.is_backlog() or start_future:
        return GRAY
    if task.is_important() and task.is_urgent():
        return ORANGE
    if task.is_important():
        return RED
    early = task.start_at is None and task.due_at is not None and task.due_at > today
    if early:
        return GREEN
    return BLACK


def border_color(task: Task, today: date | None = None) -> str | None:
    """Рамка по тегам: важная+срочная → важная → актуальная → серый."""
    _ = today
    if task.is_done() or task.is_cancelled():
        return GRAY
    if task.is_important() and task.is_urgent():
        return ORANGE
    if task.is_important():
        return BLUE
    if task.is_actual():
        return GREEN
    return GRAY
