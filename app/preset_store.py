"""Цепочки Preset: JSON в data/presets и появление следующего шага во входящих."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Task
from .tags import INBOX_TAG

SAFE_NAME = re.compile(r"[^\w\-. ()]+", re.UNICODE)


def presets_dir() -> Path:
    from .paths import app_root

    path = app_root() / "data" / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_preset_names() -> list[str]:
    names = [path.stem for path in presets_dir().glob("*.json")]
    names.sort(key=str.casefold)
    return names


def preset_path(name: str) -> Path:
    stem = SAFE_NAME.sub("", (name or "").strip()).strip(" .") or "preset"
    return presets_dir() / f"{stem}.json"


def ordered_steps(tasks: list[Task]) -> list[Task]:
    """Корень, затем связанные по after_ids. Остальные в конце."""
    by_id = {task.id: task for task in tasks}
    roots = [task for task in tasks if task.prev_id not in by_id]
    if not roots and tasks:
        roots = [tasks[0]]
    seen: set[str] = set()
    ordered: list[Task] = []

    def walk(task: Task) -> None:
        if task.id in seen:
            return
        seen.add(task.id)
        ordered.append(task)
        for child_id in task.after_ids:
            child = by_id.get(child_id)
            if child is not None:
                walk(child)

    for root in roots:
        walk(root)
    for task in tasks:
        if task.id not in seen:
            ordered.append(task)
    return ordered


def steps_from_tasks(tasks: list[Task]) -> list[dict]:
    return [_step_dict(task) for task in ordered_steps(tasks)]


def _step_dict(task: Task) -> dict:
    return {
        "title": (task.title or "").strip(),
        "role": task.role or "",
        "project": task.project or "",
        "description": task.description or "",
        "tags": list(task.tags or []),
    }


def save_preset(name: str, tasks: list[Task]) -> Path:
    path = preset_path(name)
    payload = {"tasks": steps_from_tasks(tasks)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_steps(name: str) -> list[dict]:
    path = presets_dir() / f"{Path(name).stem}.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    steps: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        tags = item.get("tags") or []
        steps.append(
            {
                "title": title,
                "role": str(item.get("role") or ""),
                "project": str(item.get("project") or ""),
                "description": str(item.get("description") or ""),
                "tags": [str(tag) for tag in tags if str(tag).strip()],
            }
        )
    return steps


def delete_preset(name: str) -> bool:
    path = presets_dir() / f"{Path(name).stem}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def rename_preset(old: str, new: str) -> str:
    src = presets_dir() / f"{Path(old).stem}.json"
    dest = preset_path(new)
    if src.exists() and src != dest:
        if dest.exists():
            dest.unlink()
        src.rename(dest)
    return dest.stem


def apply_step(task: Task, step: dict, *, preset_name: str, step_index: int) -> None:
    task.title = step["title"]
    task.role = step.get("role") or ""
    task.project = step.get("project") or ""
    task.description = step.get("description") or ""
    task.tags = list(step.get("tags") or [])
    task.preset_name = preset_name
    task.preset_step = step_index


def chain_tasks_from_steps(steps: list[dict]) -> list[Task]:
    """Линейная цепочка для окна правки: каждая следующая связана с предыдущей."""
    tasks: list[Task] = []
    previous: Task | None = None
    for index, step in enumerate(steps, start=1):
        task = Task(
            id=f"{index:03d}",
            title=step["title"],
            role=step.get("role") or "",
            project=step.get("project") or "",
            description=step.get("description") or "",
            tags=list(step.get("tags") or []),
        )
        if previous is not None:
            task.prev_id = previous.id
            previous.after_ids.append(task.id)
            previous.after_count = len(previous.after_ids)
        tasks.append(task)
        previous = task
    return tasks


def remove_with_outgoing(tasks: list[Task], task_id: str) -> None:
    by_id = {task.id: task for task in tasks}
    drop: set[str] = set()
    stack = [task_id]
    while stack:
        current = stack.pop()
        if current in drop or current not in by_id:
            continue
        drop.add(current)
        stack.extend(by_id[current].after_ids)
    kept: list[Task] = []
    for task in tasks:
        if task.id in drop:
            continue
        task.after_ids = [item for item in task.after_ids if item not in drop]
        task.after_count = len(task.after_ids)
        if task.prev_id in drop:
            task.prev_id = ""
        kept.append(task)
    tasks[:] = kept


def spawn_next_inbox(store, task: Task):
    """После выполнения шага создать следующий из Preset во входящих."""
    name = (getattr(task, "preset_name", "") or "").strip()
    step = int(getattr(task, "preset_step", -1) if getattr(task, "preset_step", -1) is not None else -1)
    if not name or step < 0:
        return None
    steps = load_steps(name)
    nxt = step + 1
    if nxt >= len(steps):
        return None
    for other in store.tasks:
        if (other.preset_name or "") == name and int(other.preset_step or -1) == nxt:
            return None
    data = steps[nxt]
    tags = [tag for tag in data.get("tags") or [] if tag != INBOX_TAG]
    tags.insert(0, INBOX_TAG)
    created = store.add_task(
        data["title"],
        persist=False,
        role=data.get("role") or "",
        project=data.get("project") or "",
        description=data.get("description") or "",
        tags=tags,
        preset_name=name,
        preset_step=nxt,
        source="preset",
    )
    return created
