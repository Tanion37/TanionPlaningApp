"""Проект хранит, какой исполнитель занимает роль. Preset задаёт только сами роли."""

from __future__ import annotations

from pathlib import Path

from .models import Task
from .projects import preset_of_project, project_key, same_project
from .roles import StudioRole
from .tags import INBOX_TAG

PROJECT_LEAD = StudioRole.PROJECT_LEAD.value
ASSIGN_PREFIX = "Назначить роль «"
SHEET_NAME = "project_roles"
_HEADERS = ("проект", "роль", "исполнитель")


def assignment_title(role: str) -> str:
    return f"{ASSIGN_PREFIX}{(role or '').strip()}»"


def role_from_assignment(task: Task) -> str:
    title = (getattr(task, "title", "") or "").strip()
    if not title.startswith(ASSIGN_PREFIX) or not title.endswith("»"):
        return ""
    return title[len(ASSIGN_PREFIX) : -1].strip()


def _path(path: Path | None) -> Path:
    if path is not None:
        return path
    from .xlsx_store import default_xlsx_path

    return default_xlsx_path()


def load_assignments(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Имя проекта → {роль: исполнитель}."""
    from .xlsx_io import load_workbook_retry

    book = _path(path)
    if not book.exists():
        return {}
    try:
        wb = load_workbook_retry(book, data_only=True)
    except (OSError, ValueError):
        return {}
    if SHEET_NAME not in wb.sheetnames:
        wb.close()
        return {}
    found: dict[str, dict[str, str]] = {}
    ws = wb[SHEET_NAME]
    for index, row in enumerate(ws.iter_rows(values_only=True)):
        if index == 0:
            continue
        cells = list(row or [])
        project = str(cells[0] or "").strip() if cells else ""
        role = str(cells[1] or "").strip() if len(cells) > 1 else ""
        executor = str(cells[2] or "").strip() if len(cells) > 2 else ""
        if not project or not role or not executor:
            continue
        bucket = found.setdefault(project, {})
        bucket[role] = executor
    wb.close()
    return found


def _bucket(project: str, path: Path | None = None) -> tuple[str, dict[str, str]]:
    mapping = load_assignments(path)
    for name, roles in mapping.items():
        if same_project(name, project):
            return name, dict(roles)
    return (project or "").strip(), {}


def executor_for(project: str, role: str, path: Path | None = None) -> str:
    _name, roles = _bucket(project, path)
    return roles.get((role or "").strip(), "")


def roles_of_project(project: str, tasks: list, path: Path | None = None) -> list[str]:
    """Роли образца и уже назначенные роли этого проекта. Руководитель всегда первый."""
    ordered: list[str] = []

    def add(role: str) -> None:
        text = (role or "").strip()
        if text and text not in ordered:
            ordered.append(text)

    add(PROJECT_LEAD)
    preset = preset_of_project(tasks, project)
    if preset:
        from .preset_store import load_steps

        for step in load_steps(preset):
            add(str(step.get("role") or ""))
    for task in tasks or []:
        if same_project(getattr(task, "project", ""), project):
            add(getattr(task, "role", ""))
    _name, assigned = _bucket(project, path)
    for role in assigned:
        add(role)
    return ordered


def _write(rows: list[tuple[str, str, str]], path: Path | None = None) -> None:
    from openpyxl import Workbook

    from .xlsx_io import load_workbook_retry, save_workbook_atomic, xlsx_write_lock

    book = _path(path)
    book.parent.mkdir(parents=True, exist_ok=True)
    with xlsx_write_lock(book):
        if book.exists():
            wb = load_workbook_retry(book)
            if SHEET_NAME in wb.sheetnames:
                del wb[SHEET_NAME]
        else:
            wb = Workbook()
            active = wb.active
            active.title = "tasks"
        ws = wb.create_sheet(SHEET_NAME)
        ws.append(list(_HEADERS))
        for project, role, executor in rows:
            ws.append([project, role, executor])
        save_workbook_atomic(wb, book)


def _rows(path: Path | None = None) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for project, roles in load_assignments(path).items():
        for role, executor in roles.items():
            rows.append((project, role, executor))
    return rows


def assign_executor(project: str, role: str, executor: str, path: Path | None = None) -> None:
    project = (project or "").strip()
    role = (role or "").strip()
    executor = (executor or "").strip()
    if not project or not role or not executor:
        return
    kept = [
        (name, item_role, person)
        for name, item_role, person in _rows(path)
        if not (same_project(name, project) and item_role == role)
    ]
    display = project
    for name, _role, _person in kept:
        if same_project(name, project):
            display = name
            break
    kept.append((display, role, executor))
    _write(kept, path)


def rename_project(old: str, new: str, path: Path | None = None) -> None:
    old = (old or "").strip()
    new = (new or "").strip()
    if not old or not new or project_key(old) == project_key(new):
        return
    rows = [
        (new if same_project(name, old) else name, role, person)
        for name, role, person in _rows(path)
    ]
    _write(rows, path)


def forget_project(project: str, path: Path | None = None) -> None:
    rows = [
        (name, role, person)
        for name, role, person in _rows(path)
        if not same_project(name, project)
    ]
    _write(rows, path)


def apply_executor_to_tasks(store, project: str, role: str, executor: str) -> None:
    """Пустым задачам этой роли в проекте поставить назначенного исполнителя."""
    person = (executor or "").strip()
    role = (role or "").strip()
    if not person or not role:
        return
    for task in store.tasks:
        if getattr(task, "deleted", 0):
            continue
        if not same_project(getattr(task, "project", ""), project):
            continue
        if (getattr(task, "role", "") or "").strip() != role:
            continue
        if (getattr(task, "executor", "") or "").strip():
            continue
        task.executor = person
        if hasattr(store, "mark_changed"):
            store.mark_changed(task)


def _open_assignment(store, project: str, role: str) -> Task | None:
    title = assignment_title(role)
    for task in store.tasks:
        if getattr(task, "deleted", 0) or task.is_done() or task.is_cancelled():
            continue
        if (task.title or "").strip() != title:
            continue
        if same_project(task.project, project):
            return task
    return None


def bind_task_executor(store, task: Task, path: Path | None = None) -> list[Task]:
    """Поставить исполнителя роли. Если роли нет в проекте — задача руководителю."""
    role = (task.role or "").strip()
    project = (task.project or "").strip()
    if not role or not project:
        return []
    person = executor_for(project, role, path)
    if person:
        task.executor = person
        return []
    task.executor = ""
    if role == PROJECT_LEAD:
        return []
    lead = executor_for(project, PROJECT_LEAD, path)
    if not lead or _open_assignment(store, project, role) is not None:
        return []
    created = store.add_task(
        assignment_title(role),
        persist=False,
        executor=lead,
        role=PROJECT_LEAD,
        project=project,
        description=f"В проекте «{project}» назначьте исполнителя на роль «{role}».",
        tags=[INBOX_TAG],
        source="app",
    )
    return [created]
