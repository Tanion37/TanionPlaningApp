"""Журнал действий с задачами: data/logs/YYYY-MM-DD.jsonl."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import Task, parse_date
from .tags import tags_to_cell

TZ = timezone(timedelta(hours=3))

Action = str  # created | moved | changed | completed | cancelled


def _root() -> Path:
    from .paths import app_root

    return app_root()


def logs_dir(root: Path | None = None) -> Path:
    base = root or _root()
    path = base / "data" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path_for(day: date, root: Path | None = None) -> Path:
    return logs_dir(root) / f"{day.isoformat()}.jsonl"


def now_local() -> datetime:
    return datetime.now(TZ)


def format_task_snapshot(task: Task | None) -> str:
    if task is None:
        return "(нет)"
    parts = [f"#{task.id}", (task.title or "").strip() or "(без названия)"]
    project = (task.project or "").strip()
    if project:
        parts.append(f"[{project}]")
    tags = tags_to_cell(list(task.tags or []))
    if tags:
        parts.append(tags)
    if task.start_at:
        parts.append(f"старт {task.start_at.isoformat()}")
    if task.due_at:
        parts.append(f"до {task.due_at.isoformat()}")
    if task.is_done():
        parts.append("✅")
    if task.is_cancelled():
        parts.append("🗑")
    return " ".join(parts)


def _date_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def snapshot_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "project": task.project,
        "description": task.description,
        "author": task.author,
        "executor": getattr(task, "executor", "") or "",
        "tags": list(task.tags),
        "created_at": _date_iso(task.created_at),
        "start_at": _date_iso(task.start_at),
        "due_at": _date_iso(task.due_at),
        "remind_at": _date_iso(task.remind_at),
        "remind_time": task.remind_time or "",
        "remind_period": task.remind_period or "",
        "series_id": getattr(task, "series_id", "") or "",
        "completed_at": _date_iso(task.completed_at),
        "pos_x": task.pos_x,
        "pos_y": task.pos_y,
        "author_id": task.author_id,
        "chat_id": task.chat_id,
        "source": task.source or "app",
        "text": format_task_snapshot(task),
    }


def task_from_state(snap: dict[str, Any]) -> Task:
    return Task(
        id=str(snap.get("id") or ""),
        title=str(snap.get("title") or ""),
        created_at=parse_date(snap.get("created_at")),
        completed_at=parse_date(snap.get("completed_at")),
        start_at=parse_date(snap.get("start_at")),
        due_at=parse_date(snap.get("due_at")),
        remind_at=parse_date(snap.get("remind_at")),
        remind_time=str(snap.get("remind_time") or "").strip(),
        remind_period=str(snap.get("remind_period") or ""),
        series_id=str(snap.get("series_id") or ""),
        author=str(snap.get("author") or ""),
        executor=str(snap.get("executor") or "").strip(),
        project=str(snap.get("project") or ""),
        description=str(snap.get("description") or ""),
        tags=list(snap.get("tags") or []),
        pos_x=snap.get("pos_x"),
        pos_y=snap.get("pos_y"),
        author_id=snap.get("author_id"),
        chat_id=snap.get("chat_id"),
        source=str(snap.get("source") or "app"),
    )


def apply_state_to_task(task: Task, snap: dict[str, Any]) -> None:
    task.title = str(snap.get("title") or "")
    task.project = str(snap.get("project") or "")
    task.description = str(snap.get("description") or "")
    task.author = str(snap.get("author") or "")
    task.executor = str(snap.get("executor") or "").strip()
    task.tags = list(snap.get("tags") or [])
    task.created_at = parse_date(snap.get("created_at"))
    task.start_at = parse_date(snap.get("start_at"))
    task.due_at = parse_date(snap.get("due_at"))
    task.remind_at = parse_date(snap.get("remind_at"))
    task.remind_time = str(snap.get("remind_time") or "").strip()
    task.remind_period = str(snap.get("remind_period") or "")
    if "series_id" in snap:
        task.series_id = str(snap.get("series_id") or "")
    task.completed_at = parse_date(snap.get("completed_at"))
    if "pos_x" in snap:
        task.pos_x = snap.get("pos_x")
    if "pos_y" in snap:
        task.pos_y = snap.get("pos_y")


@dataclass
class LogEntry:
    ts: datetime
    action: Action
    task_id: str
    before: str | None = None
    after: str | None = None
    detail: str = ""
    source: str = "app"
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    undoes_ts: str | None = None
    batch: str | None = None

    @property
    def ts_key(self) -> str:
        return self.ts.astimezone(TZ).isoformat(timespec="seconds")

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "ts": self.ts_key,
            "action": self.action,
            "task_id": self.task_id,
            "before": self.before,
            "after": self.after,
            "detail": self.detail,
            "source": self.source,
        }
        if self.before_state is not None:
            data["before_state"] = self.before_state
        if self.after_state is not None:
            data["after_state"] = self.after_state
        if self.undoes_ts:
            data["undoes_ts"] = self.undoes_ts
        if self.batch:
            data["batch"] = self.batch
        return data

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> LogEntry:
        ts_raw = raw.get("ts") or ""
        try:
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ)
        except ValueError:
            ts = now_local()
        before_state = raw.get("before_state")
        after_state = raw.get("after_state")
        if before_state is not None and not isinstance(before_state, dict):
            before_state = None
        if after_state is not None and not isinstance(after_state, dict):
            after_state = None
        return cls(
            ts=ts,
            action=str(raw.get("action") or "changed"),
            task_id=str(raw.get("task_id") or ""),
            before=raw.get("before"),
            after=raw.get("after"),
            detail=str(raw.get("detail") or ""),
            source=str(raw.get("source") or "app"),
            before_state=before_state,
            after_state=after_state,
            undoes_ts=(str(raw["undoes_ts"]) if raw.get("undoes_ts") else None),
            batch=(str(raw["batch"]) if raw.get("batch") else None),
        )


def append_log(
    action: Action,
    task: Task | None = None,
    *,
    before: str | None = None,
    after: str | None = None,
    detail: str = "",
    source: str = "app",
    task_id: str | None = None,
    root: Path | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    undoes_ts: str | None = None,
    batch: str | None = None,
) -> LogEntry:
    ts = now_local()
    tid = task_id or (task.id if task else "")
    if after is None and task is not None:
        after = format_task_snapshot(task)
    if after_state is None and task is not None:
        after_state = snapshot_dict(task)
    entry = LogEntry(
        ts=ts,
        action=action,
        task_id=str(tid),
        before=before,
        after=after,
        detail=detail,
        source=source,
        before_state=before_state,
        after_state=after_state,
        undoes_ts=undoes_ts,
        batch=batch,
    )
    path = log_path_for(ts.date(), root)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry.to_json(), ensure_ascii=False) + "\n")
    return entry


def load_day(day: date, root: Path | None = None) -> list[LogEntry]:
    path = log_path_for(day, root)
    if not path.exists():
        return []
    out: list[LogEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(LogEntry.from_json(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    out.sort(key=lambda e: e.ts)
    return out


def load_days(count: int = 14, *, today: date | None = None, root: Path | None = None) -> list[tuple[date, list[LogEntry]]]:
    today = today or now_local().date()
    result: list[tuple[date, list[LogEntry]]] = []
    for i in range(count):
        day = today - timedelta(days=i)
        result.append((day, load_day(day, root)))
    return result


def load_recent_entries(days: int = 14, *, root: Path | None = None) -> list[LogEntry]:
    """Хронология от старых к новым за последние days суток."""
    today = now_local().date()
    entries: list[LogEntry] = []
    for i in range(days - 1, -1, -1):
        entries.extend(load_day(today - timedelta(days=i), root))
    return entries


def meta_kind(entry: LogEntry) -> str | None:
    detail = (entry.detail or "").strip().casefold()
    if detail == "undo" or detail.startswith("undo "):
        return "undo"
    if detail == "redo" or detail.startswith("redo "):
        return "redo"
    return None


def compute_undone_ts(entries: Iterable[LogEntry]) -> set[str]:
    undone: set[str] = set()
    for e in entries:
        kind = meta_kind(e)
        ref = (e.undoes_ts or "").strip()
        if not ref:
            continue
        if kind == "undo":
            undone.add(ref)
        elif kind == "redo":
            undone.discard(ref)
    return undone


def is_reversible(entry: LogEntry) -> bool:
    if meta_kind(entry):
        return False
    if entry.action == "created":
        return bool(entry.after_state) or bool(entry.task_id)
    return bool(entry.before_state)


def find_undo_target(entries: list[LogEntry] | None = None, *, root: Path | None = None) -> LogEntry | None:
    entries = entries if entries is not None else load_recent_entries(root=root)
    undone = compute_undone_ts(entries)
    for e in reversed(entries):
        if not is_reversible(e):
            continue
        if e.ts_key in undone:
            continue
        return e
    return None


def find_redo_target(entries: list[LogEntry] | None = None, *, root: Path | None = None) -> LogEntry | None:
    """Последняя активная undo-запись (её undoes_ts ещё в множестве undone)."""
    entries = entries if entries is not None else load_recent_entries(root=root)
    undone = compute_undone_ts(entries)
    for e in reversed(entries):
        if meta_kind(e) != "undo":
            continue
        ref = (e.undoes_ts or "").strip()
        if ref and ref in undone:
            return e
    return None


MASS_UNDO_SEC = 5


def find_undo_targets(entries: list[LogEntry] | None = None, *, root: Path | None = None) -> list[LogEntry]:
    """Если последнее действие массовое — все обратимые за последние 5 секунд."""
    entries = entries if entries is not None else load_recent_entries(root=root)
    last = find_undo_target(entries)
    if last is None:
        return []
    if not (last.batch or "").strip():
        return [last]
    undone = compute_undone_ts(entries)
    cutoff = last.ts - timedelta(seconds=MASS_UNDO_SEC)
    out: list[LogEntry] = []
    for e in reversed(entries):
        if e.ts < cutoff:
            continue
        if not is_reversible(e) or e.ts_key in undone:
            continue
        out.append(e)
    return out or [last]


def find_redo_targets(entries: list[LogEntry] | None = None, *, root: Path | None = None) -> list[LogEntry]:
    """Пакет redo: все undo за 5 секунд, если исходное действие было массовым."""
    entries = entries if entries is not None else load_recent_entries(root=root)
    last = find_redo_target(entries)
    if last is None:
        return []
    by_key = {e.ts_key: e for e in entries}
    orig = by_key.get((last.undoes_ts or "").strip())
    if orig is None or not (orig.batch or "").strip():
        return [last]
    undone = compute_undone_ts(entries)
    cutoff = last.ts - timedelta(seconds=MASS_UNDO_SEC)
    out: list[LogEntry] = []
    for e in reversed(entries):
        if e.ts < cutoff:
            continue
        if meta_kind(e) != "undo":
            continue
        ref = (e.undoes_ts or "").strip()
        if ref and ref in undone:
            out.append(e)
    return out or [last]


def completed_titles_for_day(day: date, root: Path | None = None) -> list[str]:
    """Строки задач за день: «выполнена» или метка «контроль» (название + теги)."""
    from .tags import CONTROL_TAG, DONE_TAG, tags_to_cell

    ordered_ids: list[str] = []
    seen: set[str] = set()

    def _remember(task_id: str) -> None:
        tid = (task_id or "").strip()
        if not tid or tid in seen:
            return
        seen.add(tid)
        ordered_ids.append(tid)

    def _snapshot_done(text: str | None) -> bool:
        if not text:
            return False
        low = text.casefold()
        return "✅" in text or DONE_TAG in low or "выполненн" in low

    def _snapshot_control(text: str | None) -> bool:
        if not text:
            return False
        low = text.casefold()
        return (
            CONTROL_TAG in low
            or "👁" in text
            or "контрол" in low
        )

    def _line_from_snapshot(task_id: str, text: str | None) -> str:
        """Fallback из лога: убрать #id и даты, оставить название и теги."""
        raw = (text or "").strip()
        if not raw:
            return ""
        if task_id and raw.startswith(f"#{task_id}"):
            raw = raw[len(task_id) + 1 :].strip()
        elif raw.startswith("#"):
            parts = raw.split(None, 1)
            raw = parts[1] if len(parts) > 1 else raw
        for marker in (" старт ", " до "):
            idx = raw.find(marker)
            if idx >= 0:
                raw = raw[:idx].rstrip()
        while raw.endswith(" ✅"):
            raw = raw[:-2].rstrip()
        return raw.strip()

    def _line_from_task(task: Task) -> str:
        title = (task.title or "").strip()
        if not title:
            return ""
        parts = [title]
        project = (task.project or "").strip()
        if project:
            parts.append(f"[{project}]")
        tags = tags_to_cell(list(task.tags or []))
        if tags:
            parts.append(tags)
        return " ".join(parts)

    fallback_lines: dict[str, str] = {}

    for e in load_day(day, root):
        tid = (e.task_id or "").strip()
        if e.action == "completed":
            if tid:
                _remember(tid)
                fallback_lines.setdefault(
                    tid, _line_from_snapshot(tid, e.after or e.before)
                )
            continue
        detail = (e.detail or "").casefold()
        if e.action == "changed" and (
            detail == f"toggle {DONE_TAG}"
            or detail.startswith("toggle выполнен")
        ):
            if _snapshot_done(e.after) and not _snapshot_done(e.before):
                if tid:
                    _remember(tid)
                    fallback_lines.setdefault(
                        tid, _line_from_snapshot(tid, e.after or e.before)
                    )
            continue
        if e.action == "changed" and (
            detail == f"toggle {CONTROL_TAG}"
            or detail.startswith("toggle контрол")
            or (
                _snapshot_control(e.after)
                and not _snapshot_control(e.before)
            )
        ):
            if _snapshot_control(e.after) and not _snapshot_control(e.before):
                if tid:
                    _remember(tid)
                    fallback_lines.setdefault(
                        tid, _line_from_snapshot(tid, e.after or e.before)
                    )

    tasks_by_id: dict[str, Task] = {}
    try:
        from .xlsx_store import TaskStore, default_xlsx_path

        store = TaskStore(default_xlsx_path(root or _root()))
        store.load()
        for task in store.tasks:
            if task.id:
                tasks_by_id[task.id] = task
            if task.completed_at == day and task.is_done():
                _remember(task.id)
    except OSError:
        pass

    lines: list[str] = []
    for tid in ordered_ids:
        task = tasks_by_id.get(tid)
        line = _line_from_task(task) if task else ""
        if not line:
            line = fallback_lines.get(tid) or f"#{tid}"
        if line:
            lines.append(line)
    return lines


def day_sections(entries: list[LogEntry]) -> tuple[list[LogEntry], list[LogEntry], list[LogEntry]]:
    """выполненные, изменённые, все (хронология с ранних)."""
    completed = [e for e in entries if e.action == "completed"]
    changed = [e for e in entries if e.action == "changed"]
    return completed, changed, list(entries)


def format_entry_line(e: LogEntry) -> str:
    t = e.ts.astimezone(TZ).strftime("%H:%M")
    if e.action == "changed" and e.before and e.after:
        body = f"{e.before} → {e.after}"
    elif e.action == "moved":
        body = f"{e.after or e.before or e.task_id} → {e.detail or 'колонка'}"
    elif e.action == "completed":
        body = f"✅ {e.after or e.before or e.task_id}"
    elif e.action == "cancelled":
        body = f"🗑 {e.after or e.before or e.task_id}"
    elif e.action == "created":
        body = f"+ {e.after or e.task_id}"
    else:
        body = e.after or e.detail or e.task_id
    if e.detail and e.action not in {"moved"}:
        return f"{t} [{e.action}] {body} ({e.detail})"
    return f"{t} [{e.action}] {body}"


def done_for_day_reply(day: date, label: str, root: Path | None = None) -> str:
    """Текст как у команды СЕГОДНЯ, с произвольным заголовком."""
    titles = completed_titles_for_day(day, root)
    if not titles:
        return f"{label}: выполненных и «контроль» нет."
    return f"{label}:\n" + "\n".join(f"• {t}" for t in titles)
