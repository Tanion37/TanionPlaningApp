"""Интерактивные списки в Telegram: галочки и глаз."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CTX_NAME = "tg_interactive.json"


def _ctx_path() -> Path:
    from .paths import app_root

    folder = app_root() / "data"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / CTX_NAME


def _load_all() -> dict[str, Any]:
    path = _ctx_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_all(data: dict[str, Any]) -> None:
    _ctx_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _key(chat_id: object, message_id: object) -> str:
    return f"{chat_id}:{message_id}"


def save_context(chat_id: object, message_id: object, ctx: dict[str, Any]) -> None:
    data = _load_all()
    data[_key(chat_id, message_id)] = ctx
    _save_all(data)


def load_context(chat_id: object, message_id: object) -> dict[str, Any] | None:
    return _load_all().get(_key(chat_id, message_id))


def api(token: str, method: str, payload: dict | None = None) -> dict:
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


def _mark(done: bool) -> str:
    return "☑" if done else "☐"


def named_list_payload(col, *, hide_done: bool | None = None) -> tuple[str, dict]:
    hide = col.hide_done if hide_done is None else hide_done
    header = col.name
    if col.aliases:
        header = f"{col.name} ({', '.join(col.aliases)})"
    eye = "👁 скрыть сделанное" if not hide else "👁 показать сделанное"
    lines = [header]
    buttons: list[list[dict]] = [[{"text": eye, "callback_data": "il:e"}]]
    shown = 0
    for idx, item in enumerate(col.items):
        if hide and item.done:
            continue
        title = item.text
        if len(title) > 40:
            title = title[:37] + "…"
        lines.append(f"{_mark(item.done)} {item.text}")
        buttons.append(
            [{"text": f"{_mark(item.done)} {title}", "callback_data": f"il:t:{idx}"}]
        )
        shown += 1
        if shown >= 80:
            lines.append("…")
            break
    if shown == 0:
        lines.append("(пусто)" if not col.items else "(все пункты скрыты)")
    return "\n".join(lines), {"inline_keyboard": buttons}


def tasks_payload(
    title: str,
    tasks: list,
    *,
    hide_done: bool,
    group_priority: bool = False,
) -> tuple[str, dict]:
    eye = "👁 скрыть сделанное" if not hide_done else "👁 показать сделанное"
    lines = [title]
    buttons: list[list[dict]] = [[{"text": eye, "callback_data": "il:e"}]]
    shown = 0
    if group_priority:
        from .day_tasks import (
            TELEGRAM_PRIORITY_MARK,
            group_by_telegram_priority,
            telegram_priority_label,
        )

        blocks: list[tuple[str, list]] = group_by_telegram_priority(tasks)
    else:
        blocks = [("", list(tasks))]
        TELEGRAM_PRIORITY_MARK = {}
    first_block = True
    for header, block in blocks:
        visible = [t for t in block if not (hide_done and t.is_done())]
        if header and not visible:
            continue
        if header:
            if not first_block:
                lines.append("")
            mark = TELEGRAM_PRIORITY_MARK.get(header, "")
            lines.append(f"{mark} {header}".strip())
            first_block = False
        for task in visible:
            done = task.is_done()
            name = task.title
            short = name if len(name) <= 40 else name[:37] + "…"
            if group_priority:
                color = TELEGRAM_PRIORITY_MARK.get(telegram_priority_label(task), "")
            else:
                color = TELEGRAM_PRIORITY_MARK.get(header, "") if header else ""
            prefix = f"{color} {_mark(done)}".strip() if color else _mark(done)
            lines.append(f"{prefix} {name}")
            btn = f"{prefix} {short}"
            if len(btn) > 64:
                btn = btn[:61] + "…"
            buttons.append(
                [{"text": btn, "callback_data": f"il:t:{task.id}"}]
            )
            shown += 1
            if shown >= 80:
                lines.append("…")
                break
        if shown >= 80:
            break
    if shown == 0:
        lines.append("(пусто)" if not tasks else "(все пункты скрыты)")
    return "\n".join(lines), {"inline_keyboard": buttons}


def send_tasks_interactive(
    token: str,
    chat_id: object,
    title: str,
    tasks: list,
    ctx: dict,
) -> None:
    hide = bool(ctx.get("hide_done"))
    grouped = bool(ctx.get("group_priority")) or ctx.get("kind") == "executor"
    text, markup = tasks_payload(title, tasks, hide_done=hide, group_priority=grouped)
    ctx = dict(ctx)
    ctx.setdefault("task_ids", [t.id for t in tasks])
    ctx.setdefault("hide_done", hide)
    send_interactive(token, chat_id, text, markup, ctx)


def send_gorit_delaem(
    token: str,
    chat_id: object,
    tasks: list | None = None,
    *,
    greeting: str | None = None,
) -> None:
    from .sorting import screen_triage

    if tasks is None:
        tasks = _xlsx_store().tasks
    cols = dict(screen_triage(tasks))
    if greeting:
        api(token, "sendMessage", {"chat_id": chat_id, "text": greeting})
    for kind, title, key in (
        ("gorit", "🔥 ГОРИТ", "ГОРИТ"),
        ("delaem", "🛠 ДЕЛАЕМ", "ДЕЛАЕМ"),
    ):
        lst = cols.get(key, [])
        send_tasks_interactive(
            token,
            chat_id,
            title,
            lst,
            {"kind": kind, "task_ids": [t.id for t in lst], "hide_done": False},
        )


def send_interactive(token: str, chat_id: object, text: str, markup: dict, ctx: dict) -> None:
    result = api(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text, "reply_markup": markup},
    )
    mid = (result.get("result") or {}).get("message_id")
    if mid is not None:
        save_context(chat_id, mid, ctx)


def edit_interactive(token: str, chat_id: object, message_id: object, text: str, markup: dict, ctx: dict) -> None:
    api(
        token,
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": markup,
        },
    )
    save_context(chat_id, message_id, ctx)


def _xlsx_store():
    from .xlsx_store import TaskStore, default_xlsx_path

    store = TaskStore(default_xlsx_path())
    store.load()
    return store


def _lists_store():
    from .lists_store import ListsStore

    store = ListsStore()
    store.load()
    return store


def _refresh_named(ctx: dict) -> tuple[str, dict]:
    store = _lists_store()
    col = store.resolve(str(ctx.get("list_name") or ""))
    if col is None:
        return "Список не найден.", {"inline_keyboard": []}
    col.hide_done = bool(ctx.get("hide_done"))
    return named_list_payload(col, hide_done=col.hide_done)


def _merge_remembered(live: list, remembered_ids: list[str], by_id: dict) -> list:
    seen = {t.id for t in live}
    extra = [by_id[i] for i in remembered_ids if i in by_id and i not in seen]
    return live + extra


def _tasks_for_ctx(ctx: dict) -> tuple[str, list]:
    from .executors_store import is_own_executor, telegram_username_for
    from .tags import BY_KEY, CANCEL_TAG, DONE_TAG

    store = _xlsx_store()
    ids = [str(i) for i in ctx.get("task_ids") or []]
    by_id = {t.id: t for t in store.tasks}
    kind = ctx.get("kind")
    if kind == "named":
        return "", []
    if kind == "tag":
        key = str(ctx.get("tag_key") or "")
        if key == CANCEL_TAG:
            tasks = [t for t in store.tasks if t.is_cancelled()]
        elif key == DONE_TAG:
            tasks = [t for t in store.tasks if t.is_done()]
        else:
            tasks = [t for t in store.tasks if t.has_tag(key) and not t.is_cancelled()]
        label = BY_KEY[key].symbol if key in BY_KEY else key
        ctx["task_ids"] = [t.id for t in tasks]
        return f"Тег {label} ({key})", tasks
    if kind == "project":
        from .projects import same_project

        name = str(ctx.get("project") or "")
        tasks = [
            t for t in store.tasks if same_project(t.project, name) and not t.is_cancelled()
        ]
        ctx["task_ids"] = [t.id for t in tasks]
        return f"Проект «{name}»", tasks
    if kind in {"gorit", "delaem"}:
        from .sorting import screen_triage

        cols = dict(screen_triage(store.tasks))
        live = cols.get("ГОРИТ" if kind == "gorit" else "ДЕЛАЕМ", [])
        tasks = _merge_remembered(live, ids, by_id)
        ctx["task_ids"] = [t.id for t in tasks]
        return ("🔥 ГОРИТ" if kind == "gorit" else "🛠 ДЕЛАЕМ"), tasks
    if kind == "executor":
        from .day_tasks import executor_sections

        name = str(ctx.get("executor") or "")
        live: list = []
        for section_name, lst in executor_sections(store.tasks):
            if section_name == name:
                live = list(lst)
                break
        tasks = _merge_remembered(live, ids, by_id)
        ctx["task_ids"] = [t.id for t in tasks]
        mention = telegram_username_for(name)
        title = name
        if mention:
            title = f"{name} @{mention.lstrip('@')}"
        return title, tasks
    own = [
        t
        for t in store.tasks
        if is_own_executor(getattr(t, "executor", None))
        and not t.is_cancelled()
        and not t.is_backlog()
    ]
    open_tasks = [t for t in own if not t.is_done()][:40]
    done_tasks = [t for t in own if t.is_done()][:20]
    tasks = open_tasks + done_tasks
    ctx["task_ids"] = [t.id for t in tasks]
    return "Мои задачи", tasks


def _toggle_task(task_id: str) -> None:
    from datetime import date

    from .tags import CANCEL_TAG, DONE_TAG

    store = _xlsx_store()
    task = store.get(task_id)
    if task is None:
        return
    if task.is_done():
        task.remove_tag(DONE_TAG)
        task.completed_at = None
    else:
        task.remove_tag(CANCEL_TAG)
        task.add_tag(DONE_TAG)
        if task.completed_at is None:
            task.completed_at = date.today()
    store.save()
    from .period_roll import spawn_periodic_copies

    created = spawn_periodic_copies(store)
    if created:
        store.save()


def handle_callback_query(token: str, query: dict) -> bool:
    """Обработать callback интерактивного списка. True, если это наш callback."""
    data = str(query.get("data") or "")
    if not data.startswith("il:"):
        return False
    cq_id = query.get("id")
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    try:
        api(token, "answerCallbackQuery", {"callback_query_id": cq_id})
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
        pass
    ctx = load_context(chat_id, message_id)
    if not ctx:
        return True
    if data == "il:e":
        ctx["hide_done"] = not bool(ctx.get("hide_done"))
        if ctx.get("kind") == "named" and ctx.get("list_name"):
            store = _lists_store()
            store.set_hide_done(str(ctx["list_name"]), bool(ctx["hide_done"]))
    elif data.startswith("il:t:"):
        target = data[5:]
        if ctx.get("kind") == "named":
            try:
                idx = int(target)
            except ValueError:
                return True
            store = _lists_store()
            store.toggle_item(str(ctx.get("list_name") or ""), idx)
        else:
            _toggle_task(target)
            if target not in [str(i) for i in ctx.get("task_ids") or []]:
                ids = list(ctx.get("task_ids") or [])
                ids.append(target)
                ctx["task_ids"] = ids
    try:
        if ctx.get("kind") == "named":
            text, markup = _refresh_named(ctx)
        else:
            title, tasks = _tasks_for_ctx(ctx)
            grouped = bool(ctx.get("group_priority")) or ctx.get("kind") == "executor"
            ctx["group_priority"] = grouped
            text, markup = tasks_payload(
                title,
                tasks,
                hide_done=bool(ctx.get("hide_done")),
                group_priority=grouped,
            )
        edit_interactive(token, chat_id, message_id, text, markup, ctx)
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
        pass
    return True
