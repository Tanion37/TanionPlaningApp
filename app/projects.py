"""Имена проектов: регистр не создаёт отдельный проект."""

from __future__ import annotations

import json
from collections import Counter, defaultdict


def project_key(name: str | None) -> str:
    return (name or "").strip().casefold()


def same_project(a: str | None, b: str | None) -> bool:
    ka, kb = project_key(a), project_key(b)
    if not ka and not kb:
        return True
    if not ka or not kb:
        return False
    return ka == kb


def canonical_project_map(tasks: list) -> dict[str, str]:
    """casefold → каноническое написание (чаще встречающееся; при равенстве — стабильный порядок)."""
    exact: Counter[str] = Counter()
    for task in tasks or []:
        name = (getattr(task, "project", None) or "").strip()
        if name:
            exact[name] += 1
    by_fold: dict[str, list[str]] = defaultdict(list)
    for name in exact:
        by_fold[project_key(name)].append(name)
    result: dict[str, str] = {}
    for fold, names in by_fold.items():
        names_sorted = sorted(names, key=lambda n: (-exact[n], n.casefold(), n))
        result[fold] = names_sorted[0]
    return result


def resolve_project_name(name: str | None, tasks: list) -> str:
    """Подставить каноническое написание, если проект уже есть без учёта регистра."""
    raw = (name or "").strip()
    if not raw:
        return ""
    canon = canonical_project_map(tasks).get(project_key(raw))
    return canon if canon else raw


def unify_project_casing(tasks: list) -> int:
    """Привести все задачи к каноническим именам проектов. Вернуть число изменений."""
    mapping = canonical_project_map(tasks)
    changed = 0
    for task in tasks or []:
        raw = (getattr(task, "project", None) or "").strip()
        if not raw:
            if task.project:
                task.project = ""
                changed += 1
            continue
        canon = mapping.get(project_key(raw), raw)
        if task.project != canon:
            task.project = canon
            changed += 1
    return changed


def preset_of_project(tasks: list, name: str | None) -> str:
    """Класс (Preset) этого проекта. Пусто, если экземпляр ещё ни к чему не привязан."""
    if not (name or "").strip():
        return ""
    for task in tasks or []:
        if not same_project(getattr(task, "project", ""), name):
            continue
        preset = (getattr(task, "preset_name", "") or "").strip()
        if preset:
            return preset
    return ""


def project_name_taken(name: str | None, tasks: list) -> bool:
    """Такое название уже встречается у задачи. Регистр не делает имя новым."""
    raw = (name or "").strip()
    if not raw:
        return False
    for task in tasks or []:
        if same_project(getattr(task, "project", ""), raw):
            return True
    return False


def next_instance_name(preset: str, tasks: list, extra: object = ()) -> str:
    """Имя нового проекта по классу: само имя Preset, затем «Имя 2», «Имя 3»."""
    base = (preset or "").strip() or "Проект"
    taken = {project_key(getattr(task, "project", "")) for task in tasks or []}
    for name in extra or ():
        taken.add(project_key(str(name)))
    taken.discard("")
    if project_key(base) not in taken:
        return base
    number = 2
    while project_key(f"{base} {number}") in taken:
        number += 1
    return f"{base} {number}"


def _forgotten_path():
    from .paths import app_root

    return app_root() / "data" / "sync" / "forgotten_projects.json"


def _read_forgotten() -> dict[str, str]:
    path = _forgotten_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    found: dict[str, str] = {}
    for key, value in raw.items():
        name = str(value or key or "").strip()
        fold = project_key(name)
        if fold:
            found[fold] = name
    return found


def _write_forgotten(found: dict[str, str]) -> None:
    path = _forgotten_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remember_forgotten_project(name: str | None) -> None:
    """Проект снят с задач. Облако не должно вернуть это имя само."""
    raw = (name or "").strip()
    fold = project_key(raw)
    if not fold:
        return
    found = _read_forgotten()
    found[fold] = raw
    _write_forgotten(found)


def recall_forgotten_project(name: str | None) -> None:
    """Имя снова задали вручную — его можно хранить."""
    fold = project_key(name)
    if not fold:
        return
    found = _read_forgotten()
    if fold not in found:
        return
    del found[fold]
    _write_forgotten(found)


def is_forgotten_project(name: str | None) -> bool:
    return project_key(name) in _read_forgotten()


def clear_forgotten_projects(tasks: list) -> bool:
    """Снять забытые имена. Вернуть True, если какая-то задача изменилась."""
    changed = False
    for task in tasks or []:
        if not is_forgotten_project(getattr(task, "project", "")):
            continue
        task.project = ""
        if hasattr(task, "dirty"):
            task.dirty = 1
        changed = True
    return changed


def detach_project(store, name: str) -> int:
    """Убрать проект с задач и запомнить, что его не надо возвращать из облака."""
    from .project_roles import forget_project

    raw = (name or "").strip()
    if not raw:
        return 0
    remember_forgotten_project(raw)
    cleared = 0
    for task in getattr(store, "tasks", []) or []:
        if not (getattr(task, "project", "") or "").strip():
            continue
        if not same_project(task.project, raw):
            continue
        task.project = ""
        if hasattr(store, "mark_changed"):
            store.mark_changed(task)
        elif hasattr(task, "dirty"):
            task.dirty = 1
        cleared += 1
    forget_project(raw)
    return cleared


def projects_by_usage_frequency(tasks: list) -> list[str]:
    """Уникальные проекты (регистр не дублирует): чаще используемые слева."""
    mapping = canonical_project_map(tasks)
    counts: Counter[str] = Counter()
    for task in tasks or []:
        name = (getattr(task, "project", None) or "").strip()
        if not name:
            continue
        canon = mapping.get(project_key(name), name)
        counts[canon] += 1
    return sorted(counts.keys(), key=lambda n: (-counts[n], n.casefold()))
