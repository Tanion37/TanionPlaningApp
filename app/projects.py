"""Имена проектов: регистр не создаёт отдельный проект."""

from __future__ import annotations

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
