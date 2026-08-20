"""Логика экрана «Задачи дня»."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Iterable

from .executors_store import is_own_executor
from .models import Task
from .tags import (
    ACTUAL_TAG,
    IMPORTANT_TAG,
    INBOX_TAG,
    SYSTEM_TAG_KEYS,
    URGENT_TAG,
    canonicalize_tag_key,
    is_system_tag,
)

SECTION_GORIT = "Горит"
SECTION_NUZHNO = "Нужно"
SECTION_MOZHNO = "Можно"


def refresh_inbox_tags(tasks: Iterable[Task], today: date | None = None) -> bool:
    """Выставить входящие задачам без актуально со start<=today (или без start)."""
    today = today or date.today()
    changed = False
    for task in tasks:
        if task.is_hidden_from_boards():
            continue
        if task.is_actual() or task.is_backlog():
            continue
        if not is_own_executor(getattr(task, "executor", None)):
            continue
        start_ok = task.start_at is None or task.start_at <= today
        if not start_ok:
            continue
        if task.add_tag(INBOX_TAG):
            changed = True
    return changed


def inbox_tasks(tasks: Iterable[Task]) -> list[Task]:
    return sorted(
        [
            t
            for t in tasks
            if not t.is_hidden_from_boards()
            and t.is_inbox()
            and is_own_executor(getattr(t, "executor", None))
        ],
        key=lambda t: t.title.casefold(),
    )


def priority_section_of(task: Task) -> str | None:
    """Горит / Нужно / Можно для задач с актуально (и без входящие предпочтительно)."""
    if task.is_hidden_from_boards():
        return None
    if not is_own_executor(getattr(task, "executor", None)):
        return None
    if not task.is_actual():
        return None
    if task.is_important() and task.is_urgent():
        return SECTION_GORIT
    if task.is_important():
        return SECTION_NUZHNO
    return SECTION_MOZHNO


def priority_sections(tasks: Iterable[Task]) -> dict[str, list[Task]]:
    result = {
        SECTION_GORIT: [],
        SECTION_NUZHNO: [],
        SECTION_MOZHNO: [],
    }
    for task in tasks:
        sec = priority_section_of(task)
        if sec:
            result[sec].append(task)
    for key in result:
        result[key].sort(key=lambda t: t.title.casefold())
    return result


def apply_priority_section(task: Task, section: str) -> None:
    """Мутация тегов при drop в Горит/Нужно/Можно."""
    task.remove_tag(INBOX_TAG)
    task.add_tag(ACTUAL_TAG)
    if section == SECTION_GORIT:
        task.add_tag(IMPORTANT_TAG)
        task.add_tag(URGENT_TAG)
    elif section == SECTION_NUZHNO:
        task.add_tag(IMPORTANT_TAG)
        task.remove_tag(URGENT_TAG)
    elif section == SECTION_MOZHNO:
        task.remove_tag(IMPORTANT_TAG)
        task.remove_tag(URGENT_TAG)


def apply_inbox_to_task(task: Task, today: date | None = None) -> None:
    """Перевести задачу во входящие (кисть «Входящие»)."""
    from .tags import BACKLOG_TAG, assign_start_at, clear_actual_tag

    today = today or date.today()
    clear_actual_tag(task)
    task.remove_tag(BACKLOG_TAG)
    task.add_tag(INBOX_TAG)
    if task.start_at is None or task.start_at > today:
        assign_start_at(task, today, clear_inbox=False)


def move_actual_to_inbox(tasks: Iterable[Task]) -> int:
    """Все актуально кроме важно+срочно → входящие. Вернуть число изменённых."""
    n = 0
    for task in tasks:
        if task.is_hidden_from_boards():
            continue
        if not task.is_actual():
            continue
        if task.is_important() and task.is_urgent():
            continue
        task.remove_tag(ACTUAL_TAG)
        task.add_tag(INBOX_TAG)
        n += 1
    return n


def non_system_tags_of(task: Task) -> list[str]:
    out: list[str] = []
    for tag in task.tags:
        key = canonicalize_tag_key(tag)
        if not key or is_system_tag(key):
            continue
        if key not in out:
            out.append(key)
    return out


UNTAGGED_SECTION = "без тега"

# Явные мн.ч. для сущ. ж.р. ед.ч. (не прилагательные на -ая/-яя)
_SECTION_PLURAL_SPECIAL: dict[str, str] = {
    "переписка": "переписки",
}


def day_task_rank(task: Task) -> tuple:
    """Как Горит/Нужно/Можно: важно+срочно → важно → срочно → остальные."""
    important = task.is_important()
    urgent = task.is_urgent()
    if important and urgent:
        group = 0
    elif important:
        group = 1
    elif urgent:
        group = 2
    else:
        group = 3
    return (group, task.title.casefold())


def section_heading(tag_key: str) -> str:
    """Заголовок раздела ДЕНЬ: ж.р. ед.ч. → мн.ч."""
    if tag_key == UNTAGGED_SECTION:
        return tag_key
    if tag_key in _SECTION_PLURAL_SPECIAL:
        return _SECTION_PLURAL_SPECIAL[tag_key]
    if tag_key.endswith("ая") and len(tag_key) > 2:
        return tag_key[:-2] + "ые"
    if tag_key.endswith("яя") and len(tag_key) > 2:
        return tag_key[:-2] + "ие"
    return tag_key


def day_tag_counts(tasks: Iterable[Task]) -> list[tuple[str, list[Task]]]:
    """Несистемные теги среди актуальных + раздел «без тега», по убыванию числа."""
    by_tag: dict[str, list[Task]] = {}
    untagged: list[Task] = []
    for task in tasks:
        if task.is_hidden_from_boards() or not task.is_actual():
            continue
        if not is_own_executor(getattr(task, "executor", None)):
            continue
        tags = non_system_tags_of(task)
        if not tags:
            untagged.append(task)
            continue
        for tag in tags:
            by_tag.setdefault(tag, []).append(task)
    items = [(tag, lst) for tag, lst in by_tag.items()]
    if untagged:
        items.append((UNTAGGED_SECTION, untagged))
    items.sort(key=lambda item: (-len(item[1]), item[0].casefold()))
    for _, lst in items:
        lst.sort(key=day_task_rank)
    return items


def section_height(task_count: int, *, header_h: int = 36, task_h: int = 50, gap: int = 6) -> int:
    return header_h + task_count * (task_h + gap) + 8


def pack_day_columns(
    sections: list[tuple[str, list[Task]]],
    *,
    col_count: int,
) -> list[list[tuple[str, list[Task]]]]:
    """Разделы в колонку с наименьшей суммой задач (равномернее по нагрузке)."""
    if not sections:
        return []
    n = max(1, min(col_count, len(sections)))
    columns: list[list[tuple[str, list[Task]]]] = [[] for _ in range(n)]
    loads = [0] * n
    for sec in sections:
        _tag, tasks = sec
        # при равенстве — левее (стабильнее читать слева направо)
        i = min(range(n), key=lambda j: (loads[j], j))
        columns[i].append(sec)
        loads[i] += len(tasks)
    return columns


def rank_signature(sections: list[tuple[str, list[Task]]]) -> tuple:
    return tuple((tag, len(tasks)) for tag, tasks in sections)


def executor_sections(tasks: Iterable[Task]) -> list[tuple[str, list[Task]]]:
    """Разделы ДЕНЬ по исполнителям, кроме Юры / пустого."""
    by_name: dict[str, list[Task]] = {}
    for task in tasks:
        if task.is_hidden_from_boards():
            continue
        name = (getattr(task, "executor", None) or "").strip()
        if is_own_executor(name):
            continue
        by_name.setdefault(name, []).append(task)
    items = sorted(by_name.items(), key=lambda item: item[0].casefold())
    for _, lst in items:
        lst.sort(key=day_task_rank)
    return items
