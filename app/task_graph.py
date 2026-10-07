"""Граф задач: карточка — узел, after_ids — узлы сразу после неё."""

from __future__ import annotations

from datetime import date

from .activity_log import snapshot_dict
from .models import Task
from .roles import coerce_role

FOLLOWER_MAX = 15
CHAIN_TITLE = "Новая задача"


def parse_id_list(value: object) -> list[str]:
    if value is None or value == "":
        return []
    text = str(value).strip()
    if not text:
        return []
    parts: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        item = chunk.strip()
        if item and item not in parts:
            parts.append(item)
    return parts


def dump_id_list(ids: list[str]) -> str:
    return ",".join(item for item in ids if item)


def parse_count(value: object) -> int:
    if value is None or value == "":
        return 0
    try:
        count = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(FOLLOWER_MAX, count))


def reconcile_links(tasks: list[Task]) -> bool:
    """Убрать битые ссылки. True, если список узлов изменился."""
    by_id = {task.id: task for task in tasks}
    changed = False
    for task in tasks:
        task.role = coerce_role(task.role)
        kept = [tid for tid in task.after_ids if tid in by_id and tid != task.id]
        if kept != list(task.after_ids):
            task.after_ids = kept
            changed = True
        if task.after_ids and task.after_count != len(task.after_ids):
            task.after_count = len(task.after_ids)
            changed = True
        else:
            clamped = parse_count(task.after_count)
            if task.after_count != clamped:
                task.after_count = clamped
                changed = True
        for tid in kept:
            child = by_id[tid]
            if child.prev_id != task.id:
                child.prev_id = task.id
                changed = True
    return changed


def linked_task_title(tasks: list[Task], task: Task) -> str:
    """Имена задач, связанных с этой. У корня — имена следующих узлов."""
    by_id = {item.id: item for item in tasks}
    names: list[str] = []
    for tid in task.after_ids:
        child = by_id.get(tid)
        if child is None:
            continue
        name = (child.title or "").strip()
        if name and name not in names:
            names.append(name)
    if names:
        return ", ".join(names)
    parent = by_id.get((task.prev_id or "").strip())
    if parent is None:
        return ""
    return (parent.title or "").strip()


def subtree_tasks(tasks: list[Task], task_id: str, *, include_self: bool = True) -> list[Task]:
    """Узел и все задачи, которые идут от него по связям after_ids."""
    by_id = {task.id: task for task in tasks}
    root = by_id.get(task_id)
    if root is None:
        return []
    found: list[Task] = []
    seen: set[str] = set()
    stack = [task_id] if include_self else list(root.after_ids)
    while stack:
        current = stack.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        node = by_id[current]
        found.append(node)
        stack.extend(node.after_ids)
    return found


def _reaches(tasks: list[Task], start_id: str, target_id: str) -> bool:
    """Есть ли путь по after_ids от start_id к target_id, не считая сам старт."""
    by_id = {task.id: task for task in tasks}
    if start_id not in by_id:
        return False
    seen = {start_id}
    stack = list(by_id[start_id].after_ids)
    while stack:
        current = stack.pop()
        if current in seen or current not in by_id:
            continue
        if current == target_id:
            return True
        seen.add(current)
        stack.extend(by_id[current].after_ids)
    return False


def link_existing_task(tasks: list[Task], parent: Task, child: Task) -> bool:
    """Поставить уже существующую задачу сразу после parent. Круг не создавать."""
    if parent is None or child is None or parent.id == child.id:
        return False
    if child.id in parent.after_ids:
        return True
    if _reaches(tasks, child.id, parent.id):
        return False
    parent.after_ids.append(child.id)
    parent.after_count = len(parent.after_ids)
    if not (child.prev_id or "").strip():
        child.prev_id = parent.id
    return True


def attach_named_child(tasks: list[Task], parent: Task, title: str) -> tuple[Task | None, bool]:
    """Связать parent с задачей этого имени. Если такая одна — присоединить её, иначе создать.

    Возвращает (задача, создана ли новая). None — имя пустое или связь замкнула бы круг.
    """
    name = (title or "").strip()
    if parent is None or not name:
        return None, False
    matches = [
        task
        for task in tasks
        if task.id != parent.id and (task.title or "").strip() == name
    ]
    if len(matches) == 1:
        child = matches[0]
        if not link_existing_task(tasks, parent, child):
            return None, False
        return child, False
    child = add_linked_task(tasks, parent, name)
    return child, child is not None


def add_linked_task(tasks: list[Task], parent: Task, title: str) -> Task | None:
    """Новый узел сразу после parent. Имя пустое — ничего не создавать."""
    from .widgets import TASK_BLOCK_H, TASK_W
    from .xlsx_store import _next_id

    name = (title or "").strip()
    if parent is None or not name:
        return None
    child = Task(
        id=_next_id(tasks),
        title=name,
        created_at=date.today(),
        start_at=parent.start_at,
        due_at=parent.due_at,
        project=parent.project,
        author=parent.author,
        prev_id=parent.id,
        source="chain",
    )
    slot = len(parent.after_ids)
    if parent.pos_x is not None and parent.pos_y is not None:
        child.pos_x = float(parent.pos_x) + TASK_W + 28
        child.pos_y = float(parent.pos_y) + slot * (TASK_BLOCK_H + 8)
    tasks.append(child)
    parent.after_ids.append(child.id)
    parent.after_count = len(parent.after_ids)
    return child


def apply_follower_count(
    tasks: list[Task], parent: Task, count: int
) -> tuple[list[Task], list[tuple[Task, dict]], list[tuple[Task, dict]]]:
    """Выставить число узлов после parent.

    Возвращает (созданные, снятые пустые, отвязанные с их снимком до правки).
    Снятые уже удалены из tasks. Отвязанные остаются в списке.
    """
    from .widgets import TASK_BLOCK_H, TASK_W
    from .xlsx_store import _next_id

    count = max(0, min(FOLLOWER_MAX, int(count)))
    by_id = {task.id: task for task in tasks}
    linked = [tid for tid in parent.after_ids if tid in by_id and tid != parent.id]
    if count == len(linked):
        parent.after_ids = linked
        parent.after_count = len(linked)
        return [], [], []

    created: list[Task] = []
    removed: list[tuple[Task, dict]] = []
    unlinked: list[tuple[Task, dict]] = []

    while len(linked) < count:
        child = Task(
            id=_next_id(tasks),
            title=CHAIN_TITLE,
            created_at=date.today(),
            start_at=parent.start_at,
            due_at=parent.due_at,
            project=parent.project,
            author=parent.author,
            prev_id=parent.id,
            source="chain",
        )
        slot = len(linked)
        if parent.pos_x is not None and parent.pos_y is not None:
            child.pos_x = float(parent.pos_x) + TASK_W + 28
            child.pos_y = float(parent.pos_y) + slot * (TASK_BLOCK_H + 8)
        tasks.append(child)
        by_id[child.id] = child
        linked.append(child.id)
        created.append(child)

    while len(linked) > count:
        drop_id = linked.pop()
        child = by_id.get(drop_id)
        if child is None:
            continue
        before_child = snapshot_dict(child)
        if child.prev_id == parent.id:
            child.prev_id = ""
        if _blank_chain_node(child):
            tasks.remove(child)
            by_id.pop(child.id, None)
            removed.append((child, before_child))
        else:
            unlinked.append((child, before_child))

    parent.after_ids = linked
    parent.after_count = len(linked)
    for tid in linked:
        node = by_id.get(tid)
        if node is not None and node.prev_id != parent.id:
            node.prev_id = parent.id
    return created, removed, unlinked


def _blank_chain_node(task: Task) -> bool:
    if task.after_ids:
        return False
    if (task.role or "").strip():
        return False
    if (task.description or "").strip():
        return False
    if task.tags:
        return False
    if task.is_done() or task.is_cancelled():
        return False
    title = (task.title or "").strip()
    return title in ("", CHAIN_TITLE)
