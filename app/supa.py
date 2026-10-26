"""Вход в Supabase: публичный ключ, сессия и запросы от имени пользователя."""

from __future__ import annotations

import json
import os
from pathlib import Path

from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

# Публичный ключ проекта. service_role сюда не класть: его RLS не останавливает.
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://ectxmgrywoefnbjvdxff.supabase.co"
SUPABASE_KEY = (
    os.environ.get("SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    or "sb_publishable_ZEFp8AyzLz0bppuNyxkS7A_T5Jh2yzh"
)

class _SessionStorage:
    """Диск для «Запомнить меня». Библиотека сама пишет сюда новый refresh-токен."""

    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        self.remember = False
        self.email = ""

    def get_item(self, key: str) -> str | None:
        cached = self._memory.get(key)
        if cached:
            return cached
        if self._memory and not self.remember:
            return next(iter(self._memory.values()))
        data = _load_record() or {}
        if not data.get("remember"):
            return None
        raw = data.get("session")
        if isinstance(raw, dict):
            text = json.dumps(raw, ensure_ascii=False)
        else:
            text = str(raw or "")
        if not text.strip():
            return None
        self._memory[key] = text
        self.remember = True
        self.email = str(data.get("email") or self.email)
        return text

    def set_item(self, key: str, value: str) -> None:
        self._memory = {key: value}
        found = _email_from_session(value)
        if found:
            self.email = found
        if not self.remember:
            _clear_session()
            return
        _write_record(
            {
                "remember": True,
                "email": self.email,
                "session": value,
            }
        )

    def remove_item(self, key: str) -> None:
        self._memory.pop(key, None)
        if not self._memory:
            _clear_session()


_storage = _SessionStorage()


def _session_path() -> Path:
    from .paths import app_root

    return app_root() / "data" / "supabase_session.json"


def _load_record() -> dict | None:
    path = _session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_record(data: dict) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


def _email_from_session(raw: str) -> str:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    user = data.get("user") if isinstance(data, dict) else None
    if isinstance(user, dict):
        return str(user.get("email") or "").strip()
    return ""


def _stored_refresh(data: dict | None = None) -> str:
    record = data if data is not None else (_load_record() or {})
    raw = record.get("session")
    parsed: dict | None = None
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            parsed = loaded
    if isinstance(parsed, dict) and parsed.get("refresh_token"):
        return str(parsed["refresh_token"])
    return str(record.get("refresh_token") or "")


def _session_text(session) -> str:
    import time

    if hasattr(session, "model_dump_json"):
        raw = session.model_dump_json()
    else:
        raw = json.dumps(
            {
                "access_token": getattr(session, "access_token", "") or "",
                "refresh_token": getattr(session, "refresh_token", "") or "",
                "expires_in": int(getattr(session, "expires_in", 0) or 3600),
                "expires_at": getattr(session, "expires_at", None),
                "token_type": getattr(session, "token_type", "") or "bearer",
                "user": {"email": _storage.email},
            },
            ensure_ascii=False,
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, dict) and not data.get("expires_at"):
        data["expires_at"] = int(time.time()) + int(data.get("expires_in") or 3600)
        raw = json.dumps(data, ensure_ascii=False)
    return raw


def _clear_session() -> None:
    path = _session_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _drop_tokens_keep_mark() -> None:
    """Сервер отклонил refresh-токен. Почта на диске остаётся, пароль не пишется."""
    email = _storage.email or str((_load_record() or {}).get("email") or "").strip()
    _storage._memory.clear()
    _storage.email = email
    _storage.remember = True
    _write_record({"remember": True, "email": email})


def remembered() -> bool:
    """Есть сохранённый refresh-токен. Сеть для проверки не нужна."""
    data = _load_record()
    if not data:
        return False
    if "remember" in data and not data.get("remember"):
        return False
    return bool(_stored_refresh(data))


def remembered_email() -> str:
    data = _load_record() or {}
    return str(data.get("email") or "").strip()


def current_email() -> str:
    """Почта текущего входа. Сеть не нужна."""
    if (_storage.email or "").strip():
        return _storage.email.strip()
    found = _email_from_session(next(iter(_storage._memory.values()), ""))
    if found:
        return found
    return remembered_email()


def has_live_session() -> bool:
    """Сессия есть в памяти или в файле «Запомнить меня». Сеть не нужна."""
    if _storage._memory:
        return True
    return remembered()


def _is_network_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__.casefold()
        if any(part in name for part in ("timeout", "connect", "network", "retryable")):
            return True
        text = str(current).casefold()
        if any(
            part in text
            for part in (
                "timed out",
                "timeout",
                "connection",
                "network",
                "unreachable",
                "getaddrinfo",
                "name or service not known",
                "temporary failure",
                "failed to establish",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def _is_auth_rejected(exc: BaseException) -> bool:
    """Сервер ответил, что сессию обновить нельзя. Обрыв связи сюда не входит."""
    if _is_network_error(exc):
        return False
    text = " ".join(
        str(part or "")
        for part in (getattr(exc, "code", ""), getattr(exc, "message", ""), exc)
    ).casefold()
    markers = (
        "invalid_grant",
        "invalid refresh",
        "refresh_token_not_found",
        "refresh token not found",
        "refresh token is not valid",
        "session_not_found",
        "session not found",
    )
    if any(marker in text for marker in markers):
        return True
    return False


def _server_reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(SUPABASE_URL, timeout=4)
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False
    return True


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
    options=SyncClientOptions(
        storage=_storage,
        auto_refresh_token=True,
        persist_session=True,
    ),
)


def login(email: str, password: str, *, remember: bool = False):
    """Войти по почте и паролю. Дальше запросы идут от этого пользователя.

    На диске остаётся сессия, только если отмечено «Запомнить меня».
    Пароль не сохраняется. Новый refresh-токен библиотека пишет в тот же файл.
    """
    email = (email or "").strip()
    _storage.email = email
    _storage.remember = bool(remember)
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    if res.session is not None:
        key = next(iter(_storage._memory), "session")
        _storage.set_item(key, _session_text(res.session))
    if not remember:
        _storage.remember = False
        _clear_session()
    return res.user


def logout() -> None:
    """Отозвать сессию на сервере и забыть её на этом компьютере."""
    _storage.remember = False
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    _storage._memory.clear()
    _storage.email = ""
    _clear_session()


def discard_if_not_remembered() -> None:
    """Обычное закрытие окна не вызывает sign_out. Без галочки файл сессии убирается."""
    if _storage.remember or remembered():
        return
    _clear_session()


def refresh_saved_session() -> str:
    """Обновить access-токен по сохранённому refresh-токену.

    «ok» — сессия принята, новый refresh-токен уже на диске.
    «offline» — связи нет, файл не трогаем.
    «rejected» — сервер отклонил именно refresh-токен, нужен пароль.
    «absent» — пользователя не запоминали.
    """
    if not remembered() and not _storage._memory:
        return "absent"
    try:
        session = supabase.auth.get_session()
    except Exception as exc:
        if _is_auth_rejected(exc):
            _drop_tokens_keep_mark()
            return "rejected"
        return "offline"
    if session is None:
        if remembered() and _server_reachable():
            return "rejected"
        if remembered():
            return "offline"
        return "absent"
    return "ok"


def fetch_tasks() -> list:
    """Строки tasks, которые RLS отдаёт текущей сессии. Без входа список пуст."""
    res = supabase.table("tasks").select("*").execute()
    return list(res.data or [])
