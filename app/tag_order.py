"""Порядок тегов в нижней панели (общий для всех экранов)."""

from __future__ import annotations

import json
from pathlib import Path

from .tags import TAGS

_ORDER: list[str] | None = None


def order_path(root: Path | None = None) -> Path:
    from .paths import app_root

    base = root or app_root()
    return base / "data" / "tag_order.json"


def default_order() -> list[str]:
    return [t.key for t in TAGS]


def load_order(root: Path | None = None) -> list[str]:
    global _ORDER
    path = order_path(root)
    defaults = default_order()
    if not path.exists():
        _ORDER = list(defaults)
        return list(_ORDER)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        keys = [str(k) for k in raw.get("order", [])]
    except (OSError, json.JSONDecodeError, TypeError):
        _ORDER = list(defaults)
        return list(_ORDER)

    known = set(defaults)
    ordered = [k for k in keys if k in known]
    for k in defaults:
        if k not in ordered:
            ordered.append(k)
    _ORDER = ordered
    return list(_ORDER)


def save_order(keys: list[str], root: Path | None = None) -> None:
    global _ORDER
    path = order_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    known = set(default_order())
    ordered = [k for k in keys if k in known]
    for k in default_order():
        if k not in ordered:
            ordered.append(k)
    _ORDER = ordered
    path.write_text(
        json.dumps({"order": ordered}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def get_order(root: Path | None = None) -> list[str]:
    global _ORDER
    if _ORDER is None:
        return load_order(root)
    return list(_ORDER)


def swap_tags(key_a: str, key_b: str, root: Path | None = None) -> list[str]:
    order = get_order(root)
    if key_a not in order or key_b not in order or key_a == key_b:
        return order
    i, j = order.index(key_a), order.index(key_b)
    order[i], order[j] = order[j], order[i]
    save_order(order, root)
    return order


def ordered_tag_defs(root: Path | None = None, *, for_bar: bool = False):
    from .tags import BY_KEY, SIDEBAR_TAG_KEYS

    keys = get_order(root)
    if for_bar:
        keys = [k for k in keys if k not in SIDEBAR_TAG_KEYS]
    return [BY_KEY[k] for k in keys if k in BY_KEY]


def tags_by_usage_frequency(tasks: list, root: Path | None = None):
    """Все теги: чаще используемые слева; при равенстве — порядок панели."""
    from collections import Counter

    from .tags import BY_KEY, canonicalize_tag_key

    counts: Counter[str] = Counter()
    for task in tasks or []:
        for raw in getattr(task, "tags", None) or []:
            key = canonicalize_tag_key(str(raw))
            if key in BY_KEY:
                counts[key] += 1

    base = get_order(root)
    index = {k: i for i, k in enumerate(base)}

    def sort_key(key: str) -> tuple:
        return (-counts.get(key, 0), index.get(key, 10**6), key)

    ordered = sorted(BY_KEY.keys(), key=sort_key)
    return [BY_KEY[k] for k in ordered]


def projects_by_usage_frequency(tasks: list) -> list[str]:
    """Уникальные проекты: чаще используемые слева; регистр не дублирует."""
    from .projects import projects_by_usage_frequency as _by_freq

    return _by_freq(tasks)
