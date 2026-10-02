"""Светлая и тёмная тема экранов."""

from __future__ import annotations

import json

BG_LIGHT = "#FAFAF7"
BG_DARK = "#3C3A46"
CARD_LIGHT = "#FFFFFF"
CARD_DARK = "#4E4B58"
SELECT = "#7C3AED"
PASTEL_WHITE = "#F7F4EF"

_dark = False


def is_dark() -> bool:
    return _dark


def board_bg() -> str:
    return BG_DARK if _dark else BG_LIGHT


def card_bg() -> str:
    return CARD_DARK if _dark else CARD_LIGHT


def board_style() -> str:
    return f"background:{board_bg()};"


def _channels(color: str) -> tuple[int, int, int] | None:
    text = (color or "").strip()
    if not text.startswith("#"):
        return None
    hexpart = text[1:]
    if len(hexpart) == 3:
        hexpart = "".join(ch * 2 for ch in hexpart)
    if len(hexpart) != 6:
        return None
    try:
        value = int(hexpart, 16)
    except ValueError:
        return None
    return (value >> 16) & 255, (value >> 8) & 255, value & 255


def readable(color: str) -> str:
    """В тёмной теме тот же оттенок, но пастельно-светлый. Чёрный и тёмно-серый — пастельно-белый."""
    if not _dark:
        return color
    channels = _channels(color)
    if channels is None:
        return color
    red, green, blue = channels
    spread = max(red, green, blue) - min(red, green, blue)
    luma = 0.299 * red + 0.587 * green + 0.114 * blue
    if spread < 28 and luma < 96:
        return PASTEL_WHITE

    def lift(channel: int) -> int:
        return min(255, int(channel + (255 - channel) * 0.62))

    lifted = (lift(red), lift(green), lift(blue))
    return f"#{lifted[0]:02X}{lifted[1]:02X}{lifted[2]:02X}"


def menu_qss() -> str:
    if _dark:
        return (
            "QMenu { background:#4E4B58; color:#F7F4EF; border:1px solid #6E6A78; }"
            "QMenu::item { padding:6px 18px; background:transparent; color:#F7F4EF; }"
            "QMenu::item:selected { background:#6A6578; color:#F7F4EF; }"
        )
    return (
        "QMenu { background:#FFFFFF; color:#000000; border:1px solid #CCCCCC; }"
        "QMenu::item { padding:6px 18px; background:transparent; color:#000000; }"
        "QMenu::item:selected { background:#E4D9FF; color:#000000; }"
    )


def apply_palette(app) -> None:
    if app is None:
        return
    from PyQt6.QtGui import QColor, QPalette

    pal = QPalette()
    if _dark:
        window = QColor(BG_DARK)
        base = QColor(CARD_DARK)
        text = QColor(PASTEL_WHITE)
        button = QColor(CARD_DARK)
        highlight = QColor("#6A6578")
        highlighted = QColor(PASTEL_WHITE)
        muted = QColor("#B7B3C2")
    else:
        window = QColor(BG_LIGHT)
        base = QColor(CARD_LIGHT)
        text = QColor("#000000")
        button = QColor("#F0F0F0")
        highlight = QColor("#E4D9FF")
        highlighted = QColor("#000000")
        muted = QColor("#999999")
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, window)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, button)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, highlighted)
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, muted)
    app.setPalette(pal)


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
