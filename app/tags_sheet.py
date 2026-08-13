"""Вкладка xlsx «tags»: панель / системные / скрытые теги с символами."""

from __future__ import annotations

from openpyxl.workbook.workbook import Workbook

from .tag_order import ordered_tag_defs
from .tags import BY_KEY, SIDEBAR_TAG_KEYS, SYSTEM_TAG_KEYS, TAGS

TAGS_SHEET = "tags"


def write_tags_sheet(wb: Workbook) -> None:
    """Перезаписать лист tags (панель | системные | скрытые)."""
    if TAGS_SHEET in wb.sheetnames:
        del wb[TAGS_SHEET]
    ws = wb.create_sheet(TAGS_SHEET)

    panel = ordered_tag_defs(for_bar=True)
    system = [t for t in TAGS if t.key in SYSTEM_TAG_KEYS]
    hidden = [BY_KEY[k] for k in SIDEBAR_TAG_KEYS if k in BY_KEY]

    ws.append(
        [
            "панель_ключ",
            "панель_символ",
            "системный_ключ",
            "системный_символ",
            "скрытый_ключ",
            "скрытый_символ",
        ]
    )
    n = max(len(panel), len(system), len(hidden), 1)
    for i in range(n):
        ws.append(
            [
                panel[i].key if i < len(panel) else None,
                panel[i].symbol if i < len(panel) else None,
                system[i].key if i < len(system) else None,
                system[i].symbol if i < len(system) else None,
                hidden[i].key if i < len(hidden) else None,
                hidden[i].symbol if i < len(hidden) else None,
            ]
        )
