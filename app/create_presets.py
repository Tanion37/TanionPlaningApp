"""Пресеты быстрого создания задачи."""

from __future__ import annotations

from datetime import date

from .day_tasks import SECTION_GORIT, SECTION_NUZHNO, apply_priority_section
from .models import Task
from .tags import BACKLOG_TAG, DONE_TAG, INBOX_TAG

PRESET_GORIT = "горящая"
PRESET_NUZHNO = "нужно"
PRESET_INBOX = "во входящие"
PRESET_BACKLOG = "в беклог"
PRESET_DONE = "отметить выполненное"

CREATE_PRESETS: tuple[str, ...] = (
    PRESET_GORIT,
    PRESET_NUZHNO,
    PRESET_INBOX,
    PRESET_BACKLOG,
    PRESET_DONE,
)


def tags_for_preset(preset: str, base_tags: list[str] | None = None) -> list[str]:
    """Итоговые теги для пресета; сохраняет несистемные из base_tags."""
    from .tags import ACTUAL_TAG, IMPORTANT_TAG, URGENT_TAG

    keep = [
        t
        for t in (base_tags or [])
        if t
        not in {
            INBOX_TAG,
            BACKLOG_TAG,
            DONE_TAG,
            ACTUAL_TAG,
            IMPORTANT_TAG,
            URGENT_TAG,
        }
    ]
    stub = Task(id="0", title="", tags=list(keep))
    if preset == PRESET_GORIT:
        apply_priority_section(stub, SECTION_GORIT)
    elif preset == PRESET_NUZHNO:
        apply_priority_section(stub, SECTION_NUZHNO)
    elif preset == PRESET_INBOX:
        stub.add_tag(INBOX_TAG)
    elif preset == PRESET_BACKLOG:
        stub.add_tag(BACKLOG_TAG)
    elif preset == PRESET_DONE:
        stub.add_tag(DONE_TAG)
    return list(stub.tags)


def apply_preset_to_new_task_data(data: dict, preset: str | None) -> dict:
    """Дополнить data тегами и completed_at по пресету."""
    if not preset:
        return data
    data["tags"] = tags_for_preset(preset, list(data.get("tags") or []))
    if preset == PRESET_DONE and not data.get("completed_at"):
        data["completed_at"] = date.today()
    return data
