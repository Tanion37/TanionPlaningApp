"""Проект хранит, какой исполнитель занимает роль. Preset задаёт только сами роли."""

from __future__ import annotations

from pathlib import Path

from .models import Task
from .projects import preset_of_project, project_key, same_project
from .roles import StudioRole
from .tags import INBOX_TAG

PROJECT_LEAD = StudioRole.PROJECT_LEAD.value
ASSIGN_PREFIX = "Назначить роль «"
ASSIGN_BOTH = "Назначить роль и исполнителя"
SHEET_NAME = "project_roles"
_HEADERS = ("проект", "роль", "исполнитель")


def assignment_title(role: str) -> str:
    return f"{ASSIGN_PREFIX}{(role or '').strip()}»"


def role_from_assignment(task: Task) -> str:
    title = (getattr(task, "title", "") or "").strip()
    if not title.startswith(ASSIGN_PREFIX) or not title.endswith("»"):
        return ""
    return title[len(ASSIGN_PREFIX) : -1].strip()


def is_role_and_executor_task(task: Task) -> bool:
    return (getattr(task, "title", "") or "").strip() == ASSIGN_BOTH


def _meta(task: Task, key: str) -> str:
    prefix = f"{key}: "
    for line in (getattr(task, "description", "") or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _set_meta(task: Task, key: str, value: str) -> None:
    prefix = f"{key}: "
    lines = [
        line
        for line in (getattr(task, "description", "") or "").splitlines()
        if not line.startswith(prefix)
    ]
    text = (value or "").strip()
    if text:
        lines.append(prefix + text)
    task.description = "\n".join(lines).strip()


def pending_role(task: Task) -> str:
    return _meta(task, "роль")


def pending_executor(task: Task) -> str:
    return _meta(task, "исполнитель")


def remember_role(task: Task, role: str) -> bool:
    role = (role or "").strip()
    if pending_role(task) == role:
        return False
    _set_meta(task, "роль", role)
    return True


def remember_executor(task: Task, executor: str) -> bool:
    executor = (executor or "").strip()
    if not executor or pending_executor(task) == executor:
        return False
    _set_meta(task, "исполнитель", executor)
    return True


def settle_assignment(store, task: Task, path: Path | None = None) -> bool:
    """Когда выбраны роль и исполнитель — записать их и сдать карточку в выполненные."""
    if not is_role_and_executor_task(task):
        return False
    role = pending_role(task)
    person = pending_executor(task)
    if not role or not person:
        return False
    from .tags import DONE_TAG

    if task.is_done() and task.has_tag(DONE_TAG):
        return False
    source = store.get(task.prev_id) if task.prev_id and hasattr(store, "get") else None
    if source is not None and not getattr(source, "deleted", 0) and not is_role_and_executor_task(source):
        source.role = role
        source.executor = person
        if hasattr(store, "mark_changed"):
            store.mark_changed(source)
    project = (task.project or (getattr(source, "project", "") if source else "") or "").strip()
    if project:
        assign_executor(project, role, person, path)
        apply_executor_to_tasks(store, project, role, person)
    from datetime import date

    from .tags import ACTUAL_TAG, CANCEL_TAG, CONTROL_TAG, INBOX_TAG

    task.remove_tag(CANCEL_TAG)
    task.remove_tag(INBOX_TAG)
    task.remove_tag(ACTUAL_TAG)
    task.remove_tag(CONTROL_TAG)
    task.add_tag(DONE_TAG)
    task.completed_at = date.today()
    if hasattr(store, "mark_changed"):
        store.mark_changed(task)
    return True


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


def _open_both_assignment(store, source: Task) -> Task | None:
    for task in store.tasks:
        if getattr(task, "deleted", 0) or task.is_done() or task.is_cancelled():
            continue
        if not is_role_and_executor_task(task):
            continue
        if (task.prev_id or "") == source.id:
            return task
    return None


def bind_task_executor(store, task: Task, path: Path | None = None) -> list[Task]:
    """Поставить исполнителя роли. Если роли нет — руководитель назначает роль и исполнителя."""
    if is_role_and_executor_task(task) or role_from_assignment(task):
        return []
    role = (task.role or "").strip()
    project = (task.project or "").strip()
    if not project:
        return []
    if not role:
        lead = executor_for(project, PROJECT_LEAD, path)
        if not lead or _open_both_assignment(store, task) is not None:
            return []
        created = store.add_task(
            ASSIGN_BOTH,
            persist=False,
            executor=lead,
            role=PROJECT_LEAD,
            project=project,
            description=f"У задачи «{task.title}» в проекте «{project}» не выбраны роль и исполнитель.",
            tags=[INBOX_TAG],
            prev_id=task.id,
            source="app",
        )
        return [created]
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
