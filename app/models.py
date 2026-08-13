"""Модель задачи планировщика."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def format_date(value: date | None) -> str:
    return value.isoformat() if value else ""


@dataclass
class Task:
    id: str
    title: str
    created_at: date | None = None
    completed_at: date | None = None
    start_at: date | None = None  # когда можно приступать
    due_at: date | None = None  # когда надо закончить
    remind_at: date | None = None
    remind_time: str = ""  # "HH:MM"
    remind_period: str = ""
    author: str = ""
    project: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    pos_x: float | None = None
    pos_y: float | None = None
    author_id: int | None = None
    chat_id: int | None = None
    source: str = "app"

    def has_tag(self, key: str) -> bool:
        return key in self.tags

    def add_tag(self, key: str) -> bool:
        if key in self.tags:
            return False
        self.tags.append(key)
        return True

    def remove_tag(self, key: str) -> bool:
        if key not in self.tags:
            return False
        self.tags.remove(key)
        return True

    def toggle_tag(self, key: str) -> bool:
        """Вернуть True, если тег теперь включён."""
        if self.has_tag(key):
            self.remove_tag(key)
            return False
        self.add_tag(key)
        return True

    def is_backlog(self) -> bool:
        from .tags import BACKLOG_TAG

        return self.has_tag(BACKLOG_TAG)

    def is_done(self) -> bool:
        from .tags import DONE_ALIASES, DONE_TAG

        if self.is_cancelled():
            return False
        if self.has_tag(DONE_TAG):
            return True
        if any(t in DONE_ALIASES for t in self.tags):
            return True
        return self.completed_at is not None

    def is_cancelled(self) -> bool:
        from .tags import CANCEL_ALIASES, CANCEL_TAG

        if self.has_tag(CANCEL_TAG):
            return True
        return any(t in CANCEL_ALIASES for t in self.tags)

    def is_hidden_from_boards(self) -> bool:
        """Скрыта с обычных экранов (только фильтр тега или проект)."""
        return self.is_done() or self.is_cancelled()

    def is_important(self) -> bool:
        from .tags import IMPORTANT_TAG

        return self.has_tag(IMPORTANT_TAG)

    def is_urgent(self) -> bool:
        from .tags import URGENT_TAG

        return self.has_tag(URGENT_TAG)

    def is_inbox(self) -> bool:
        from .tags import INBOX_TAG

        return self.has_tag(INBOX_TAG)

    def is_actual(self) -> bool:
        from .tags import ACTUAL_TAG

        return self.has_tag(ACTUAL_TAG)

    def is_frog(self) -> bool:
        """«Сложная» (🐸) – бывшая лягушка."""
        return self.has_tag("сложная")

    def is_fast(self) -> bool:
        return self.has_tag("быстрая")
