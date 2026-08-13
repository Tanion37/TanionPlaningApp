"""Сдвиг дат периодических задач при старте приложения."""

from __future__ import annotations

from datetime import date, timedelta

from .models import Task


def roll_periodic_dates(tasks: list[Task], today: date | None = None) -> bool:
    """Если период «каждый день/неделю» и даты в прошлом — выставить на текущий период.

    start_at = сегодня;
    каждый день → due_at = сегодня;
    каждую неделю → due_at = сегодня + 6.
    """
    today = today or date.today()
    changed = False
    for task in tasks:
        period = (task.remind_period or "").strip().lower()
        if period not in ("каждый день", "каждую неделю"):
            continue
        stale = False
        if task.start_at is not None and task.start_at < today:
            stale = True
        if task.due_at is not None and task.due_at < today:
            stale = True
        if not stale:
            continue
        task.start_at = today
        if period == "каждый день":
            task.due_at = today
        else:
            task.due_at = today + timedelta(days=6)
        changed = True
    return changed
