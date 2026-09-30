"""Роли студии для карточки задачи."""

from __future__ import annotations

from enum import Enum


class StudioRole(Enum):
    STUDIO_HEAD = "Руководитель студии"
    STUDIO_COORDINATOR = "Координатор студии"
    MANAGER = "Менеджер"
    GAME_DESIGNER = "Геймдизайнер"
    ARTIST = "Художник/Дизайнер"
    COPYWRITER = "Копирайтер/Корректор"
    EDITOR = "Редактор"
    SCREENWRITER = "Сценарист"
    LAYOUT = "Верстальщик"


def role_labels() -> list[str]:
    return [role.value for role in StudioRole]


def coerce_role(value: object) -> str:
    text = str(value or "").strip()
    if text in _ROLE_VALUES:
        return text
    return ""


_ROLE_VALUES = frozenset(role_labels())
