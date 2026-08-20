"""Отправка списка задач исполнителя в чат студии (TanionTaskBot)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

STUDIO_CHAT_TITLE = "PGD studio AI"


def _config_paths() -> list[Path]:
    from .paths import app_root

    root = app_root()
    parent = root.parent
    seen: set[Path] = set()
    out: list[Path] = []
    for path in (
        root / "config.json",
        parent / "TanionPlaning" / "config.json",
        parent / "PGDstudioBot" / "config.json",
    ):
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _telegram_from_file(path: Path) -> dict:
    data: dict = {}
    try:
        from .tas_secrets import load_resolved_json

        data = load_resolved_json(path)
    except Exception:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    tg = dict(data.get("telegram") or {})
    ttb = data.get("tanion_task_bot") or {}
    if not tg.get("bot_token") and ttb.get("bot_token"):
        tg["bot_token"] = ttb["bot_token"]
    if not tg.get("chat_id") and ttb.get("chat_id"):
        tg["chat_id"] = ttb["chat_id"]
    token = str(tg.get("bot_token") or "").strip()
    if not token or token.startswith("secrets:"):
        return {}
    return tg


def iter_telegram_cfgs() -> list[dict]:
    """Конфиги ботов: сначала секретарь, затем студийный. Токены не логировать."""
    seen: set[str] = set()
    out: list[dict] = []
    for path in _config_paths():
        if not path.is_file():
            continue
        tg = _telegram_from_file(path)
        token = str(tg.get("bot_token") or "")
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(tg)
    return out


def load_telegram_cfg() -> dict:
    cfgs = iter_telegram_cfgs()
    return cfgs[0] if cfgs else {}


def _api(token: str, method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        desc = result.get("description") or result
        raise RuntimeError(str(desc))
    return result


def _chat_ids(tg: dict) -> list[str]:
    ids: list[str] = []
    for raw in tg.get("allowed_chat_ids") or []:
        text = str(raw).strip()
        if text:
            ids.append(text)
    chat_id = str(tg.get("chat_id") or "").strip()
    if chat_id:
        ids.append(chat_id)
    studio = str(tg.get("studio_chat_id") or "").strip()
    if studio:
        ids.append(studio)
    return ids


def resolve_studio_send() -> tuple[str, str]:
    """Токен и chat_id бота, который видит «PGD studio AI»."""
    want = STUDIO_CHAT_TITLE.casefold()
    cfgs = iter_telegram_cfgs()
    if not cfgs:
        raise RuntimeError("Нет токена бота в config.json")
    all_ids: list[str] = []
    for tg in cfgs:
        for chat_id in _chat_ids(tg):
            if chat_id not in all_ids:
                all_ids.append(chat_id)
    for tg in cfgs:
        token = str(tg.get("bot_token") or "").strip()
        if not token:
            continue
        seen: set[str] = set()
        for chat_id in all_ids:
            if chat_id in seen:
                continue
            seen.add(chat_id)
            try:
                info = _api(token, "getChat", {"chat_id": chat_id})
            except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
                continue
            result = info.get("result") or {}
            title = str(result.get("title") or result.get("username") or "").strip()
            if title.casefold() == want or want in title.casefold():
                return token, str(result.get("id") or chat_id)
    raise RuntimeError(
        f"Чат «{STUDIO_CHAT_TITLE}» не найден. "
        "Нужен бот, который состоит в этом чате."
    )


def format_executor_list(executor: str, tasks: list, mention: str) -> str:
    from .day_tasks import TELEGRAM_PRIORITY_MARK, group_by_telegram_priority, non_system_tags_of
    from .tags import tags_to_cell

    head = executor.strip() or "Исполнитель"
    if mention:
        head = f"{head} @{mention.lstrip('@')}"
    if not tasks:
        return f"{head}\n(пусто)"
    lines = [head]
    for header, block in group_by_telegram_priority(tasks):
        if not block:
            continue
        mark = TELEGRAM_PRIORITY_MARK.get(header, "")
        lines.append(f"{mark} {header}".strip())
        for task in block:
            line = f"{mark} ☐ {task.title}".strip()
            tags = tags_to_cell(non_system_tags_of(task))
            if tags:
                line += f"  {tags}"
            lines.append(line)
    return "\n".join(lines)


def send_executor_tasks(executor: str, tasks: list) -> str:
    """Отправить список. Вернуть текст, который ушёл в чат."""
    from .executors_store import telegram_username_for
    from .telegram_lists import send_interactive, tasks_payload

    token, chat_id = resolve_studio_send()
    mention = telegram_username_for(executor)
    title = executor.strip() or "Исполнитель"
    if mention:
        title = f"{title} @{mention.lstrip('@')}"
    text, markup = tasks_payload(
        title, tasks, hide_done=False, group_priority=True
    )
    send_interactive(
        token,
        chat_id,
        text,
        markup,
        {
            "kind": "executor",
            "executor": executor,
            "task_ids": [t.id for t in tasks],
            "hide_done": False,
            "group_priority": True,
        },
    )
    return text
