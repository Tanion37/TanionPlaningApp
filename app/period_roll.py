"""Периодические задачи: новая копия по календарю, не сдвиг той же карточки.

Вариант C: следующая появляется, только если в серии нет открытой копии
и календарный слот уже наступил (или покрывает сегодня).
Последний отменённый экземпляр останавливает серию.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from .models import Task

PERIOD_DAY = "каждый день"
PERIOD_WEEK = "каждую неделю"
PERIOD_MONTH = "каждый месяц"
PERIOD_YEAR = "каждый год"

KNOWN_PERIODS = frozenset({PERIOD_DAY, PERIOD_WEEK, PERIOD_MONTH, PERIOD_YEAR})


def canonical_period(value: str | None) -> str | None:
    text = (value or "").strip().casefold().replace("ё", "е")
    if text in KNOWN_PERIODS:
        return text
    return None


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def add_years(d: date, years: int) -> date:
    year = d.year + years
    try:
        return date(year, d.month, d.day)
    except ValueError:
        last = calendar.monthrange(year, d.month)[1]
        return date(year, d.month, last)


def add_period(d: date, period: str) -> date:
    if period == PERIOD_DAY:
        return d + timedelta(days=1)
    if period == PERIOD_WEEK:
        return d + timedelta(weeks=1)
    if period == PERIOD_MONTH:
        return add_months(d, 1)
    if period == PERIOD_YEAR:
        return add_years(d, 1)
    raise ValueError(period)


def next_occurrence_start(anchor: date, period: str, today: date) -> date | None:
    """Старт текущего календарного слота, если он уже наступил; иначе None."""
    nxt = add_period(anchor, period)
    for _ in range(4000):
        nxt2 = add_period(nxt, period)
        if nxt2 <= today:
            nxt = nxt2
            continue
        break
    if nxt <= today:
        return nxt
    return None


def ensure_task_series(task: Task) -> bool:
    """Если задана периодичность – закрепить series_id (свой id, если пусто)."""
    if not canonical_period(task.remind_period):
        return False
    sid = str(getattr(task, "series_id", "") or "").strip()
    if sid:
        if task.series_id != sid:
            task.series_id = sid
            return True
        return False
    if not task.id:
        return False
    task.series_id = task.id
    return True


def ensure_series_ids(tasks: list[Task]) -> bool:
    changed = False
    for task in tasks:
        if ensure_task_series(task):
            changed = True
    return changed


def _anchor(task: Task, today: date) -> date:
    return (
        task.start_at
        or task.due_at
        or task.remind_at
        or task.created_at
        or task.completed_at
        or today
    )


def _copy_open_tags(tags: list[str]) -> list[str]:
    from .tags import (
        CANCEL_ALIASES,
        CANCEL_TAG,
        DONE_ALIASES,
        DONE_TAG,
        canonicalize_tag_key,
    )

    out: list[str] = []
    for tag in tags:
        key = canonicalize_tag_key(tag) or tag
        if key in DONE_ALIASES or key in CANCEL_ALIASES:
            continue
        if key in {DONE_TAG, CANCEL_TAG}:
            continue
        if tag not in out:
            out.append(tag)
    return out


def _make_copy(store, src: Task, new_start: date, today: date) -> Task:
    from .xlsx_store import _next_id, _normalize_tag_list

    anchor = _anchor(src, today)
    delta = new_start - anchor
    start_at = src.start_at + delta if src.start_at else None
    due_at = src.due_at + delta if src.due_at else None
    remind_at = src.remind_at + delta if src.remind_at else None
    if start_at is None and due_at is None and remind_at is None:
        start_at = new_start
    series_id = str(src.series_id or src.id).strip() or src.id
    task = Task(
        id=_next_id(store.tasks),
        title=src.title,
        created_at=today,
        completed_at=None,
        start_at=start_at,
        due_at=due_at,
        remind_at=remind_at,
        remind_time=src.remind_time or "",
        remind_period=src.remind_period,
        author=src.author,
        executor=src.executor,
        project=src.project,
        description=src.description,
        tags=_normalize_tag_list(_copy_open_tags(list(src.tags))),
        author_id=src.author_id,
        chat_id=src.chat_id,
        source="periodic",
        series_id=series_id,
    )
    store.tasks.append(task)
    return task


def spawn_periodic_copies(store, today: date | None = None) -> list[Task]:
    """Создать просроченные по календарю копии. Не трогает открытые серии."""
    today = today or date.today()
    ensure_series_ids(store.tasks)
    by_series: dict[str, list[Task]] = {}
    for task in store.tasks:
        if not canonical_period(task.remind_period):
            continue
        sid = str(task.series_id or task.id).strip() or task.id
        by_series.setdefault(sid, []).append(task)

    created: list[Task] = []
    for members in by_series.values():
        if any(not t.is_done() and not t.is_cancelled() for t in members):
            continue
        latest = max(members, key=lambda t: (_anchor(t, today), t.id))
        if latest.is_cancelled() or not latest.is_done():
            continue
        period = canonical_period(latest.remind_period)
        if not period:
            continue
        nxt = next_occurrence_start(_anchor(latest, today), period, today)
        if nxt is None:
            continue
        created.append(_make_copy(store, latest, nxt, today))
    return created
