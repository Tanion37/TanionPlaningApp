"""Список исполнителей (xlsx-вкладка executors)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .xlsx_io import load_workbook_retry, save_workbook_atomic, xlsx_write_lock
from .xlsx_store import default_xlsx_path

SHEET_NAME = "executors"
DEFAULT_EXECUTOR = "Юра"
DEFAULT_EXECUTORS: tuple[str, ...] = (DEFAULT_EXECUTOR, "Лёша", "Саша", "Сойер")
DEMO_EXECUTORS: tuple[str, ...] = ("Кот", "Кактус", "Дракон", "Чайник")

# Telegram @username для отправки списка в чат студии (без @).
# Личные ники – в config.json → executor_telegram, не в публичном коде.
EXECUTOR_TELEGRAM: dict[str, str] = {}


def normalize_executor_name(name: str | None) -> str:
    return (name or "").strip().casefold().replace("ё", "е")


def is_own_executor(name: str | None) -> bool:
    """Пустой исполнитель или Юра / Юрий — задача владельца, без отдельного раздела."""
    text = (name or "").strip()
    if not text:
        return True
    key = normalize_executor_name(text)
    return key in {"юра", "юрий"} or key.startswith("юрий ")


# Чужие входящие: колонка «Входящие», но не у всех аккаунтов.
DELEGATED_INBOX_EXECUTORS: tuple[str, ...] = ("Саша", "Лёша", "Владислав", "Сойер")

# Назначил задачу одному из них — видит её во входящих вместе с исполнителем.
# Вторая почта — вход на этом компьютере, тот же назначающий.
INBOX_ASSIGNER_EMAILS: frozenset[str] = frozenset(
    {
        "yury@nxt.ru",
        "proboardgamedesign@yandex.ru",
    }
)

# Почта входа исполнителя → его имя. Такой аккаунт видит только свои входящие.
INBOX_EXECUTOR_EMAILS: dict[str, str] = {}


def _email_key(email: str | None) -> str:
    return (email or "").strip().casefold()


def is_delegated_inbox_executor(name: str | None) -> bool:
    key = normalize_executor_name(name)
    return any(key == normalize_executor_name(item) for item in DELEGATED_INBOX_EXECUTORS)


def current_login_email() -> str:
    from .supa import current_email

    return current_email().strip()


def is_inbox_assigner(email: str | None) -> bool:
    key = _email_key(email)
    return any(key == _email_key(item) for item in INBOX_ASSIGNER_EMAILS)


def delegated_inbox_visible(task, email: str | None = None) -> bool:
    """Входящую Саши, Лёши, Владислава или Сойера видит этот исполнитель и тот, кто её назначил."""
    if not is_delegated_inbox_executor(getattr(task, "executor", "")):
        return False
    viewer = current_login_email() if email is None else email
    key = _email_key(viewer)
    mapped = INBOX_EXECUTOR_EMAILS.get(key, "")
    if mapped and normalize_executor_name(mapped) == normalize_executor_name(getattr(task, "executor", "")):
        return True
    if not is_inbox_assigner(key):
        return False
    assigned = _email_key(getattr(task, "assigned_by", ""))
    if not assigned:
        return True
    return is_inbox_assigner(assigned)


def inbox_executor_visible(task, email: str | None = None) -> bool:
    if is_own_executor(getattr(task, "executor", None)):
        return True
    return delegated_inbox_visible(task, email)


def shown_on_boards(task, email: str | None = None) -> bool:
    """Чужая входящая не показывается на экранах, если этот вход её не видит."""
    if not getattr(task, "is_inbox", lambda: False)() or task.is_actual() or task.is_control():
        return True
    if not is_delegated_inbox_executor(getattr(task, "executor", "")):
        return True
    return delegated_inbox_visible(task, email)


def remember_inbox_assigner(task, previous: str = "") -> None:
    """Запомнить почту, которая поставила исполнителя Саше, Лёше, Владиславу или Сойеру."""
    if not is_delegated_inbox_executor(getattr(task, "executor", "")):
        return
    email = current_login_email()
    if not email:
        return
    current = (getattr(task, "executor", "") or "").strip()
    if (previous or "").strip() == current and (getattr(task, "assigned_by", "") or "").strip():
        return
    task.assigned_by = email


def telegram_username_for(name: str | None) -> str:
    import json

    key = normalize_executor_name(name)
    mapped = dict(EXECUTOR_TELEGRAM)
    try:
        from .paths import app_root

        cfg_path = app_root() / "config.json"
        if cfg_path.is_file():
            extra = json.loads(cfg_path.read_text(encoding="utf-8")).get("executor_telegram") or {}
            if isinstance(extra, dict):
                for raw_name, username in extra.items():
                    mapped[normalize_executor_name(str(raw_name))] = str(username).lstrip("@")
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return mapped.get(key, "")


class ExecutorsStore:
    def __init__(self, xlsx_path: Path | None = None) -> None:
        self.path = xlsx_path or default_xlsx_path()
        self.names: list[str] = []

    def load(self) -> list[str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.names = list(DEFAULT_EXECUTORS)
            self.save()
            return list(self.names)

        wb = load_workbook_retry(self.path, data_only=True)
        if SHEET_NAME not in wb.sheetnames:
            self.names = list(DEFAULT_EXECUTORS)
            self.save()
            return list(self.names)

        ws = wb[SHEET_NAME]
        names: list[str] = []
        for row in ws.iter_rows(values_only=True):
            if not row:
                continue
            val = row[0]
            if val is None or str(val).strip() == "":
                continue
            text = str(val).strip()
            if text.casefold() in {"исполнитель", "исполнители", "name", "имя"}:
                continue
            if text not in names:
                names.append(text)
        if not names:
            names = list(DEFAULT_EXECUTORS)
            self.names = names
            self.save()
            return list(self.names)
        if not any(n.casefold() == DEFAULT_EXECUTOR.casefold() for n in names):
            names = [DEFAULT_EXECUTOR, *names]
            self.names = names
            self.save()
            return list(self.names)
        self.names = names
        return list(self.names)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with xlsx_write_lock(self.path):
            if self.path.exists():
                wb = load_workbook_retry(self.path)
            else:
                wb = Workbook()
                default = wb.active
                default.title = "tasks"
                from .xlsx_store import COLUMNS

                default.append(list(COLUMNS))

            if SHEET_NAME in wb.sheetnames:
                del wb[SHEET_NAME]
            ws = wb.create_sheet(SHEET_NAME)
            ws.append(["исполнитель"])
            for name in self.names:
                ws.append([name])
            save_workbook_atomic(wb, self.path)

    def add(self, name: str) -> tuple[bool, str]:
        from .lists_store import split_semicolon_items

        parts = split_semicolon_items(name)
        if not parts:
            return False, "Пустое имя."
        added = False
        for text in parts:
            if any(n.casefold() == text.casefold() for n in self.names):
                continue
            self.names.append(text)
            added = True
        if not added:
            return False, "already"
        self.save()
        return True, ""

    def remove(self, name: str) -> bool:
        key = (name or "").strip().casefold()
        before = len(self.names)
        self.names = [n for n in self.names if n.casefold() != key]
        if len(self.names) == before:
            return False
        self.save()
        return True
