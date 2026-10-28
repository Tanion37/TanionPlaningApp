"""Обновление рабочей копии из ветки main на GitHub."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/Tanion37/TanionPlaningApp.git"
BRANCH = "main"


def _root() -> Path:
    from .paths import app_root

    return app_root()


def _git(args: list[str], *, timeout: int = 25) -> subprocess.CompletedProcess[str]:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        ["git", *args],
        cwd=_root(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        creationflags=flags,
    )


def update_available() -> bool | None:
    """True — в main есть коммиты, которых нет локально. None — проверить не удалось."""
    root = _root()
    if not (root / ".git").is_dir():
        return None
    try:
        fetched = _git(["fetch", REPO_URL, BRANCH])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if fetched.returncode != 0:
        return None
    try:
        ahead = _git(["rev-list", "--count", f"HEAD..FETCH_HEAD"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ahead.returncode != 0:
        return None
    try:
        count = int((ahead.stdout or "0").strip() or "0")
    except ValueError:
        return None
    return count > 0


def apply_update() -> tuple[bool, str]:
    """Поставить файлы программы на текущий main. data/ не трогает."""
    try:
        fetched = _git(["fetch", REPO_URL, BRANCH], timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Не удалось связаться с GitHub."
    if fetched.returncode != 0:
        return False, "Не удалось связаться с GitHub."
    try:
        fast = _git(["merge", "--ff-only", "FETCH_HEAD"], timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Не удалось обновить приложение."
    if fast.returncode == 0:
        return True, ""
    # Локальная копия разошлась с main. Берём main целиком: задачи в data/ остаются.
    try:
        reset = _git(["reset", "--hard", "FETCH_HEAD"], timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Не удалось обновить приложение."
    if reset.returncode != 0:
        return False, "Не удалось обновить приложение."
    return True, ""


def restart_app() -> None:
    """Запустить эту же копию заново. Текущий процесс закрывает вызывающий код."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=_root(),
        creationflags=flags,
        close_fds=True,
    )
