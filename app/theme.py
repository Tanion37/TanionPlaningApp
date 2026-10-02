"""Светлая и тёмная тема экранов."""

from __future__ import annotations

import json

BG_LIGHT = "#FAFAF7"
BG_DARK = "#3C3A46"
CARD_LIGHT = "#FFFFFF"
CARD_DARK = "#4E4B58"
SELECT = "#7C3AED"

_dark = False


def is_dark() -> bool:
    return _dark


def board_bg() -> str:
    return BG_DARK if _dark else BG_LIGHT


def card_bg() -> str:
    return CARD_DARK if _dark else CARD_LIGHT


def board_style() -> str:
    return f"background:{board_bg()};"


def readable(color: str) -> str:
    if _dark and color.lower() in {"#000000", "#000", "#555555"}:
        return "#F4F1F8" if color.lower() in {"#000000", "#000"} else "#D9D6E0"
    return color


def set_dark(on: bool) -> None:
    global _dark
    _dark = bool(on)


def toggle() -> bool:
    set_dark(not _dark)
    save()
    return _dark


def _path():
    from .paths import app_root

    return app_root() / "data" / "theme.json"


def load() -> None:
    path = _path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    set_dark(bool(data.get("dark")))


def save() -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"dark": _dark}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
