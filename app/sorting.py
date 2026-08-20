"""Раскладка задач по экранам / колонкам."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from .models import Task
from .tags import IMPORTANT_TAG, TAG_SORT_KEYS, URGENT_TAG, assign_start_at, clear_actual_tag, clear_inbox_tag


def add_months(d: date, months: int) -> date:
    m0 = d.month - 1 + months
    year = d.year + m0 // 12
    month = m0 % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def apply_backlog_deferral(task: Task, today: date | None = None) -> None:
    """Отложить: старт +1 месяц, без due/remind, без важная/срочная; снять входящую."""
    today = today or date.today()
    assign_start_at(task, add_months(today, 1))
    task.due_at = None
    task.remind_at = None
    task.remind_time = ""
    task.remove_tag(IMPORTANT_TAG)
    task.remove_tag(URGENT_TAG)


def _is_today_task(task: Task, today: date) -> bool:
    return task.due_at == today


def _is_overdue(task: Task, today: date) -> bool:
    if task.is_backlog() or task.is_hidden_from_boards():
        return False
    return task.due_at is not None and task.due_at < today


def _is_this_week(task: Task, today: date) -> bool:
    end = today + timedelta(days=7)
    if task.due_at is not None and today < task.due_at <= end:
        return True
    if task.start_at is not None and today < task.start_at <= end:
        return True
    return False


def _urgency_rank(task: Task) -> tuple:
    """Меньше = выше в колонке просроченных (срочные первые)."""
    urgent = 0 if task.is_urgent() else 1
    due = task.due_at.toordinal() if task.due_at else 10**9
    return (urgent, due, task.title.lower())


def _priority_rank(task: Task) -> tuple:
    """Важность → срочность → быстрая (меньше = выше)."""
    return (
        0 if task.is_important() else 1,
        0 if task.is_urgent() else 1,
        0 if task.is_fast() else 1,
        task.title.casefold(),
    )


def _gorit_rank(task: Task) -> tuple:
    """важно+срочно → важно → срочно → остальные."""
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


def active_tasks(tasks: list[Task]) -> list[Task]:
    """Без выполненных и отменённых."""
    return [t for t in tasks if not t.is_hidden_from_boards()]


def screen_urgency(tasks: list[Task], today: date | None = None) -> list[tuple[str, list[Task]]]:
    """Колонки: просроченные | сегодня | неделя | прочие | беклог."""
    today = today or date.today()
    pool = active_tasks(tasks)

    overdue: list[Task] = []
    today_col: list[Task] = []
    week: list[Task] = []
    other: list[Task] = []
    backlog: list[Task] = []
    placed: set[str] = set()

    for task in pool:
        if task.is_backlog():
            backlog.append(task)
            placed.add(task.id)
            continue
        if _is_overdue(task, today):
            overdue.append(task)
            placed.add(task.id)

    overdue.sort(key=_urgency_rank)

    for task in pool:
        if task.id in placed:
            continue
        if _is_today_task(task, today):
            today_col.append(task)
            placed.add(task.id)

    for task in pool:
        if task.id in placed:
            continue
        if _is_this_week(task, today):
            week.append(task)
            placed.add(task.id)

    for task in pool:
        if task.id in placed:
            continue
        other.append(task)

    return [
        ("Просроченные", overdue),
        ("Сегодня", today_col),
        ("Неделя", week),
        ("Прочие", other),
        ("Бэклог", backlog),
    ]


def screen_triage(tasks: list[Task], today: date | None = None) -> list[tuple[str, list[Task]]]:
    """ГОРИТ | ДЕЛАЕМ | ЗАВТРА | НЕДЕЛЯ | ТУМАН ВОЙНЫ (задача только в первой колонке)."""
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)
    pool = active_tasks(tasks)
    placed: set[str] = set()

    def _start_ok_for_hot(task: Task) -> bool:
        return task.start_at is None or task.start_at <= today

    gorit: list[Task] = []
    for task in pool:
        if _is_today_task(task, today) and _start_ok_for_hot(task):
            gorit.append(task)
            placed.add(task.id)
    gorit.sort(key=_gorit_rank)

    delaem: list[Task] = []
    for task in pool:
        if task.id in placed:
            continue
        if task.start_at is not None and task.start_at <= today:
            delaem.append(task)
            placed.add(task.id)
    delaem.sort(key=_priority_rank)

    zavtra: list[Task] = []
    for task in pool:
        if task.id in placed:
            continue
        if task.start_at == tomorrow:
            zavtra.append(task)
            placed.add(task.id)
    zavtra.sort(key=_priority_rank)

    nedelya: list[Task] = []
    for task in pool:
        if task.id in placed:
            continue
        if task.start_at is not None and today < task.start_at <= week_end:
            nedelya.append(task)
            placed.add(task.id)
    nedelya.sort(
        key=lambda t: (
            t.start_at.toordinal() if t.start_at else 10**9,
            *_priority_rank(t),
        )
    )

    fog_normal: list[Task] = []
    fog_backlog: list[Task] = []
    for task in pool:
        if task.id in placed:
            continue
        if task.is_backlog():
            fog_backlog.append(task)
        else:
            fog_normal.append(task)
    fog_normal.sort(key=_priority_rank)
    fog_backlog.sort(key=_priority_rank)
    fog = fog_normal + fog_backlog

    return [
        ("ГОРИТ", gorit),
        ("ДЕЛАЕМ", delaem),
        ("ЗАВТРА", zavtra),
        ("НЕДЕЛЯ", nedelya),
        ("ТУМАН ВОЙНЫ", fog),
    ]


TRIAGE_COLUMNS = ("ГОРИТ", "ДЕЛАЕМ", "ЗАВТРА", "НЕДЕЛЯ", "ТУМАН ВОЙНЫ")


def apply_task_to_triage_column(task: Task, column: str, today: date | None = None) -> None:
    """Подстроить поля задачи под колонку triage после drop."""
    today = today or date.today()
    tomorrow = today + timedelta(days=1)

    if column == "ГОРИТ":
        task.due_at = today
        if task.start_at is None or task.start_at > today:
            assign_start_at(task, today)
        else:
            clear_inbox_tag(task)
        return

    if column == "ДЕЛАЕМ":
        if task.due_at == today:
            task.due_at = None
        assign_start_at(task, today)
        return

    if column == "ЗАВТРА":
        assign_start_at(task, tomorrow)
        clear_actual_tag(task)
        if task.due_at == today:
            task.due_at = tomorrow
        return

    if column == "НЕДЕЛЯ":
        assign_start_at(task, today + timedelta(days=7))
        clear_actual_tag(task)
        if task.due_at == today:
            task.due_at = task.start_at
        return

    if column == "ТУМАН ВОЙНЫ":
        apply_backlog_deferral(task, today)
        return


def screen_tags(tasks: list[Task], today: date | None = None) -> list[tuple[str, list[Task]]]:
    _ = today
    pool = active_tasks(tasks)
    columns: list[tuple[str, list[Task]]] = []
    for key in TAG_SORT_KEYS:
        col = [t for t in pool if t.has_tag(key)]
        if col:
            columns.append((key, col))
    untagged = [
        t
        for t in pool
        if not any(t.has_tag(k) for k in TAG_SORT_KEYS)
    ]
    if untagged:
        columns.append(("без тега", untagged))
    return columns


def screen_projects(tasks: list[Task], today: date | None = None) -> list[tuple[str, list[Task]]]:
    """Колонки по проектам (регистр не разделяет), А→Я, «без проекта» в конце."""
    from .projects import canonical_project_map, project_key

    _ = today
    pool = active_tasks(tasks)
    mapping = canonical_project_map(pool)
    by_project: dict[str, list[Task]] = {}
    for task in pool:
        raw = (task.project or "").strip()
        if not raw:
            name = "без проекта"
        else:
            name = mapping.get(project_key(raw), raw)
        by_project.setdefault(name, []).append(task)

    def sort_key(name: str) -> tuple:
        if name == "без проекта":
            return (1, "")
        return (0, name.casefold())

    columns: list[tuple[str, list[Task]]] = []
    for name in sorted(by_project.keys(), key=sort_key):
        col = by_project[name]
        col.sort(key=lambda t: t.title.casefold())
        columns.append((name, col))
    return columns


def screen_backlog(tasks: list[Task], today: date | None = None) -> list[tuple[str, list[Task]]]:
    """Все незакрытые задачи с тегом бэклог."""
    _ = today
    pool = [
        t
        for t in tasks
        if t.is_backlog() and not t.is_done() and not t.is_cancelled()
    ]
    pool.sort(key=lambda t: t.title.casefold())
    return [("Бэклог", pool)]


SCREENS = (
    ("triage", "ГОРИТ / ДЕЛАЕМ", screen_triage),
    ("urgency", "По срочности", screen_urgency),
    ("tags", "По тегам", screen_tags),
    ("projects", "По проектам", screen_projects),
)
