"""Очередь экрана «Фокус»: невыполненные задачи по кругу."""

from __future__ import annotations

import json
from typing import Iterable

from .models import Task
from .morning_review import DEFAULT_FONT_PT, clamp_font_pt

ACTION_LATER = "later"


def settings_path():
    from .paths import app_root

    return app_root() / "data" / "focus.json"


def load_font_pt() -> int:
    path = settings_path()
    if not path.exists():
        return DEFAULT_FONT_PT
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return clamp_font_pt(int(raw.get("font_pt", DEFAULT_FONT_PT)))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_FONT_PT


def save_font_pt(pt: int) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"font_pt": clamp_font_pt(pt)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _group(task: Task) -> int:
    """0 — горящие, 1 — актуальные, 2 — остальные невыполненные."""
    if task.is_important() and task.is_urgent():
        return 0
    if task.is_actual():
        return 1
    return 2


def focus_queue(tasks: Iterable[Task]) -> list[Task]:
    """Невыполненные: сначала горящие, затем актуальные, затем остальные."""
    items = [
        task
        for task in tasks
        if not task.deleted and not task.is_done() and not task.is_cancelled()
    ]
    items.sort(key=lambda task: (_group(task), (task.title or "").casefold(), task.id))
    return items


def next_index(ids: list[str], current_id: str | None) -> int:
    """Следующая позиция по кругу. Одна задача остаётся на месте."""
    if not ids:
        return 0
    if len(ids) == 1:
        return 0
    if current_id in ids:
        return (ids.index(current_id) + 1) % len(ids)
    return 0
