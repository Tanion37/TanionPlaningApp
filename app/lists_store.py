"""Списки (xlsx-вкладка lists): колонки = списки, строка 1 = имя+алиасы."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .xlsx_store import default_xlsx_path

SHEET_NAME = "lists"

# (каноническое имя, алиасы…) – без личных имён
DEFAULT_LISTS: tuple[tuple[str, ...], ...] = (
    ("Книги", "Почитать"),
    ("Фильмы", "Посмотреть", "Кино"),
    ("Игры", "Поиграть"),
    ("Покупки",),
    ("Идеи",),
)


@dataclass
class ListColumn:
    name: str
    aliases: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)

    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]

    def header_cell(self) -> str:
        parts = [self.name, *self.aliases]
        return ",".join(parts)


class ListsStore:
    def __init__(self, xlsx_path: Path | None = None) -> None:
        self.path = xlsx_path or default_xlsx_path()
        self.columns: list[ListColumn] = []

    def load(self) -> list[ListColumn]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.columns = self._defaults()
            self.save()
            return list(self.columns)

        wb = load_workbook(self.path, data_only=True)
        if SHEET_NAME not in wb.sheetnames:
            self.columns = self._defaults()
            self.save()
            return list(self.columns)

        ws = wb[SHEET_NAME]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            self.columns = self._defaults()
            self.save()
            return list(self.columns)

        header = rows[0]
        cols: list[ListColumn] = []
        for col_idx, cell in enumerate(header):
            if cell is None or str(cell).strip() == "":
                continue
            parts = [p.strip() for p in str(cell).split(",") if p.strip()]
            if not parts:
                continue
            name, aliases = parts[0], parts[1:]
            items: list[str] = []
            for row in rows[1:]:
                if col_idx >= len(row):
                    continue
                val = row[col_idx]
                if val is None or str(val).strip() == "":
                    continue
                items.append(str(val).strip())
            cols.append(ListColumn(name=name, aliases=aliases, items=items))

        if not cols:
            cols = self._defaults()
            self.columns = cols
            self.save()
            return list(self.columns)

        self.columns = cols
        return list(self.columns)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            wb = load_workbook(self.path)
        else:
            wb = Workbook()
            default = wb.active
            default.title = "tasks"
            from .xlsx_store import COLUMNS

            default.append(list(COLUMNS))

        if SHEET_NAME in wb.sheetnames:
            del wb[SHEET_NAME]
        ws = wb.create_sheet(SHEET_NAME)

        if not self.columns:
            self.columns = self._defaults()

        max_items = max((len(c.items) for c in self.columns), default=0)
        headers = [c.header_cell() for c in self.columns]
        ws.append(headers)
        for i in range(max_items):
            row = []
            for c in self.columns:
                row.append(c.items[i] if i < len(c.items) else None)
            ws.append(row)

        wb.save(self.path)

    def _defaults(self) -> list[ListColumn]:
        return [
            ListColumn(name=names[0], aliases=list(names[1:]), items=[])
            for names in DEFAULT_LISTS
        ]

    def resolve(self, needle: str) -> ListColumn | None:
        key = (needle or "").strip().casefold()
        if not key:
            return None
        for col in self.columns:
            for name in col.all_names():
                if name.casefold() == key:
                    return col
        hits = [
            col
            for col in self.columns
            if any(key in n.casefold() for n in col.all_names())
        ]
        if len(hits) == 1:
            return hits[0]
        return None

    def add_item(self, list_needle: str, item: str) -> tuple[ListColumn | None, str]:
        """Добавить пункт. Вернуть (колонка, сообщение об ошибке или '')."""
        text = (item or "").strip()
        if not text:
            return None, "Пустой пункт списка."
        col = self.resolve(list_needle)
        if col is None:
            return None, f"Список «{list_needle}» не найден."
        if text in col.items:
            return col, "already"
        col.items.append(text)
        self.save()
        return col, ""
