"""Логика экрана «Утренний разбор»: верхняя входящая и действия кнопок."""

from __future__ import annotations

import json
from datetime import date
from typing import Iterable

from .day_tasks import (
    SECTION_GORIT,
    SECTION_MOZHNO,
    SECTION_NUZHNO,
    apply_executor_assignment,
    apply_priority_section,
    inbox_tasks,
)
from .models import Task
from .sorting import apply_backlog_deferral, apply_month_shift, apply_task_to_triage_column
from .tags import BACKLOG_TAG, CANCEL_TAG, DONE_TAG
from .widgets import TASK_H, TASK_W

# Текущий шрифт карточки задачи на досках — 9 pt.
# Масштаб экрана по умолчанию — 4×; кнопки крупнее масштаба, задача мельче.
BASE_TASK_FONT_PT = 9
DEFAULT_FONT_PT = BASE_TASK_FONT_PT * 4
MIN_FONT_PT = 12
MAX_FONT_PT = 72
FONT_STEP = 4
BUTTON_FONT_NUM = 5
BUTTON_FONT_DEN = 4
TASK_FONT_NUM = 1
TASK_FONT_DEN = 2

MORNING_EXECUTORS = ("Владислав", "Саша", "Лёша")

ACTION_GORIT = "gorit"
ACTION_NUZHNO = "nuzhno"
ACTION_MOZHNO = "mozhno"
ACTION_TOMORROW = "tomorrow"
ACTION_WEEK = "week"
ACTION_MONTH = "month"
ACTION_BACKLOG = "backlog"
ACTION_DONE = "done"


def executor_action(name: str) -> str:
    return f"executor:{name}"


def clamp_font_pt(pt: int) -> int:
    return max(MIN_FONT_PT, min(MAX_FONT_PT, int(pt)))


def button_font_pt(scale_pt: int) -> int:
    """Шрифт кнопок крупнее масштаба экрана."""
    return clamp_font_pt(round(clamp_font_pt(scale_pt) * BUTTON_FONT_NUM / BUTTON_FONT_DEN))


def task_font_pt(scale_pt: int) -> int:
    """Шрифт задачи мельче кнопок."""
    return max(MIN_FONT_PT, round(clamp_font_pt(scale_pt) * TASK_FONT_NUM / TASK_FONT_DEN))


def task_size_for_font(font_pt: int) -> tuple[int, int]:
    """Размер карточки пропорционален шрифту (200×50 при 9 pt)."""
    scale = max(1, int(font_pt)) / BASE_TASK_FONT_PT
    return max(1, round(TASK_W * scale)), max(1, round(TASK_H * scale))


def task_card_size(scale_pt: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Карточка не больше кнопок: шрифт задачи, затем clamp по размеру кнопки."""
    tw, th = task_size_for_font(task_font_pt(scale_pt))
    return min(tw, max(1, int(max_w))), min(th, max(1, int(max_h)))


def settings_path():
    from .paths import app_root

    return app_root() / "data" / "morning_review.json"


def load_font_pt() -> int:
    path = settings_path()
    if not path.exists():
        return DEFAULT_FONT_PT
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return clamp_font_pt(int(raw.get("font_pt", DEFAULT_FONT_PT)))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_FONT_PT


def save_font_pt(pt: int) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"font_pt": clamp_font_pt(pt)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def current_inbox_task(tasks: Iterable[Task], today: date | None = None) -> Task | None:
    items = inbox_tasks(tasks, today)
    return items[0] if items else None


def apply_morning_action(task: Task, action: str, today: date | None = None) -> None:
    today = today or date.today()
    if action == ACTION_GORIT:
        apply_priority_section(task, SECTION_GORIT)
        return
    if action == ACTION_NUZHNO:
        apply_priority_section(task, SECTION_NUZHNO)
        return
    if action == ACTION_MOZHNO:
        apply_priority_section(task, SECTION_MOZHNO)
        return
    if action == ACTION_TOMORROW:
        apply_task_to_triage_column(task, "ЗАВТРА", today)
        return
    if action == ACTION_WEEK:
        apply_task_to_triage_column(task, "НЕДЕЛЯ", today)
        return
    if action == ACTION_MONTH:
        apply_month_shift(task, today)
        return
    if action == ACTION_BACKLOG:
        task.add_tag(BACKLOG_TAG)
        apply_backlog_deferral(task, today)
        return
    if action == ACTION_DONE:
        task.remove_tag(CANCEL_TAG)
        task.add_tag(DONE_TAG)
        if task.completed_at is None:
            task.completed_at = today
        return
    if action.startswith("executor:"):
        apply_executor_assignment(task, action.split(":", 1)[1])
        return
    raise ValueError(f"Неизвестное действие утреннего разбора: {action}")
