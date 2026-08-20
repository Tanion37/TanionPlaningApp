"""Временное скрытие задачи на экране «Задачи дня» (даты не меняются)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=3))


def _path(root: Path | None = None) -> Path:
    from .paths import app_root

    base = root or app_root()
    return base / "data" / "day_hidden.json"


def _now() -> datetime:
    return datetime.now(TZ)


def _load_raw(root: Path | None = None) -> dict[str, str]:
    import json

    path = _path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k and v}


def _save_raw(data: dict[str, str], root: Path | None = None) -> None:
    import json

    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_until(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def prune(root: Path | None = None) -> dict[str, str]:
    now = _now()
    raw = _load_raw(root)
    kept = {}
    for tid, stamp in raw.items():
        until = _parse_until(stamp)
        if until is not None and until > now:
            kept[tid] = stamp
    if kept != raw:
        _save_raw(kept, root)
    return kept


def hide_task(task_id: str, hours: float = 4, root: Path | None = None) -> datetime:
    tid = (task_id or "").strip()
    until = _now() + timedelta(hours=hours)
    data = prune(root)
    if tid:
        data[tid] = until.isoformat()
        _save_raw(data, root)
    return until


def is_hidden(task_id: str, root: Path | None = None) -> bool:
    tid = (task_id or "").strip()
    if not tid:
        return False
    data = prune(root)
    return tid in data


def without_hidden(tasks: list, root: Path | None = None) -> list:
    data = prune(root)
    if not data:
        return list(tasks)
    return [t for t in tasks if getattr(t, "id", "") not in data]
