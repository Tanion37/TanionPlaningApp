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


def _app_needs_update() -> bool | None:
    """Сравнить каталог app на диске с FETCH_HEAD. Ветку репозитория не двигает."""
    diff = _git(["diff", "--quiet", "FETCH_HEAD", "--", "app"])
    if diff.returncode == 0:
        return False
    if diff.returncode == 1:
        return True
    return None


def update_available() -> bool | None:
    """True — в публичном main другой каталог app. None — проверить не удалось."""
    root = _root()
    if not (root / ".git").is_dir():
        return None
    try:
        fetched = _git(["fetch", REPO_URL, BRANCH])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if fetched.returncode != 0:
        return None
    return _app_needs_update()


def apply_update() -> tuple[bool, str]:
    """Записать в рабочую копию только каталог app. data/ и ветку не трогает."""
    try:
        fetched = _git(["fetch", REPO_URL, BRANCH], timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Не удалось связаться с GitHub."
    if fetched.returncode != 0:
        return False, "Не удалось связаться с GitHub."
    try:
        restored = _git(
            ["restore", "--source=FETCH_HEAD", "--worktree", "--", "app"],
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Не удалось обновить приложение."
    if restored.returncode != 0:
        return False, (restored.stderr or restored.stdout or "Не удалось обновить приложение.").strip()
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
