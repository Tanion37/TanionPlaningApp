"""Вход в Supabase: публичный ключ, сессия и запросы от имени пользователя."""

from __future__ import annotations

import json
import os
from pathlib import Path

from supabase import Client, create_client

# Публичный ключ проекта. service_role сюда не класть: его RLS не останавливает.
SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://ectxmgrywoefnbjvdxff.supabase.co"
SUPABASE_KEY = (
    os.environ.get("SUPABASE_ANON_KEY")
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    or "sb_publishable_ZEFp8AyzLz0bppuNyxkS7A_T5Jh2yzh"
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


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


def _save_session(session, *, email: str = "") -> None:
    if session is None:
        return
    access = getattr(session, "access_token", "") or ""
    refresh = getattr(session, "refresh_token", "") or ""
    if not access or not refresh:
        return
    previous = _load_record() or {}
    kept_email = (email or str(previous.get("email") or "")).strip()
    _write_record(
        {
            "remember": True,
            "email": kept_email,
            "access_token": access,
            "refresh_token": refresh,
        }
    )


def _load_tokens() -> tuple[str, str] | None:
    data = _load_record()
    if not data:
        return None
    access = str(data.get("access_token") or "")
    refresh = str(data.get("refresh_token") or "")
    if not access or not refresh:
        return None
    return access, refresh


def _clear_session() -> None:
    path = _session_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _drop_tokens_keep_mark() -> None:
    """Сервер отклонил токен. Отметка входа остаётся, пароль на диск не пишется."""
    data = _load_record() or {}
    email = str(data.get("email") or "").strip()
    _write_record({"remember": True, "email": email})


def remembered() -> bool:
    """Этот компьютер уже помнит пользователя. Сеть для проверки не нужна."""
    data = _load_record()
    if not data:
        return False
    if "remember" in data:
        return bool(data.get("remember"))
    return bool(data.get("access_token") and data.get("refresh_token"))


def remembered_email() -> str:
    data = _load_record() or {}
    return str(data.get("email") or "").strip()


def has_live_session() -> bool:
    """Сессия уже есть в памяти этого запуска. Сеть не нужна."""
    try:
        return supabase.auth.get_session() is not None
    except Exception:
        return False


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
    status = getattr(exc, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
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
        "session expired",
    )
    if any(marker in text for marker in markers):
        return True
    return status in (400, 401, 403)


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


def login(email: str, password: str, *, remember: bool = False):
    """Войти по почте и паролю. Дальше запросы идут от этого пользователя.

    На диске остаётся отметка и токены, только если отмечено «Запомнить меня».
    Пароль не сохраняется.
    """
    email = (email or "").strip()
    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
    if remember and res.session is not None:
        _save_session(res.session, email=email)
    else:
        _clear_session()
    return res.user


def logout() -> None:
    _clear_session()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass


def refresh_saved_session() -> str:
    """Обновить токены, когда связь есть.

    «ok» — сессия принята. «offline» — связи нет, файл не трогаем.
    «rejected» — сервер отклонил токен, нужен пароль. «absent» — пользователя не запоминали.
    """
    if not remembered():
        return "absent"
    tokens = _load_tokens()
    if tokens is None:
        if _server_reachable():
            return "rejected"
        return "offline"
    try:
        res = supabase.auth.set_session(tokens[0], tokens[1])
    except Exception as exc:
        if _is_auth_rejected(exc):
            _drop_tokens_keep_mark()
            return "rejected"
        return "offline"
    if res.session is None or res.user is None:
        _drop_tokens_keep_mark()
        return "rejected"
    email = getattr(res.user, "email", "") or ""
    _save_session(res.session, email=email)
    return "ok"


def fetch_tasks() -> list:
    """Строки tasks, которые RLS отдаёт текущей сессии. Без входа список пуст."""
    res = supabase.table("tasks").select("*").execute()
    return list(res.data or [])
