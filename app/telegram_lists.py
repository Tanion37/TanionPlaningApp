"""Интерактивные списки в Telegram: описание, Готово!, синхронизация."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CTX_NAME = "tg_interactive.json"
MAX_TASK_ROWS = 48
ALERT_LIMIT = 200
SYNC_BTN = "Засинхронить"
DONE_BTN = "Готово!"
NEW_PREFIX = "🔴 NEW"
NEW_HTML = "🔴 <b>NEW</b>"
_URL_RE = re.compile(
    r"(https?://[^\s<>]+|www\.[^\s<>]+|t\.me/[^\s<>]+)",
    re.IGNORECASE,
)


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


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _clip_btn(text: str) -> str:
    if len(text) <= 64:
        return text
    return text[:61] + "…"


def _linkify_html(text: str) -> str:
    """Экранировать текст и обернуть URL в <a href>."""
    parts: list[str] = []
    pos = 0
    for match in _URL_RE.finditer(text):
        parts.append(_esc(text[pos : match.start()]))
        raw = match.group(0)
        trail = ""
        while raw and raw[-1] in ".,);]}>\"'":
            trail = raw[-1] + trail
            raw = raw[:-1]
        href = raw
        low = href.casefold()
        if low.startswith("www.") or low.startswith("t.me/"):
            href = "https://" + href
        parts.append(f'<a href="{_esc(href).replace(chr(34), "&quot;")}">{_esc(raw)}</a>')
        parts.append(_esc(trail))
        pos = match.end()
    parts.append(_esc(text[pos:]))
    return "".join(parts)


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
    pending_done_ids: list | None = None,
    new_ids: list | None = None,
    report_button: bool = False,
    sync_button: bool | None = None,
) -> tuple[str, dict]:
    eye = "👁 скрыть сделанное" if not hide_done else "👁 показать сделанное"
    pending = {str(i) for i in (pending_done_ids or [])}
    fresh = {str(i) for i in (new_ids or [])}
    show_sync = sync_button if sync_button is not None else True
    if report_button:
        show_sync = True
    lines = [_esc(title)]
    buttons: list[list[dict]] = [[{"text": eye, "callback_data": "il:e"}]]
    if show_sync:
        buttons.append([{"text": SYNC_BTN, "callback_data": "il:r"}])
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
            lines.append(_esc(header))
            first_block = False
        for task in visible:
            tid = str(task.id)
            done = task.is_done() or tid in pending
            is_new = tid in fresh and not done
            name = task.title
            short = name if len(name) <= 28 else name[:25] + "…"
            if group_priority:
                color = TELEGRAM_PRIORITY_MARK.get(telegram_priority_label(task), "")
            else:
                color = TELEGRAM_PRIORITY_MARK.get(header, "") if header else ""
            prefix = f"{color} {_mark(done)}".strip() if color else _mark(done)
            new_html = f"{NEW_HTML} " if is_new else ""
            lines.append(f"{new_html}{prefix} {_esc(name)}")
            btn_core = f"{prefix} {short}"
            btn = _clip_btn(f"{NEW_PREFIX} {btn_core}" if is_new else btn_core)
            row = [{"text": btn, "callback_data": f"il:t:{tid}"}]
            if not done:
                row.append({"text": DONE_BTN, "callback_data": f"il:d:{tid}"})
            buttons.append(row)
            shown += 1
            if shown >= MAX_TASK_ROWS:
                lines.append("…")
                break
        if shown >= MAX_TASK_ROWS:
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
) -> str:
    hide = bool(ctx.get("hide_done"))
    grouped = bool(ctx.get("group_priority")) or ctx.get("kind") in {
        "executor",
        "priority",
    }
    ids = [t.id for t in tasks]
    ctx = dict(ctx)
    ctx["title"] = title
    ctx.setdefault("task_ids", ids)
    ctx.setdefault("synced_ids", list(ctx.get("task_ids") or ids))
    ctx.setdefault("new_ids", [])
    ctx.setdefault("hide_done", hide)
    ctx["group_priority"] = grouped
    text, markup = tasks_payload(
        title,
        tasks,
        hide_done=hide,
        group_priority=grouped,
        pending_done_ids=ctx.get("pending_done_ids") or [],
        new_ids=ctx.get("new_ids") or [],
        sync_button=True,
    )
    send_interactive(token, chat_id, text, markup, ctx, parse_mode="HTML")
    return text


def _priority_live(tasks: list | None = None) -> list:
    from .day_hide import without_hidden
    from .day_tasks import priority_tasks_flat

    if tasks is None:
        tasks = _xlsx_store().tasks
    return priority_tasks_flat(without_hidden(tasks))


def send_priority_digest(
    token: str,
    chat_id: object,
    tasks: list | None = None,
    *,
    greeting: str | None = None,
) -> None:
    """Приоритет в форме списка исполнителю: ГОРЯЩЕЕ / НУЖНО / МОЖНО и кружки."""
    lst = _priority_live(tasks)
    title = greeting or "Приоритет"
    send_tasks_interactive(
        token,
        chat_id,
        title,
        lst,
        {
            "kind": "priority",
            "title": title,
            "task_ids": [t.id for t in lst],
            "hide_done": False,
            "group_priority": True,
        },
    )


def send_gorit_delaem(
    token: str,
    chat_id: object,
    tasks: list | None = None,
    *,
    greeting: str | None = None,
) -> None:
    """Совместимость: утро и /today шлют Приоритет, не колонки ГОРИТ/ДЕЛАЕМ."""
    send_priority_digest(token, chat_id, tasks, greeting=greeting)


def send_interactive(
    token: str,
    chat_id: object,
    text: str,
    markup: dict,
    ctx: dict,
    *,
    parse_mode: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": markup,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = api(token, "sendMessage", payload)
    mid = (result.get("result") or {}).get("message_id")
    if mid is not None:
        save_context(chat_id, mid, ctx)


def edit_interactive(
    token: str,
    chat_id: object,
    message_id: object,
    text: str,
    markup: dict,
    ctx: dict,
    *,
    parse_mode: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "reply_markup": markup,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    api(token, "editMessageText", payload)
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


def _parse_mode_for(ctx: dict) -> str | None:
    if ctx.get("kind") == "named":
        return None
    return "HTML"


def _live_tasks_for_ctx(ctx: dict) -> tuple[str, list]:
    """Актуальные задачи этого вида списка. ctx.task_ids не меняет."""
    from .executors_store import is_own_executor, telegram_username_for
    from .tags import BY_KEY, CANCEL_TAG, DONE_TAG

    store = _xlsx_store()
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
        return f"Тег {label} ({key})", tasks
    if kind == "project":
        from .projects import same_project

        name = str(ctx.get("project") or "")
        tasks = [
            t for t in store.tasks if same_project(t.project, name) and not t.is_cancelled()
        ]
        return f"Проект «{name}»", tasks
    if kind == "priority":
        return str(ctx.get("title") or "Приоритет"), _priority_live(store.tasks)
    if kind in {"gorit", "delaem"}:
        from .sorting import screen_triage

        cols = dict(screen_triage(store.tasks))
        live = cols.get("ГОРИТ" if kind == "gorit" else "ДЕЛАЕМ", [])
        return ("🔥 ГОРИТ" if kind == "gorit" else "🛠 ДЕЛАЕМ"), live
    if kind == "executor":
        from .day_tasks import executor_sections

        name = str(ctx.get("executor") or "")
        live: list = []
        for section_name, lst in executor_sections(store.tasks):
            if section_name == name:
                live = list(lst)
                break
        mention = telegram_username_for(name)
        title = name
        if mention:
            title = f"{name} @{mention.lstrip('@')}"
        return title, live
    own = [
        t
        for t in store.tasks
        if is_own_executor(getattr(t, "executor", None))
        and not t.is_cancelled()
        and not t.is_backlog()
    ]
    open_tasks = [t for t in own if not t.is_done()][:40]
    done_tasks = [t for t in own if t.is_done()][:20]
    return "Мои задачи", open_tasks + done_tasks


def _tasks_for_display(ctx: dict) -> tuple[str, list]:
    """Задачи, которые сейчас в сообщении (снимок до Засинхронить)."""
    store = _xlsx_store()
    by_id = {t.id: t for t in store.tasks}
    ids = [str(i) for i in ctx.get("task_ids") or []]
    tasks = [by_id[i] for i in ids if i in by_id]
    title = str(ctx.get("title") or "")
    if not title:
        title, _live = _live_tasks_for_ctx(ctx)
        ctx["title"] = title
    return title, tasks


def _spawn_after_save(store) -> None:
    from .period_roll import spawn_periodic_copies

    _created, changed = spawn_periodic_copies(store)
    if changed:
        store.save()


def _mark_own_done(task_id: str) -> str:
    from datetime import date

    from .tags import CANCEL_TAG, DONE_TAG

    store = _xlsx_store()
    task = store.get(task_id)
    if task is None:
        return "Задача не найдена"
    if task.is_done():
        return "Уже сделана"
    task.remove_tag(CANCEL_TAG)
    task.add_tag(DONE_TAG)
    if task.completed_at is None:
        task.completed_at = date.today()
    store.save()
    _spawn_after_save(store)
    return "Записано в таблицу"


def _complete_executor_task(task_id: str) -> str:
    """Контрольная копия на Юру, оригинал — выполнена. Сразу в xlsx."""
    from .executors_store import DEFAULT_EXECUTOR
    from .models import Task
    from .tags import CANCEL_TAG, DONE_TAG, control_followup_tags
    from .xlsx_store import _next_id, _normalize_tag_list, now_date

    store = _xlsx_store()
    task = store.get(task_id)
    if task is None:
        return "Задача не найдена"
    if task.is_done() or task.is_cancelled():
        return "Уже сделана"
    today = now_date()
    follow = Task(
        id=_next_id(store.tasks),
        title=task.title,
        created_at=today,
        completed_at=None,
        start_at=today,
        due_at=task.due_at,
        remind_at=None,
        remind_time="",
        remind_period="",
        author=task.author,
        executor=DEFAULT_EXECUTOR,
        project=task.project,
        description=task.description,
        tags=_normalize_tag_list(control_followup_tags(task.tags)),
        source="telegram",
        series_id="",
    )
    store.tasks.append(follow)
    task.remove_tag(CANCEL_TAG)
    task.add_tag(DONE_TAG)
    if task.completed_at is None:
        task.completed_at = today
    store.save()
    _spawn_after_save(store)
    return "Записано в таблицу"


def _complete_task(ctx: dict, task_id: str) -> str:
    if ctx.get("kind") == "executor":
        return _complete_executor_task(task_id)
    return _mark_own_done(task_id)


def _sync_list(ctx: dict) -> str:
    """Скрыть сделанные, подтянуть новые, пометить NEW. Старые pending — в таблицу."""
    flushed = 0
    pending = [str(i) for i in ctx.get("pending_done_ids") or []]
    if ctx.get("kind") == "executor" and pending:
        for tid in pending:
            msg = _complete_executor_task(tid)
            if msg.startswith("Записано"):
                flushed += 1
        ctx["pending_done_ids"] = []
    title, live = _live_tasks_for_ctx(ctx)
    prev = {str(i) for i in ctx.get("synced_ids") or ctx.get("task_ids") or []}
    live_ids = [t.id for t in live]
    new_ids = [i for i in live_ids if i not in prev]
    ctx["title"] = title
    ctx["task_ids"] = live_ids
    ctx["synced_ids"] = live_ids
    ctx["new_ids"] = new_ids
    ctx["hide_done"] = True
    parts = ["Список обновлён"]
    if flushed:
        parts.append(f"сделано: {flushed}")
    if new_ids:
        parts.append(f"новых: {len(new_ids)}")
    return ", ".join(parts)


def _rebuild_payload(ctx: dict) -> tuple[str, dict]:
    if ctx.get("kind") == "named":
        return _refresh_named(ctx)
    title, tasks = _tasks_for_display(ctx)
    grouped = bool(ctx.get("group_priority")) or ctx.get("kind") in {
        "executor",
        "priority",
    }
    ctx["group_priority"] = grouped
    return tasks_payload(
        title,
        tasks,
        hide_done=bool(ctx.get("hide_done")),
        group_priority=grouped,
        pending_done_ids=ctx.get("pending_done_ids") or [],
        new_ids=ctx.get("new_ids") or [],
        sync_button=True,
    )


def _answer_callback(
    token: str,
    cq_id: object,
    text: str | None = None,
    *,
    alert: bool = False,
) -> None:
    payload: dict[str, Any] = {"callback_query_id": cq_id}
    if text:
        payload["text"] = text[:ALERT_LIMIT]
        if alert:
            payload["show_alert"] = True
    try:
        api(token, "answerCallbackQuery", payload)
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
        pass


def _show_description(
    token: str,
    cq_id: object,
    chat_id: object,
    message_id: object,
    task_id: str,
    ctx: dict,
) -> None:
    store = _xlsx_store()
    task = store.get(task_id)
    if task is None:
        _answer_callback(token, cq_id, "Задача не найдена")
        return
    desc = (getattr(task, "description", None) or "").strip()
    if not desc:
        _answer_callback(token, cq_id, "Нет описания")
        return
    body = f"<b>{_esc(task.title)}</b>\n\n{_linkify_html(desc)}"
    if len(body) > 4000:
        body = body[:3999] + "…"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": body,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    desc_mid = ctx.get("desc_message_id")
    sent = False
    if desc_mid is not None:
        try:
            api(
                token,
                "editMessageText",
                {**payload, "message_id": desc_mid},
            )
            sent = True
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
            sent = False
    if not sent:
        payload["reply_to_message_id"] = message_id
        try:
            result = api(token, "sendMessage", payload)
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
            _answer_callback(token, cq_id, f"{task.title}\n\n{desc}"[:ALERT_LIMIT], alert=True)
            return
        mid = (result.get("result") or {}).get("message_id")
        if mid is not None:
            ctx["desc_message_id"] = mid
            save_context(chat_id, message_id, ctx)
    _answer_callback(token, cq_id)


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
        return _handle_list_callback(token, data, cq_id, chat_id, message_id)
    except Exception:
        _answer_callback(token, cq_id, "Не удалось обновить задачу")
        raise


def _handle_list_callback(
    token: str,
    data: str,
    cq_id: object,
    chat_id: object,
    message_id: object,
) -> bool:
    ctx = load_context(chat_id, message_id)
    if not ctx:
        _answer_callback(token, cq_id)
        return True
    toast: str | None = None
    if data in {"il:r", "il:s"}:
        toast = _sync_list(ctx)
    elif data == "il:e":
        ctx["hide_done"] = not bool(ctx.get("hide_done"))
        if ctx.get("kind") == "named" and ctx.get("list_name"):
            store = _lists_store()
            store.set_hide_done(str(ctx["list_name"]), bool(ctx["hide_done"]))
    elif data.startswith("il:d:"):
        target = data[5:]
        toast = _complete_task(ctx, target)
        ids = [str(i) for i in ctx.get("task_ids") or []]
        if target not in ids:
            ids.append(target)
            ctx["task_ids"] = ids
    elif data.startswith("il:t:"):
        target = data[5:]
        if ctx.get("kind") == "named":
            try:
                idx = int(target)
            except ValueError:
                _answer_callback(token, cq_id)
                return True
            store = _lists_store()
            store.toggle_item(str(ctx.get("list_name") or ""), idx)
        else:
            _show_description(token, cq_id, chat_id, message_id, target, ctx)
            return True
    else:
        _answer_callback(token, cq_id)
        return True
    _answer_callback(token, cq_id, toast)
    try:
        text, markup = _rebuild_payload(ctx)
        edit_interactive(
            token,
            chat_id,
            message_id,
            text,
            markup,
            ctx,
            parse_mode=_parse_mode_for(ctx),
        )
    except (urllib.error.URLError, RuntimeError, TimeoutError, OSError):
        pass
    return True
