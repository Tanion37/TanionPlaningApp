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


def _save_session(session) -> None:
    if session is None:
        return
    access = getattr(session, "access_token", "") or ""
    refresh = getattr(session, "refresh_token", "") or ""
    if not access or not refresh:
        return
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"access_token": access, "refresh_token": refresh}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _load_tokens() -> tuple[str, str] | None:
    path = _session_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
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


def login(email: str, password: str):
    """Войти по почте и паролю. Дальше запросы идут от этого пользователя."""
    res = supabase.auth.sign_in_with_password(
        {"email": (email or "").strip(), "password": password}
    )
    if res.session is not None:
        _save_session(res.session)
    return res.user


def logout() -> None:
    try:
        supabase.auth.sign_out()
    finally:
        _clear_session()


def restore_session() -> bool:
    """Поднять сохранённую сессию. False — нужен ввод почты и пароля."""
    tokens = _load_tokens()
    if tokens is None:
        return False
    try:
        res = supabase.auth.set_session(tokens[0], tokens[1])
    except Exception:
        _clear_session()
        return False
    if res.session is None or res.user is None:
        _clear_session()
        return False
    _save_session(res.session)
    return True


def fetch_tasks() -> list:
    """Строки tasks, которые RLS отдаёт текущей сессии. Без входа список пуст."""
    res = supabase.table("tasks").select("*").execute()
    return list(res.data or [])
