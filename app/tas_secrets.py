"""Резолв ссылок secrets:… через канон TAS secrets_store.py."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any


def _store_path() -> Path:
    env = (os.environ.get("TANION_AGENT_SETTINGS") or "").strip()
    candidates = []
    if env:
        candidates.append(Path(env) / "secrets_store.py")
    candidates.extend(
        [
            Path(r"D:\CURSOR\TanionAgentSetting") / "secrets_store.py",
            Path(r"C:\CURSOR\TanionAgentSetting") / "secrets_store.py",
            Path(__file__).resolve().parents[1] / "TanionAgentSetting" / "secrets_store.py",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Нет TanionAgentSetting/secrets_store.py. Нужен локальный TAS."
    )


def _mod():
    path = _store_path()
    spec = importlib.util.spec_from_file_location("tas_secrets_store", path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_resolved_json(path: str | Path) -> dict[str, Any]:
    return _mod().load_resolved_json(path)


def resolve_tree(obj: Any) -> Any:
    return _mod().resolve_tree(obj)
