"""Напоминание «СДЕЛАТЬ БЭКАП» в ГОРИТ, если снимок в GitHub не удался."""

from __future__ import annotations

from datetime import date

BACKUP_TASK_TITLE = "СДЕЛАТЬ БЭКАП"


def _open_backup_tasks(store) -> list:
    return [
        t
        for t in store.tasks
        if (t.title or "").strip() == BACKUP_TASK_TITLE
        and not t.is_done()
        and not t.is_cancelled()
    ]


def sync_backup_reminder(ok: bool) -> None:
    """ok=True – закрыть открытые «СДЕЛАТЬ БЭКАП»; иначе создать/оставить в ГОРИТ."""
    from .tags import DONE_TAG, URGENT_TAG
    from .xlsx_store import TaskStore, default_xlsx_path

    store = TaskStore(default_xlsx_path())
    store.load()
    today = date.today()
    open_ones = _open_backup_tasks(store)
    changed = False
    if ok:
        for task in open_ones:
            task.remove_tag("отменена")
            if DONE_TAG not in task.tags:
                task.tags.append(DONE_TAG)
            task.completed_at = today
            changed = True
    else:
        if open_ones:
            for task in open_ones:
                if task.due_at != today:
                    task.due_at = today
                    changed = True
                if task.start_at is not None and task.start_at > today:
                    task.start_at = today
                    changed = True
                if URGENT_TAG not in task.tags:
                    task.add_tag(URGENT_TAG)
                    changed = True
        else:
            store.add_task(
                BACKUP_TASK_TITLE,
                start_at=today,
                due_at=today,
                tags=[URGENT_TAG],
                executor="Юра",
                source="backup",
            )
            return
    if changed:
        store.save()
