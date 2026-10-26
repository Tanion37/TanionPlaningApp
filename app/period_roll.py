"""Периодические задачи: новая копия по календарю, не сдвиг той же карточки.

Следующий старт – по сетке от первичной даты серии (start исходной карточки),
не от даты выполнения и не «завтра». День / неделя / месяц / год.
Пока в серии есть открытый экземпляр, следующий не появится.
Отмена последнего останавливает серию.
Если снова открыт неавтоспавн, лишние автокопии снимаются.
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


def next_aligned_start(primary: date, period: str, after: date) -> date:
    """Первый старт сетки от primary, строго позже after."""
    canon = canonical_period(period)
    if not canon:
        raise ValueError(period)
    d = primary
    for _ in range(20000):
        if d > after:
            return d
        d = add_period(d, canon)
    raise ValueError(f"cannot align {primary} {canon} after {after}")


def next_copy_start(primary: date, period: str, after: date) -> date:
    """Старт новой копии по сетке от первичной даты, не от выполнения."""
    return next_aligned_start(primary, period, after)


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


def _series_primary(members: list[Task], today: date) -> date:
    """Первичная дата: start исходной карточки (id == series_id)."""
    origin = None
    for task in members:
        sid = str(task.series_id or task.id).strip() or task.id
        if str(task.id) == str(sid):
            origin = task
            break
    if origin is None:
        origin = min(members, key=lambda t: (_anchor(t, today), t.id))
    return origin.start_at or _anchor(origin, today)


def _last_scheduled_start(members: list[Task], primary: date) -> date:
    starts = [t.start_at for t in members if t.start_at]
    if starts:
        return max(starts)
    return primary


def _copy_open_tags(tags: list[str], *, add_inbox: bool) -> list[str]:
    from .tags import (
        ACTUAL_TAG,
        CANCEL_ALIASES,
        CANCEL_TAG,
        DONE_ALIASES,
        DONE_TAG,
        INBOX_TAG,
        canonicalize_tag_key,
    )

    skip = DONE_ALIASES | CANCEL_ALIASES | {DONE_TAG, CANCEL_TAG, ACTUAL_TAG, "актуально"}
    out: list[str] = []
    for tag in tags:
        key = canonicalize_tag_key(tag) or tag
        if key in skip:
            continue
        if tag not in out:
            out.append(tag)
    if add_inbox and INBOX_TAG not in out:
        out.append(INBOX_TAG)
    return out


def _shift_task_start(task: Task, new_start: date) -> bool:
    old = task.start_at
    if old == new_start:
        return False
    if old and task.due_at:
        task.due_at = new_start + (task.due_at - old)
    if old and task.remind_at:
        task.remind_at = new_start + (task.remind_at - old)
    task.start_at = new_start
    return True


def _make_copy(store, src: Task, new_start: date, today: date) -> Task:
    from .xlsx_store import _next_id, _normalize_tag_list

    start_at = new_start
    if src.start_at and src.due_at:
        due_at = new_start + (src.due_at - src.start_at)
    elif src.due_at:
        due_at = new_start
    else:
        due_at = None
    if src.start_at and src.remind_at:
        remind_at = new_start + (src.remind_at - src.start_at)
    elif src.remind_at:
        remind_at = new_start
    else:
        remind_at = None
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
        tags=_normalize_tag_list(_copy_open_tags(list(src.tags), add_inbox=new_start <= today)),
        author_id=src.author_id,
        chat_id=src.chat_id,
        source="periodic",
        series_id=series_id,
    )
    store.tasks.append(task)
    return task


def _period_of(members: list[Task]) -> str | None:
    for task in members:
        canon = canonical_period(task.remind_period)
        if canon:
            return canon
    return None


def _repair_premature_copies(
    members: list[Task], primary: date, period: str, today: date
) -> bool:
    """Отложить автокопии, которые всплыли раньше сетки (вчерашняя логика «на завтра»)."""
    from .tags import clear_inbox_tag

    open_members = [t for t in members if not t.is_done() and not t.is_cancelled()]
    if not open_members:
        return False
    if any((t.source or "").strip().casefold() != "periodic" for t in open_members):
        return False
    done_members = [t for t in members if t.is_done()]
    if not done_members:
        return False
    after = max((t.start_at or _anchor(t, today) for t in done_members), default=primary)
    expected = next_aligned_start(primary, period, after)
    if expected <= today:
        return False
    changed = False
    for task in open_members:
        if (task.source or "").strip().casefold() != "periodic":
            continue
        if task.start_at is None or task.start_at <= today:
            continue
        if task.start_at >= expected:
            continue
        if _shift_task_start(task, expected):
            clear_inbox_tag(task)
            changed = True
    return changed


def spawn_periodic_copies(store, today: date | None = None) -> tuple[list[Task], bool]:
    """Создать копию по сетке от первичной даты, если серия закрыта.

    Снять лишние автокопии. Поправить слишком ранние открытые автокопии.
    Вернуть (новые копии, были ли изменения в store).
    """
    today = today or date.today()
    ensure_series_ids(store.tasks)
    by_series: dict[str, list[Task]] = {}
    for task in store.tasks:
        if not canonical_period(task.remind_period):
            continue
        sid = str(task.series_id or task.id).strip() or task.id
        by_series.setdefault(sid, []).append(task)

    stale: list[Task] = []
    for members in by_series.values():
        open_members = [t for t in members if not t.is_done() and not t.is_cancelled()]
        has_user_open = any((t.source or "").strip().casefold() != "periodic" for t in open_members)
        if not has_user_open:
            continue
        for task in open_members:
            if (task.source or "").strip().casefold() == "periodic":
                stale.append(task)
    if stale:
        stale_ids = {id(t) for t in stale}
        store.tasks[:] = [t for t in store.tasks if id(t) not in stale_ids]
        by_series = {}
        for task in store.tasks:
            if not canonical_period(task.remind_period):
                continue
            sid = str(task.series_id or task.id).strip() or task.id
            by_series.setdefault(sid, []).append(task)

    repaired = False
    for members in by_series.values():
        period = _period_of(members)
        if not period:
            continue
        primary = _series_primary(members, today)
        if _repair_premature_copies(members, primary, period, today):
            repaired = True

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
        primary = _series_primary(members, today)
        after = _last_scheduled_start(members, primary)
        new_start = next_copy_start(primary, period, after)
        created.append(_make_copy(store, latest, new_start, today))
    return created, bool(created or stale or repaired)
