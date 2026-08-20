"""Синхронизация задач с Notion: журнал изменений + суточная сверка.

Локальный xlsx — source of truth для офлайн-работы.
Notion — зеркало и шина между устройствами.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .activity_log import snapshot_dict
from .models import Task, parse_date
from .tags import tags_to_cell
from .xlsx_store import TaskStore

log = logging.getLogger("tanion.notion_sync")

TZ = timezone(timedelta(hours=3))
NOTION_VERSION = "2022-06-28"
API = "https://api.notion.com/v1"

COMPARE_FIELDS: tuple[str, ...] = (
    "title",
    "project",
    "description",
    "author",
    "executor",
    "tags",
    "created_at",
    "start_at",
    "due_at",
    "remind_at",
    "remind_time",
    "remind_period",
    "series_id",
    "completed_at",
)


def _now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def sync_dir(root: Path | None = None) -> Path:
    from .paths import app_root

    path = (root or app_root()) / "data" / "sync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_app_config() -> dict[str, Any]:
    from .paths import app_root
    from .tas_secrets import load_resolved_json

    path = app_root() / "config.json"
    if not path.exists():
        return {}
    try:
        return load_resolved_json(path)
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return {}


def save_app_config(cfg: dict[str, Any]) -> None:
    from .paths import app_root

    path = app_root() / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class NotionConfig:
    enabled: bool = False
    token: str = ""
    parent_page_id: str = ""
    database_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NotionConfig:
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled")),
            token=str(data.get("token") or "").strip(),
            parent_page_id=_normalize_id(str(data.get("parent_page_id") or "")),
            database_id=_normalize_id(str(data.get("database_id") or "")),
        )

    def ready(self) -> bool:
        return bool(self.enabled and self.token and (self.database_id or self.parent_page_id))


def _normalize_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    # URL → id
    if "notion.so" in text:
        text = text.rstrip("/").split("/")[-1].split("?")[0]
    return text.replace("-", "")


@dataclass
class SyncState:
    device_id: str = ""
    page_map: dict[str, str] = field(default_factory=dict)  # task_id → page_id
    field_times: dict[str, dict[str, str]] = field(default_factory=dict)
    last_ops_sync_at: str = ""
    last_full_reconcile_at: str = ""
    last_error: str = ""
    last_error_at: str = ""
    offline_until: str = ""
    lists_page_id: str = ""
    lists_hash: str = ""

    @classmethod
    def load(cls, root: Path | None = None) -> SyncState:
        path = sync_dir(root) / "state.json"
        if not path.exists():
            state = cls(device_id=str(uuid.uuid4()))
            state.save(root)
            return state
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = cls(device_id=str(uuid.uuid4()))
            state.save(root)
            return state
        return cls(
            device_id=str(raw.get("device_id") or uuid.uuid4()),
            page_map={str(k): str(v) for k, v in (raw.get("page_map") or {}).items()},
            field_times={
                str(tid): {str(f): str(ts) for f, ts in (fields or {}).items()}
                for tid, fields in (raw.get("field_times") or {}).items()
            },
            last_ops_sync_at=str(raw.get("last_ops_sync_at") or ""),
            last_full_reconcile_at=str(raw.get("last_full_reconcile_at") or ""),
            last_error=str(raw.get("last_error") or ""),
            last_error_at=str(raw.get("last_error_at") or ""),
            offline_until=str(raw.get("offline_until") or ""),
            lists_page_id=str(raw.get("lists_page_id") or ""),
            lists_hash=str(raw.get("lists_hash") or ""),
        )

    def save(self, root: Path | None = None) -> None:
        path = sync_dir(root) / "state.json"
        payload = {
            "device_id": self.device_id,
            "page_map": self.page_map,
            "field_times": self.field_times,
            "last_ops_sync_at": self.last_ops_sync_at,
            "last_full_reconcile_at": self.last_full_reconcile_at,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "offline_until": self.offline_until,
            "lists_page_id": self.lists_page_id,
            "lists_hash": self.lists_hash,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ChangeLog:
    """Append-only очередь локальных изменений для push в Notion."""

    def __init__(self, root: Path | None = None) -> None:
        self.path = sync_dir(root) / "pending_ops.jsonl"

    def append(
        self,
        *,
        action: str,
        task_id: str,
        snapshot: dict[str, Any] | None,
        changed_fields: list[str] | None = None,
        device_id: str = "",
    ) -> None:
        op = {
            "op_id": str(uuid.uuid4()),
            "ts": _now_iso(),
            "device_id": device_id,
            "action": action,
            "task_id": task_id,
            "snapshot": snapshot,
            "changed_fields": changed_fields or list(COMPARE_FIELDS),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(op, ensure_ascii=False) + "\n")

    def load_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        ops: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ops.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return ops

    def replace_all(self, ops: list[dict[str, Any]]) -> None:
        if not ops:
            if self.path.exists():
                self.path.unlink()
            return
        text = "\n".join(json.dumps(op, ensure_ascii=False) for op in ops) + "\n"
        self.path.write_text(text, encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class NotionApiError(Exception):
    def __init__(self, message: str, *, offline: bool = False) -> None:
        super().__init__(message)
        self.offline = offline


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            f"{API}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise NotionApiError(f"HTTP {exc.code}: {detail[:500]}") from exc
        except URLError as exc:
            raise NotionApiError(str(exc.reason or exc), offline=True) from exc
        except TimeoutError as exc:
            raise NotionApiError("timeout", offline=True) from exc

    def ensure_series_property(self, database_id: str) -> None:
        db = _dash_id(_normalize_id(database_id))
        info = self.request("GET", f"/databases/{db}")
        props = info.get("properties") or {}
        if "Series" in props:
            return
        self.request(
            "PATCH",
            f"/databases/{db}",
            {"properties": {"Series": {"rich_text": {}}}},
        )

    def create_database(self, parent_page_id: str) -> str:
        parent_id = _normalize_id(parent_page_id)
        # Notion accepts UUID with dashes
        dashed = _dash_id(parent_id)
        body = {
            "parent": {"type": "page_id", "page_id": dashed},
            "title": [{"type": "text", "text": {"content": "TanionPlaning Tasks"}}],
            "properties": {
                "Name": {"title": {}},
                "Task ID": {"rich_text": {}},
                "Project": {"rich_text": {}},
                "Description": {"rich_text": {}},
                "Author": {"rich_text": {}},
                "Executor": {"rich_text": {}},
                "Tags": {"rich_text": {}},
                "Created": {"date": {}},
                "Start": {"date": {}},
                "Due": {"date": {}},
                "Remind": {"date": {}},
                "Remind Time": {"rich_text": {}},
                "Remind Period": {"rich_text": {}},
                "Series": {"rich_text": {}},
                "Completed": {"date": {}},
                "Field Times": {"rich_text": {}},
                "Device": {"rich_text": {}},
            },
        }
        result = self.request("POST", "/databases", body)
        return _normalize_id(str(result.get("id") or ""))

    def query_all(self, database_id: str) -> list[dict]:
        db = _dash_id(_normalize_id(database_id))
        results: list[dict] = []
        cursor = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            page = self.request("POST", f"/databases/{db}/query", body)
            results.extend(page.get("results") or [])
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        return results

    def create_page(self, database_id: str, props: dict) -> str:
        db = _dash_id(_normalize_id(database_id))
        result = self.request(
            "POST",
            "/pages",
            {"parent": {"database_id": db}, "properties": props},
        )
        return _normalize_id(str(result.get("id") or ""))

    def update_page(self, page_id: str, props: dict) -> None:
        pid = _dash_id(_normalize_id(page_id))
        self.request("PATCH", f"/pages/{pid}", {"properties": props})

    def archive_page(self, page_id: str) -> None:
        pid = _dash_id(_normalize_id(page_id))
        self.request("PATCH", f"/pages/{pid}", {"archived": True})

    def create_child_page(self, parent_page_id: str, title: str, children: list[dict]) -> str:
        dashed = _dash_id(_normalize_id(parent_page_id))
        result = self.request(
            "POST",
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": dashed},
                "properties": {
                    "title": {"title": [{"type": "text", "text": {"content": title[:1900]}}]}
                },
                "children": children,
            },
        )
        return _normalize_id(str(result.get("id") or ""))

    def block_children(self, block_id: str) -> list[dict]:
        pid = _dash_id(_normalize_id(block_id))
        results: list[dict] = []
        cursor = None
        while True:
            path = f"/blocks/{pid}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            page = self.request("GET", path)
            results.extend(page.get("results") or [])
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        return results

    def delete_block(self, block_id: str) -> None:
        pid = _dash_id(_normalize_id(block_id))
        self.request("DELETE", f"/blocks/{pid}")

    def append_children(self, block_id: str, children: list[dict]) -> None:
        pid = _dash_id(_normalize_id(block_id))
        self.request("PATCH", f"/blocks/{pid}/children", {"children": children})


def _dash_id(value: str) -> str:
    raw = _normalize_id(value)
    if len(raw) != 32:
        return value
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def _rich(text: str) -> dict:
    content = (text or "")[:1900]
    return {"rich_text": [{"type": "text", "text": {"content": content}}]}


def _title(text: str) -> dict:
    content = (text or "")[:1900] or "(без названия)"
    return {"title": [{"type": "text", "text": {"content": content}}]}


def _date_prop(value: str | None) -> dict:
    if not value:
        return {"date": None}
    return {"date": {"start": value}}


def snapshot_to_props(snap: dict[str, Any], *, field_times: dict[str, str], device_id: str) -> dict:
    tags = snap.get("tags") or []
    if isinstance(tags, list):
        tags_cell = tags_to_cell(tags)
    else:
        tags_cell = str(tags)
    return {
        "Name": _title(str(snap.get("title") or "")),
        "Task ID": _rich(str(snap.get("id") or "")),
        "Project": _rich(str(snap.get("project") or "")),
        "Description": _rich(str(snap.get("description") or "")),
        "Author": _rich(str(snap.get("author") or "")),
        "Executor": _rich(str(snap.get("executor") or "")),
        "Tags": _rich(tags_cell),
        "Created": _date_prop(snap.get("created_at")),
        "Start": _date_prop(snap.get("start_at")),
        "Due": _date_prop(snap.get("due_at")),
        "Remind": _date_prop(snap.get("remind_at")),
        "Remind Time": _rich(str(snap.get("remind_time") or "")),
        "Remind Period": _rich(str(snap.get("remind_period") or "")),
        "Series": _rich(str(snap.get("series_id") or "")),
        "Completed": _date_prop(snap.get("completed_at")),
        "Field Times": _rich(json.dumps(field_times, ensure_ascii=False)),
        "Device": _rich(device_id),
    }


def _plain_rich(prop: dict | None) -> str:
    if not prop:
        return ""
    parts = []
    for item in prop.get("rich_text") or prop.get("title") or []:
        parts.append(item.get("plain_text") or "")
    return "".join(parts).strip()


def _plain_date(prop: dict | None) -> str | None:
    if not prop:
        return None
    date_obj = prop.get("date")
    if not date_obj:
        return None
    start = date_obj.get("start")
    return start[:10] if start else None


def page_to_snapshot(page: dict) -> dict[str, Any] | None:
    props = page.get("properties") or {}
    task_id = _plain_rich(props.get("Task ID"))
    title = _plain_rich(props.get("Name"))
    if not task_id and not title:
        return None
    tags_raw = _plain_rich(props.get("Tags"))
    from .tags import parse_tags_cell

    return {
        "id": task_id or "",
        "title": title,
        "project": _plain_rich(props.get("Project")),
        "description": _plain_rich(props.get("Description")),
        "author": _plain_rich(props.get("Author")),
        "executor": _plain_rich(props.get("Executor")),
        "tags": parse_tags_cell(tags_raw),
        "created_at": _plain_date(props.get("Created")),
        "start_at": _plain_date(props.get("Start")),
        "due_at": _plain_date(props.get("Due")),
        "remind_at": _plain_date(props.get("Remind")),
        "remind_time": _plain_rich(props.get("Remind Time")),
        "remind_period": _plain_rich(props.get("Remind Period")),
        "series_id": _plain_rich(props.get("Series")),
        "completed_at": _plain_date(props.get("Completed")),
        "source": "notion",
        "_page_id": _normalize_id(str(page.get("id") or "")),
        "_field_times": _parse_field_times(_plain_rich(props.get("Field Times"))),
        "_last_edited": str(page.get("last_edited_time") or ""),
    }


def _parse_field_times(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _field_value(snap: dict[str, Any], name: str) -> Any:
    val = snap.get(name)
    if name == "tags":
        return list(val or [])
    return val if val is not None else ""


def diff_snapshots(local: dict[str, Any], remote: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for name in COMPARE_FIELDS:
        if _field_value(local, name) != _field_value(remote, name):
            changed.append(name)
    return changed


def merge_by_field_times(
    local: dict[str, Any],
    remote: dict[str, Any],
    local_times: dict[str, str],
    remote_times: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Полевая merge: берём более свежий timestamp; конфликт → список полей."""
    merged = dict(local)
    times = dict(local_times)
    conflicts: list[str] = []
    for name in COMPARE_FIELDS:
        lt = local_times.get(name) or ""
        rt = remote_times.get(name) or ""
        lv = _field_value(local, name)
        rv = _field_value(remote, name)
        if lv == rv:
            times[name] = max(lt, rt) if lt or rt else times.get(name, "")
            continue
        if lt and rt and lt != rt:
            # обе стороны меняли поле после общего предка
            if lt > rt:
                merged[name] = lv
                times[name] = lt
            elif rt > lt:
                merged[name] = rv
                times[name] = rt
            else:
                conflicts.append(name)
            continue
        if rt and (not lt or rt > lt):
            merged[name] = rv
            times[name] = rt
        else:
            merged[name] = lv
            times[name] = lt or _now_iso()
    return merged, times, conflicts


def _lists_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _lists_blocks(payload: dict) -> list[dict]:
    raw = json.dumps(payload, ensure_ascii=False)
    size = 1800
    chunks = []
    if not raw:
        raw = "{}"
    for i in range(0, len(raw), size):
        chunks.append({"type": "text", "text": {"content": raw[i : i + size]}})
    return [
        {
            "object": "block",
            "type": "code",
            "code": {"language": "json", "rich_text": chunks},
        }
    ]


def _parse_lists_blocks(blocks: list[dict]) -> dict | None:
    for block in blocks:
        if block.get("type") != "code":
            continue
        parts: list[str] = []
        for item in (block.get("code") or {}).get("rich_text") or []:
            parts.append(
                item.get("plain_text")
                or ((item.get("text") or {}).get("content") or "")
            )
        raw = "".join(parts).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


@dataclass
class SyncResult:
    ok: bool
    message: str = ""
    pushed: int = 0
    pulled: int = 0
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    offline: bool = False


class NotionSyncManager:
    """Управление debounce-синком и суточной сверкой."""

    DEBOUNCE_MS = 60_000
    RETRY_MS = 3_600_000

    def __init__(
        self,
        store: TaskStore,
        *,
        on_applied: Callable[[], None] | None = None,
        on_conflicts: Callable[[list[dict[str, Any]]], None] | None = None,
        parent_timer_host: Any = None,
    ) -> None:
        self.store = store
        self.on_applied = on_applied
        self.on_conflicts = on_conflicts
        self.state = SyncState.load()
        self.changelog = ChangeLog()
        self.cfg = NotionConfig.from_dict(load_app_config().get("notion"))
        self._debounce = None
        self._retry = None
        self._host = parent_timer_host
        if parent_timer_host is not None:
            from PyQt6.QtCore import QTimer

            self._debounce = QTimer(parent_timer_host)
            self._debounce.setSingleShot(True)
            self._debounce.timeout.connect(self.sync_now)
            self._retry = QTimer(parent_timer_host)
            self._retry.setSingleShot(True)
            self._retry.timeout.connect(self.sync_now)

    def notify_local_change(
        self,
        task: Task | None,
        *,
        action: str = "upsert",
        before: dict[str, Any] | None = None,
    ) -> None:
        if not self.cfg.enabled:
            return
        if action == "delete" and task is None and before:
            task_id = str(before.get("id") or "")
            self.changelog.append(
                action="delete",
                task_id=task_id,
                snapshot=before,
                changed_fields=["__deleted__"],
                device_id=self.state.device_id,
            )
        elif task is not None:
            snap = snapshot_dict(task)
            changed = list(COMPARE_FIELDS)
            if before:
                changed = diff_snapshots(before, snap) or ["title"]
            now = _now_iso()
            times = dict(self.state.field_times.get(task.id) or {})
            for name in changed:
                times[name] = now
            self.state.field_times[task.id] = times
            self.state.save()
            self.changelog.append(
                action="upsert",
                task_id=task.id,
                snapshot=snap,
                changed_fields=changed,
                device_id=self.state.device_id,
            )
        self.schedule_debounce()

    def notify_lists_change(self) -> None:
        if not self.cfg.enabled:
            return
        self.schedule_debounce()

    def schedule_debounce(self) -> None:
        if self._debounce is None:
            return
        self._debounce.stop()
        self._debounce.start(self.DEBOUNCE_MS)

    def schedule_retry(self) -> None:
        if self._retry is None:
            return
        self._retry.stop()
        self._retry.start(self.RETRY_MS)

    def sync_now(self, *, force_full: bool = False) -> SyncResult:
        self.cfg = NotionConfig.from_dict(load_app_config().get("notion"))
        if not self.cfg.enabled:
            return SyncResult(ok=True, message="Notion sync выключен")
        if not self.cfg.token:
            return SyncResult(ok=False, message="Нет notion.token в config.json")
        if self._is_offline_cooldown() and not force_full:
            return SyncResult(ok=False, message="Офлайн-пауза", offline=True)

        client = NotionClient(self.cfg.token)
        try:
            if not self.cfg.database_id:
                if not self.cfg.parent_page_id:
                    return SyncResult(
                        ok=False,
                        message="Укажи notion.parent_page_id в config.json",
                    )
                db_id = client.create_database(self.cfg.parent_page_id)
                self.cfg.database_id = db_id
                cfg = load_app_config()
                notion = dict(cfg.get("notion") or {})
                notion["database_id"] = db_id
                cfg["notion"] = notion
                save_app_config(cfg)

            client.ensure_series_property(self.cfg.database_id)
            pushed = self._push_ops(client)
            pulled, conflicts = self._pull_and_merge(client)
            lists_pulled = self._sync_lists(client)
            pulled += lists_pulled
            need_full = force_full or self._need_daily_reconcile()
            if need_full:
                more_conflicts = self._full_reconcile(client)
                conflicts.extend(more_conflicts)
                self.state.last_full_reconcile_at = _now_iso()

            self.state.last_ops_sync_at = _now_iso()
            self.state.last_error = ""
            self.state.offline_until = ""
            self.state.save()
            if conflicts and self.on_conflicts:
                self.on_conflicts(conflicts)
            if pulled and self.on_applied:
                self.on_applied()
            return SyncResult(
                ok=True,
                message="ok",
                pushed=pushed,
                pulled=pulled,
                conflicts=conflicts,
            )
        except NotionApiError as exc:
            self.state.last_error = str(exc)
            self.state.last_error_at = _now_iso()
            if exc.offline:
                until = datetime.now(TZ) + timedelta(hours=1)
                self.state.offline_until = until.isoformat(timespec="seconds")
                self.schedule_retry()
            self.state.save()
            log.warning("Notion sync failed: %s", exc)
            return SyncResult(ok=False, message=str(exc), offline=exc.offline)

    def _is_offline_cooldown(self) -> bool:
        raw = self.state.offline_until
        if not raw:
            return False
        try:
            until = datetime.fromisoformat(raw)
        except ValueError:
            return False
        if until.tzinfo is None:
            until = until.replace(tzinfo=TZ)
        return datetime.now(TZ) < until

    def _need_daily_reconcile(self) -> bool:
        raw = self.state.last_full_reconcile_at
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=TZ)
        return datetime.now(TZ) - last >= timedelta(hours=20)

    def _push_ops(self, client: NotionClient) -> int:
        ops = self.changelog.load_all()
        if not ops:
            return 0
        # схлопываем по task_id: последний upsert / delete
        latest: dict[str, dict[str, Any]] = {}
        for op in ops:
            latest[str(op.get("task_id") or "")] = op
        remaining: list[dict[str, Any]] = []
        pushed = 0
        for task_id, op in latest.items():
            if not task_id:
                continue
            try:
                if op.get("action") == "delete":
                    page_id = self.state.page_map.get(task_id)
                    if page_id:
                        client.archive_page(page_id)
                        self.state.page_map.pop(task_id, None)
                        self.state.field_times.pop(task_id, None)
                    pushed += 1
                    continue
                snap = op.get("snapshot") or {}
                times = dict(self.state.field_times.get(task_id) or {})
                for name in op.get("changed_fields") or []:
                    times[name] = op.get("ts") or _now_iso()
                self.state.field_times[task_id] = times
                props = snapshot_to_props(
                    snap, field_times=times, device_id=self.state.device_id
                )
                page_id = self.state.page_map.get(task_id)
                if page_id:
                    client.update_page(page_id, props)
                else:
                    page_id = client.create_page(self.cfg.database_id, props)
                    self.state.page_map[task_id] = page_id
                pushed += 1
            except NotionApiError:
                remaining.append(op)
                raise
        self.changelog.replace_all(remaining)
        self.state.save()
        return pushed

    def _pull_and_merge(self, client: NotionClient) -> tuple[int, list[dict]]:
        pages = client.query_all(self.cfg.database_id)
        pending_ids = {str(op.get("task_id") or "") for op in self.changelog.load_all()}
        pulled = 0
        conflicts: list[dict[str, Any]] = []
        local_by_id = {t.id: t for t in self.store.tasks}
        changed_store = False

        for page in pages:
            if page.get("archived"):
                continue
            remote = page_to_snapshot(page)
            if not remote:
                continue
            task_id = str(remote.get("id") or "")
            page_id = str(remote.get("_page_id") or "")
            if task_id:
                self.state.page_map[task_id] = page_id
            if not task_id:
                continue
            if task_id in pending_ids:
                # локальные незапушенные ops важнее до push; конфликт поймает full reconcile
                continue
            local = local_by_id.get(task_id)
            local_snap = snapshot_dict(local) if local else None
            remote_times = dict(remote.get("_field_times") or {})
            local_times = dict(self.state.field_times.get(task_id) or {})
            if local_snap is None:
                task = self._task_from_snap(remote)
                self.store.tasks.append(task)
                self.state.field_times[task_id] = remote_times or {
                    f: remote.get("_last_edited") or _now_iso() for f in COMPARE_FIELDS
                }
                changed_store = True
                pulled += 1
                continue
            diffs = diff_snapshots(local_snap, remote)
            if not diffs:
                continue
            merged, times, field_conflicts = merge_by_field_times(
                local_snap, remote, local_times, remote_times
            )
            if field_conflicts:
                conflicts.append(
                    {
                        "task_id": task_id,
                        "title": merged.get("title") or task_id,
                        "fields": field_conflicts,
                        "local": {f: _field_value(local_snap, f) for f in field_conflicts},
                        "remote": {f: _field_value(remote, f) for f in field_conflicts},
                    }
                )
            from .activity_log import apply_state_to_task

            apply_state_to_task(local, merged)
            self.state.field_times[task_id] = times
            changed_store = True
            pulled += 1

        if changed_store:
            self.store.save()
        self.state.save()
        return pulled, conflicts

    def _full_reconcile(self, client: NotionClient) -> list[dict]:
        pages = client.query_all(self.cfg.database_id)
        remote_by_id: dict[str, dict] = {}
        for page in pages:
            if page.get("archived"):
                continue
            snap = page_to_snapshot(page)
            if snap and snap.get("id"):
                remote_by_id[str(snap["id"])] = snap

        conflicts: list[dict[str, Any]] = []
        local_ids = {t.id for t in self.store.tasks}
        for task in self.store.tasks:
            remote = remote_by_id.get(task.id)
            local_snap = snapshot_dict(task)
            if remote is None:
                # есть только локально — запушим при следующем ops sync
                self.changelog.append(
                    action="upsert",
                    task_id=task.id,
                    snapshot=local_snap,
                    changed_fields=list(COMPARE_FIELDS),
                    device_id=self.state.device_id,
                )
                continue
            diffs = diff_snapshots(local_snap, remote)
            if not diffs:
                continue
            local_times = dict(self.state.field_times.get(task.id) or {})
            remote_times = dict(remote.get("_field_times") or {})
            # если timestamps позволяют однозначно — merge без диалога
            merged, times, field_conflicts = merge_by_field_times(
                local_snap, remote, local_times, remote_times
            )
            if not field_conflicts and merged != local_snap:
                from .activity_log import apply_state_to_task

                apply_state_to_task(task, merged)
                self.state.field_times[task.id] = times
                self.store.save()
            elif field_conflicts or diffs:
                conflicts.append(
                    {
                        "task_id": task.id,
                        "title": task.title,
                        "fields": field_conflicts or diffs,
                        "local": {f: _field_value(local_snap, f) for f in (field_conflicts or diffs)},
                        "remote": {f: _field_value(remote, f) for f in (field_conflicts or diffs)},
                    }
                )

        for task_id, remote in remote_by_id.items():
            if task_id in local_ids:
                continue
            # есть только в Notion
            conflicts.append(
                {
                    "task_id": task_id,
                    "title": remote.get("title") or task_id,
                    "fields": ["__only_remote__"],
                    "local": {},
                    "remote": remote,
                }
            )
        self.state.save()
        return conflicts

    def _sync_lists(self, client: NotionClient) -> int:
        from .lists_store import ListsStore

        if not self.cfg.parent_page_id:
            return 0
        store = ListsStore(self.store.path)
        store.load()
        local = store.snapshot()
        local_hash = _lists_hash(local)
        page_id = self.state.lists_page_id
        remote = None
        if page_id:
            try:
                remote = _parse_lists_blocks(client.block_children(page_id))
            except NotionApiError:
                page_id = ""
                remote = None
        remote_hash = _lists_hash(remote) if remote else ""
        remembered = self.state.lists_hash or ""
        local_changed = local_hash != remembered
        remote_changed = bool(remote_hash) and remote_hash != remembered
        if remote and remote_changed and not local_changed:
            store.apply_snapshot(remote)
            self.state.lists_hash = remote_hash
            self.state.save()
            return 1
        if local_changed or not page_id:
            blocks = _lists_blocks(local)
            if page_id:
                for child in client.block_children(page_id):
                    cid = child.get("id")
                    if cid:
                        client.delete_block(str(cid))
                client.append_children(page_id, blocks)
            else:
                page_id = client.create_child_page(
                    self.cfg.parent_page_id, "TanionPlaning Lists", blocks
                )
                self.state.lists_page_id = page_id
            self.state.lists_hash = local_hash
            self.state.save()
        return 0

    def resolve_conflict(self, task_id: str, *, prefer: str) -> None:
        """prefer: local | remote"""
        pages = NotionClient(self.cfg.token).query_all(self.cfg.database_id)
        remote = None
        for page in pages:
            snap = page_to_snapshot(page)
            if snap and snap.get("id") == task_id:
                remote = snap
                break
        local = self.store.get(task_id)
        if prefer == "remote" and remote:
            if local is None:
                self.store.tasks.append(self._task_from_snap(remote))
            else:
                from .activity_log import apply_state_to_task

                apply_state_to_task(local, remote)
            self.state.field_times[task_id] = dict(remote.get("_field_times") or {})
            self.store.save()
            self.notify_local_change(self.store.get(task_id), action="upsert")
        elif prefer == "local" and local is not None:
            self.notify_local_change(local, action="upsert", before=None)
            # форсируем все поля
            now = _now_iso()
            self.state.field_times[task_id] = {f: now for f in COMPARE_FIELDS}
            self.state.save()
            self.schedule_debounce()

    @staticmethod
    def _task_from_snap(snap: dict[str, Any]) -> Task:
        from .activity_log import task_from_state

        return task_from_state(snap)
