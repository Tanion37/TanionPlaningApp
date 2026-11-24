"""Очередь экрана «Фокус»: Горит, Нужно, Можно, Контроль и снова Горит."""

from __future__ import annotations

import json
from datetime import date
from typing import Iterable

from .day_tasks import SECTION_GORIT, SECTION_MOZHNO, SECTION_NUZHNO
from .executors_store import is_own_executor, normalize_executor_name
from .models import Task
from .morning_review import DEFAULT_FONT_PT, clamp_font_pt

ACTION_LATER = "later"
ACTION_TO_GORIT = "to_gorit"
SECTION_CONTROL = "Контроль"

_SECTION_RANK = {
    SECTION_GORIT: 0,
    SECTION_NUZHNO: 1,
    SECTION_MOZHNO: 2,
    SECTION_CONTROL: 3,
}

# Почта входа → исполнитель, чьи задачи крутит «Фокус». Остальные экраны это не используют.
FOCUS_EMAIL_EXECUTOR: dict[str, str] = {
    "yury@nxt.ru": "Юра",
    "yury@grani.games": "Саша",
    "proboardgamedesign@yandex.ru": "Владислав",
}


def executor_for_login(email: str | None) -> str | None:
    return FOCUS_EMAIL_EXECUTOR.get((email or "").strip().casefold())


def _belongs_to_executor(task: Task, executor: str) -> bool:
    wanted = normalize_executor_name(executor)
    if wanted == normalize_executor_name("Юра"):
        return is_own_executor(task.executor)
    return normalize_executor_name(task.executor) == wanted


def settings_path():
    from .paths import app_root

    return app_root() / "data" / "focus.json"


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


def focus_section(task: Task, today: date | None = None) -> str | None:
    """Раздел круга. Пусто — задача в круг не входит.

    Горит — важная и срочная. Тег «контроль» этот раздел не меняет.
    Прочий контроль идёт после Можно. Нужно и Можно — актуальные задачи
    без контроля и без входящей.
    """
    if task.deleted or task.is_done() or task.is_cancelled() or task.is_inbox():
        return None
    if task.is_important() and task.is_urgent():
        return SECTION_GORIT
    today = today or date.today()
    if task.is_control():
        if task.start_at is not None and task.start_at > today:
            return None
        return SECTION_CONTROL
    if not task.is_actual():
        return None
    if task.is_important():
        return SECTION_NUZHNO
    return SECTION_MOZHNO


def focus_queue(tasks: Iterable[Task], *, executor: str | None, today: date | None = None) -> list[Task]:
    """Задачи этого исполнителя: Горит, Нужно, Можно, Контроль."""
    if not executor:
        return []
    today = today or date.today()
    items = [
        task
        for task in tasks
        if _belongs_to_executor(task, executor) and focus_section(task, today) is not None
    ]
    items.sort(
        key=lambda task: (
            _SECTION_RANK[focus_section(task, today)],
            (task.title or "").casefold(),
            task.id,
        )
    )
    return items


def first_gorit_index(tasks: Iterable[Task], today: date | None = None) -> int | None:
    """Позиция первой задачи раздела Горит. Пусто, если таких нет."""
    today = today or date.today()
    for index, task in enumerate(tasks):
        if focus_section(task, today) == SECTION_GORIT:
            return index
    return None


def next_index(ids: list[str], current_id: str | None) -> int:
    """Следующая позиция по кругу. Одна задача остаётся на месте."""
    if not ids:
        return 0
    if len(ids) == 1:
        return 0
    if current_id in ids:
        return (ids.index(current_id) + 1) % len(ids)
    return 0
