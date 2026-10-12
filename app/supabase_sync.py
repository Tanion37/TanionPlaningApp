"""Синхронизация задач с Supabase. Файл tasks.xlsx пишет только TaskStore.save."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime

from .models import Task, format_date, parse_date
from .tags import tags_to_cell
from .xlsx_store import STORE_LOCK, TaskStore, _fill_prev_uuids, _next_id

log = logging.getLogger("tanion.supabase_sync")


def _state_path():
    from .paths import app_root

    return app_root() / "data" / "sync" / "supabase_state.json"


def _logged_in() -> bool:
    from .supa import supabase

    try:
        return supabase.auth.get_session() is not None
    except Exception:
        return False


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iso_date(value: date | None) -> str | None:
    text = format_date(value)
    return text or None


def _load_roles() -> tuple[dict[str, str], dict[str, str]]:
    from .supa import supabase

    try:
        data = supabase.table("roles").select("id,name").execute().data or []
    except Exception:
        log.warning("не удалось прочитать roles", exc_info=True)
        return {}, {}
    by_name: dict[str, str] = {}
    by_id: dict[str, str] = {}
    for row in data:
        name = str(row.get("name") or "").strip()
        role_id = row.get("id")
        if not name or role_id in (None, ""):
            continue
        by_name[name] = str(role_id)
        by_id[str(role_id)] = name
    return by_name, by_id


def _root_uuid(task: Task, tasks: list[Task]) -> str:
    by_id = {item.id: item for item in tasks}
    by_uuid = {item.cloud_uuid: item for item in tasks if item.cloud_uuid}
    seen: set[str] = set()
    current = task
    while current.cloud_uuid and current.cloud_uuid not in seen:
        seen.add(current.cloud_uuid)
        parent = by_uuid.get(current.prev_uuid or "")
        if parent is None and current.prev_id:
            parent = by_id.get(current.prev_id)
        if parent is None:
            break
        current = parent
    return current.cloud_uuid or task.cloud_uuid


def to_remote(task: Task, tasks: list[Task], role_ids: dict[str, str]) -> dict:
    parent_uuid = (task.prev_uuid or "").strip()
    if not parent_uuid and task.prev_id:
        parent = next((item for item in tasks if item.id == task.prev_id), None)
        if parent is not None:
            parent_uuid = parent.cloud_uuid
    tags = tags_to_cell(task.tags)
    return {
        "id": task.cloud_uuid,
        "title": (task.title or "").strip() or "(без названия)",
        "description": _text(task.description),
        "assignee": _text(task.executor),
        "author_name": _text(task.author),
        "project": _text(task.project),
        "tags": tags or None,
        "issued_on": _iso_date(task.created_at),
        "completed_on": _iso_date(task.completed_at),
        "start_on": _iso_date(task.start_at),
        "due_on": _iso_date(task.due_at),
        "remind_on": _iso_date(task.remind_at),
        "remind_time": _text(task.remind_time),
        "repeat_rule": _text(task.remind_period),
        "status": "done" if task.is_done() else "todo",
        "deleted": bool(task.deleted),
        "role_id": role_ids.get((task.role or "").strip()),
        "parent_id": parent_uuid or None,
        "root_id": _root_uuid(task, tasks),
    }


def apply_remote(task: Task, remote: dict, role_names: dict[str, str], tasks: list[Task]) -> None:
    from .tags import parse_tags_cell

    task.title = str(remote.get("title") or task.title or "").strip() or task.title
    task.description = str(remote.get("description") or "")
    task.executor = str(remote.get("assignee") or "")
    task.author = str(remote.get("author_name") or "")
    task.project = str(remote.get("project") or "")
    if remote.get("tags") is not None:
        task.tags = parse_tags_cell(str(remote.get("tags") or ""))
    task.created_at = parse_date(remote.get("issued_on"))
    task.completed_at = parse_date(remote.get("completed_on"))
    task.start_at = parse_date(remote.get("start_on"))
    task.due_at = parse_date(remote.get("due_on"))
    task.remind_at = parse_date(remote.get("remind_on"))
    remind_time = remote.get("remind_time")
    if isinstance(remind_time, datetime):
        task.remind_time = f"{remind_time.hour:02d}:{remind_time.minute:02d}"
    elif hasattr(remind_time, "hour"):
        task.remind_time = f"{int(remind_time.hour):02d}:{int(remind_time.minute):02d}"
    else:
        task.remind_time = str(remind_time or "")[:5]
    task.remind_period = str(remote.get("repeat_rule") or "")
    role_id = remote.get("role_id")
    task.role = role_names.get(str(role_id), "") if role_id not in (None, "") else ""
    task.cloud_uuid = str(remote.get("id") or task.cloud_uuid)
    task.prev_uuid = str(remote.get("parent_id") or "")
    version = remote.get("version")
    try:
        task.cloud_version = int(version) if version not in (None, "") else None
    except (TypeError, ValueError):
        task.cloud_version = None
    task.deleted = 1 if remote.get("deleted") else 0
    task.dirty = 0
    task.conflict = 0
    if task.prev_uuid:
        parent = next((item for item in tasks if item.cloud_uuid == task.prev_uuid), None)
        if parent is not None:
            task.prev_id = parent.id


def _last_pulled_at() -> str | None:
    path = _state_path()
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("last_pulled_at")
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _set_last_pulled_at(value: str) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_pulled_at": value}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _push(store: TaskStore, role_ids: dict[str, str], role_names: dict[str, str]) -> bool:
    from .supa import supabase

    changed = False
    for task in list(store.tasks):
        if not task.dirty or task.conflict:
            continue
        if not task.cloud_uuid:
            task.cloud_uuid = str(uuid.uuid4())
        data = to_remote(task, store.tasks, role_ids)
        try:
            if not task.cloud_version:
                found = (
                    supabase.table("tasks")
                    .select("version")
                    .eq("id", task.cloud_uuid)
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if found and found[0].get("version") not in (None, ""):
                    task.cloud_version = int(found[0]["version"])
            if not task.cloud_version:
                res = supabase.table("tasks").insert(data).execute()
            else:
                res = (
                    supabase.table("tasks")
                    .update(data)
                    .eq("id", task.cloud_uuid)
                    .eq("version", int(task.cloud_version))
                    .execute()
                )
                if not res.data:
                    task.conflict = 1
                    changed = True
                    continue
            if not res.data:
                continue
            apply_remote(task, res.data[0], role_names, store.tasks)
            changed = True
        except Exception:
            log.warning("не удалось отправить задачу %s", task.id, exc_info=True)
    return changed


def _pull(store: TaskStore, role_names: dict[str, str]) -> bool:
    from .supa import supabase
    from .xlsx_store import _load_id_map, _map_uuid

    since = _last_pulled_at()
    query = supabase.table("tasks").select("*").order("updated_at")
    if since:
        query = query.gt("updated_at", since)
    remote_rows = query.execute().data or []
    by_uuid = {task.cloud_uuid: task for task in store.tasks if task.cloud_uuid}
    reverse = {cloud: local for local, cloud in _load_id_map().items()}
    changed = False
    for remote in remote_rows:
        cloud_id = str(remote.get("id") or "")
        if not cloud_id:
            continue
        local = by_uuid.get(cloud_id)
        if local is None:
            local_id = reverse.get(cloud_id, "")
            if local_id:
                local = next(
                    (
                        task
                        for task in store.tasks
                        if _map_uuid({local_id: cloud_id}, task.id) == cloud_id
                    ),
                    None,
                )
                if local is not None:
                    by_uuid[cloud_id] = local
        if local is None:
            local = Task(
                id=_next_id(store.tasks),
                title=str(remote.get("title") or ""),
                source="supabase",
            )
            store.tasks.append(local)
            by_uuid[cloud_id] = local
            apply_remote(local, remote, role_names, store.tasks)
            changed = True
        elif local.dirty or local.conflict:
            local.conflict = 1
            changed = True
        else:
            apply_remote(local, remote, role_names, store.tasks)
            changed = True
    if remote_rows:
        stamps = [str(row.get("updated_at") or "") for row in remote_rows if row.get("updated_at")]
        if stamps:
            _set_last_pulled_at(max(stamps))
    return changed


def sync_store(store: TaskStore) -> tuple[bool, list[Task]]:
    """Сначала отправка, потом получение. Сеть оборвалась — dirty остаётся на следующий раз."""
    if not _logged_in():
        return False, []
    from .xlsx_store import _apply_id_map

    with STORE_LOCK:
        try:
            _apply_id_map(store.tasks)
            _fill_prev_uuids(store.tasks)
            role_ids, role_names = _load_roles()
            changed = _push(store, role_ids, role_names)
            changed = _pull(store, role_names) or changed
        except Exception:
            log.warning("синхронизация пропущена", exc_info=True)
            return False, []
        _fill_prev_uuids(store.tasks)
        conflicts = [task for task in store.tasks if task.conflict]
        if changed or conflicts:
            store.save(track_edits=False)
        return changed, conflicts


def keep_local(store: TaskStore, task: Task) -> None:
    """Своя версия: взять свежую version из облака и отправить локальные поля заново."""
    from .supa import supabase

    with STORE_LOCK:
        if not task.cloud_uuid:
            task.cloud_uuid = str(uuid.uuid4())
        try:
            remote = (
                supabase.table("tasks").select("version").eq("id", task.cloud_uuid).execute().data
                or []
            )
        except Exception:
            log.warning("не удалось прочитать version %s", task.cloud_uuid, exc_info=True)
            return
        if remote:
            try:
                task.cloud_version = int(remote[0].get("version"))
            except (TypeError, ValueError):
                task.cloud_version = None
        task.conflict = 0
        task.dirty = 1
        role_ids, role_names = _load_roles()
        _push(store, role_ids, role_names)
        store.save(track_edits=False)


def take_remote(store: TaskStore, task: Task) -> None:
    """Чужая версия: перезаписать строку и снять dirty."""
    from .supa import supabase

    with STORE_LOCK:
        if not task.cloud_uuid:
            task.conflict = 0
            task.dirty = 0
            store.save(track_edits=False)
            return
        try:
            remote = (
                supabase.table("tasks").select("*").eq("id", task.cloud_uuid).execute().data or []
            )
        except Exception:
            log.warning("не удалось прочитать задачу %s", task.cloud_uuid, exc_info=True)
            return
        if not remote:
            return
        _, role_names = _load_roles()
        apply_remote(task, remote[0], role_names, store.tasks)
        store.save(track_edits=False)
