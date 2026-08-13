"""Отступы контента от плавающей панели кнопок.

Правило: кнопки не накладываются на задачи — резервируем полосу
со стороны панели и сдвигаем раскладку.
"""

from __future__ import annotations

from .widgets import CIRCLE

# ширина панели кнопок + зазор до задач
SIDE_PANEL_PAD = CIRCLE + 24
CONTENT_BASE_MARGIN = 8


def content_side_margins(
    controls_on_left: bool,
    *,
    base: int = CONTENT_BASE_MARGIN,
) -> tuple[int, int]:
    """Вернуть (left, right) отступы для области задач."""
    if controls_on_left:
        return SIDE_PANEL_PAD, base
    return base, SIDE_PANEL_PAD


def content_left(controls_on_left: bool, *, base: int = CONTENT_BASE_MARGIN) -> int:
    return content_side_margins(controls_on_left, base=base)[0]


def content_right(controls_on_left: bool, *, base: int = CONTENT_BASE_MARGIN) -> int:
    return content_side_margins(controls_on_left, base=base)[1]
