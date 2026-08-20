"""Теги планировщика: символ → ключ и обратно; нечёткое сопоставление."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

DONE_TAG = "выполнена"
CANCEL_TAG = "отменена"
IMPORTANT_TAG = "важная"
URGENT_TAG = "срочная"
INBOX_TAG = "входящая"
ACTUAL_TAG = "актуальная"
CHECKED_TAG = "проверенная"
BACKLOG_TAG = "бэклог"
CORRESPONDENCE_TAG = "переписка"
CONTROL_TAG = "контроль"
DELEGATE_TAG = "делегируемая"
# совместимость: бывший тег «ответы» / кнопка Ответы
ANSWERS_TAG = CORRESPONDENCE_TAG
TODAY_ACTION = "__today__"
TOMORROW_ACTION = "__tomorrow__"
WEEK_ACTION = "__week__"
DONE_CHECK_ACTION = "__done_check__"
SOCIAL_TAG = "соцсети"
SPECIAL_ACTION_KEYS = frozenset(
    {TODAY_ACTION, TOMORROW_ACTION, WEEK_ACTION, DONE_CHECK_ACTION}
)
# Кисти, которые по клику на раздел применяются ко всем задачам раздела.
SECTION_BRUSH_KEYS = frozenset(
    {TOMORROW_ACTION, WEEK_ACTION, BACKLOG_TAG, INBOX_TAG}
)

DONE_ALIASES = frozenset(
    {
        "выполнена",
        "выполнено",
        "выполненное",
        "выполненный",
        "done",
    }
)
CANCEL_ALIASES = frozenset(
    {
        "отменена",
        "отменено",
        "отменённое",
        "отмененное",
        "отменённый",
        "отмененный",
        "cancelled",
        "canceled",
    }
)

# Жёсткие миграции старых имён → канон
LEGACY_TAG_MAP: dict[str, str] = {
    "выполненное": DONE_TAG,
    "выполнено": DONE_TAG,
    "выполненный": DONE_TAG,
    "отменённое": CANCEL_TAG,
    "отмененное": CANCEL_TAG,
    "отменено": CANCEL_TAG,
    "важно": IMPORTANT_TAG,
    "важный": IMPORTANT_TAG,
    "срочно": URGENT_TAG,
    "срочный": URGENT_TAG,
    "срочн": URGENT_TAG,
    "входящие": INBOX_TAG,
    "входящий": INBOX_TAG,
    "актуально": ACTUAL_TAG,
    "проверено": CHECKED_TAG,
    "проверена": CHECKED_TAG,
    "беклог": BACKLOG_TAG,
    "бэклог": BACKLOG_TAG,
    "отложенная": BACKLOG_TAG,
    "backlog": BACKLOG_TAG,
    "ответы": CORRESPONDENCE_TAG,
    "ответная": CORRESPONDENCE_TAG,
    "геймдизайнерская": "геймдизайн",
    "геймдизайн": "геймдизайн",
    "документы": "документная",
    "платежи": "финансы",
    "платёжная": "финансы",
    "платежная": "финансы",
    "подумать": "обдумываемая",
    "на улице": "уличная",
    "личное": "личная",
    "делегировать": "делегируемая",
    "контрольная": "контроль",
    "контроль": "контроль",
}

SYSTEM_TAG_KEYS: frozenset[str] = frozenset(
    {
        INBOX_TAG,
        ACTUAL_TAG,
        IMPORTANT_TAG,
        URGENT_TAG,
        DONE_TAG,
        CANCEL_TAG,
        CHECKED_TAG,
    }
)

# Теги, которые показываются в правой панели, а не в нижней полосе
SIDEBAR_TAG_KEYS: frozenset[str] = frozenset({BACKLOG_TAG})

# Старые теги дней недели — снимаются при миграции
LEGACY_WEEKDAY_KEYS: frozenset[str] = frozenset(
    {"ПН", "ВТ", "СР", "ЧТ", "ПТ", "ВХ", "пн", "вт", "ср", "чт", "пт", "вх"}
)


@dataclass(frozen=True, slots=True)
class TagDef:
    key: str
    symbol: str
    label: str
    weekday: int | None = None  # устарело, всегда None
    is_weekend: bool = False


# важная: ⚠; срочная: 🔥; выполнена: ✅; отменена: 🗑
# входящая: ⬇; актуальная: ★; проверенная: ☑; бэклог: 🗄
TAGS: tuple[TagDef, ...] = (
    TagDef(IMPORTANT_TAG, "⚠", IMPORTANT_TAG),
    TagDef(URGENT_TAG, "🔥", URGENT_TAG),
    TagDef(INBOX_TAG, "⬇", INBOX_TAG),
    TagDef(ACTUAL_TAG, "★", ACTUAL_TAG),
    TagDef(CHECKED_TAG, "☑", CHECKED_TAG),
    TagDef("геймдизайн", "🎲", "геймдизайн"),
    TagDef("ПРОГД", "ПРО", "ПРОГД"),
    TagDef("сложная", "🐸", "сложная"),
    TagDef("быстрая", "⚡", "быстрая"),
    TagDef("документная", "📄", "документная"),
    TagDef("финансы", "💳", "финансы"),
    TagDef("обдумываемая", "💡", "обдумываемая"),
    TagDef("уличная", "🚶", "уличная"),
    TagDef("личная", "🏠", "личная"),
    TagDef(SOCIAL_TAG, "📱", SOCIAL_TAG),
    TagDef("ИИ", "🤖", "ИИ"),
    TagDef(CORRESPONDENCE_TAG, "💬", CORRESPONDENCE_TAG),
    TagDef(DELEGATE_TAG, "📤", DELEGATE_TAG),
    TagDef(CONTROL_TAG, "👁", CONTROL_TAG),
    TagDef(BACKLOG_TAG, "🗄", BACKLOG_TAG),
    TagDef("в работе", "🔧", "в работе"),
    TagDef(CANCEL_TAG, "🗑", CANCEL_TAG),
    TagDef(DONE_TAG, "✅", DONE_TAG),
)

BY_KEY: dict[str, TagDef] = {t.key: t for t in TAGS}
BY_SYMBOL: dict[str, TagDef] = {t.symbol: t for t in TAGS}
BY_SYMBOL["❗"] = BY_KEY[IMPORTANT_TAG]
BY_SYMBOL["✔"] = BY_KEY[DONE_TAG]
BY_SYMBOL["💭"] = BY_KEY["обдумываемая"]
BY_SYMBOL["⬇"] = BY_KEY[INBOX_TAG]
BY_SYMBOL["↓"] = BY_KEY[INBOX_TAG]
BY_SYMBOL["📥"] = BY_KEY[INBOX_TAG]
BY_SYMBOL["★"] = BY_KEY[ACTUAL_TAG]
BY_SYMBOL["☑"] = BY_KEY[CHECKED_TAG]
BY_SYMBOL["💡"] = BY_KEY["обдумываемая"]
BY_SYMBOL["🗄"] = BY_KEY[BACKLOG_TAG]
BY_SYMBOL["✉"] = BY_KEY[CORRESPONDENCE_TAG]  # старый символ «ответы»
BY_SYMBOL["🧱"] = BY_KEY["сложная"]
BY_SYMBOL["🐸"] = BY_KEY["сложная"]
BY_SYMBOL["👁️"] = BY_KEY[CONTROL_TAG]
BY_SYMBOL["👀"] = BY_KEY[CONTROL_TAG]
BY_SYMBOL["ПРО"] = BY_KEY["ПРОГД"]
BY_SYMBOL["про"] = BY_KEY["ПРОГД"]

# Сортировка по тегам на экране: без системных
TAG_SORT_KEYS: tuple[str, ...] = tuple(
    t.key for t in TAGS if t.key not in SYSTEM_TAG_KEYS
)

WEEKDAY_KEYS: tuple[str, ...] = ()

REMIND_PERIODS: tuple[str, ...] = (
    "",
    "каждый день",
    "каждую неделю",
    "каждый месяц",
    "каждый год",
)


def normalize_tag_text(key: str) -> str:
    return key.strip().casefold().replace("ё", "е")


def _stems(text: str) -> set[str]:
    """Префиксы после отрезания 0–2 последних букв (для нечёткого сравнения)."""
    n = normalize_tag_text(text)
    if not n:
        return set()
    out = {n}
    if len(n) >= 2:
        out.add(n[:-1])
    if len(n) >= 3:
        out.add(n[:-2])
    return out


def tags_differ_by_at_most_two_letters(a: str, b: str) -> bool:
    """True, если ключи отличаются не более чем в 1–2 последних буквах."""
    na, nb = normalize_tag_text(a), normalize_tag_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    stems_a, stems_b = _stems(a), _stems(b)
    shared = stems_a & stems_b
    if not shared:
        return False
    longest = max(len(s) for s in shared)
    return longest >= 3


def most_frequent_tag_variant(
    candidates: Iterable[str],
    usage: Counter[str] | None = None,
) -> str | None:
    """Выбрать наиболее употребимый вариант; при равенстве — системный/известный."""
    items = [c for c in candidates if c]
    if not items:
        return None
    usage = usage or Counter()
    items_sorted = sorted(
        items,
        key=lambda k: (
            -usage.get(k, 0),
            0 if k in BY_KEY else 1,
            0 if k in SYSTEM_TAG_KEYS else 1,
            len(k),
            k,
        ),
    )
    return items_sorted[0]


def collect_tag_usage(tag_lists: Iterable[Iterable[str]]) -> Counter[str]:
    c: Counter[str] = Counter()
    for tags in tag_lists:
        for t in tags:
            if t:
                c[str(t)] += 1
    return c


def find_fuzzy_match(
    key: str,
    known: Iterable[str],
    usage: Counter[str] | None = None,
) -> str | None:
    """Найти среди known канон, совпадающий с key по правилу 1–2 букв."""
    matches = [k for k in known if tags_differ_by_at_most_two_letters(key, k)]
    if not matches:
        return None
    return most_frequent_tag_variant(matches, usage)


def canonicalize_tag_key(
    key: str,
    *,
    usage: Counter[str] | None = None,
    extra_known: Iterable[str] | None = None,
) -> str:
    raw = key.strip()
    if not raw:
        return raw
    lower = normalize_tag_text(raw)

    if lower in LEGACY_WEEKDAY_KEYS or raw in LEGACY_WEEKDAY_KEYS:
        return ""

    if lower in DONE_ALIASES or raw in DONE_ALIASES:
        return DONE_TAG
    if lower in CANCEL_ALIASES or raw in CANCEL_ALIASES:
        return CANCEL_TAG
    if lower in {"лягушка", "frog"}:
        return "сложная"

    mapped = LEGACY_TAG_MAP.get(lower) or LEGACY_TAG_MAP.get(raw)
    if mapped:
        return mapped

    for t in TAGS:
        if normalize_tag_text(t.key) == lower:
            return t.key

    known: list[str] = [t.key for t in TAGS]
    if extra_known:
        known.extend(extra_known)
    if usage:
        known.extend(usage.keys())
    fuzzy = find_fuzzy_match(raw, known, usage)
    if fuzzy:
        for t in TAGS:
            if tags_differ_by_at_most_two_letters(fuzzy, t.key):
                return t.key
        return fuzzy

    return raw


def normalize_tag_token(
    token: str,
    *,
    usage: Counter[str] | None = None,
    extra_known: Iterable[str] | None = None,
) -> str | None:
    """Вернуть ключ тега по символу, ключу или алиасу."""
    raw = token.strip()
    if not raw:
        return None
    if raw in BY_SYMBOL:
        return BY_SYMBOL[raw].key
    if raw in BY_KEY:
        return canonicalize_tag_key(raw, usage=usage, extra_known=extra_known)
    lower = normalize_tag_text(raw)
    aliases = {
        "важно": IMPORTANT_TAG,
        "важная": IMPORTANT_TAG,
        "срочно": URGENT_TAG,
        "срочная": URGENT_TAG,
        "срочн": URGENT_TAG,
        "входящие": INBOX_TAG,
        "входящая": INBOX_TAG,
        "входящий": INBOX_TAG,
        "актуально": ACTUAL_TAG,
        "актуальная": ACTUAL_TAG,
        "проверено": CHECKED_TAG,
        "проверена": CHECKED_TAG,
        "проверенная": CHECKED_TAG,
        "беклог": BACKLOG_TAG,
        "бэклог": BACKLOG_TAG,
        "backlog": BACKLOG_TAG,
        "отложенная": BACKLOG_TAG,
        "ответы": CORRESPONDENCE_TAG,
        "переписка": CORRESPONDENCE_TAG,
        "ai": "ИИ",
        "лягушка": "сложная",
        "frog": "сложная",
        "глаз": "контроль",
        "eye": "контроль",
        "контроль": "контроль",
        "контрольная": "контроль",
        "прогд": "ПРОГД",
        "pgd": "ПРОГД",
        "про": "ПРОГД",
        "геймдизайн": "геймдизайн",
        "геймдизайнерская": "геймдизайн",
        "документы": "документная",
        "платежи": "финансы",
        "платёжная": "финансы",
        "платежная": "финансы",
        "финансы": "финансы",
        "подумать": "обдумываемая",
        "на улице": "уличная",
        "личное": "личная",
        "делегировать": "делегируемая",
    }
    if lower in aliases:
        return aliases[lower]
    canon = canonicalize_tag_key(raw, usage=usage, extra_known=extra_known)
    if not canon:
        return None
    if canon in BY_KEY or canon in SYSTEM_TAG_KEYS:
        return canon
    for t in TAGS:
        if normalize_tag_text(t.key) == lower or normalize_tag_text(t.label) == lower:
            return t.key
    return canon


def parse_tags_cell(
    value: str | None,
    *,
    usage: Counter[str] | None = None,
) -> list[str]:
    """Разобрать колонку тегов: символы подряд или через пробел/запятую."""
    if not value:
        return []
    text = str(value).strip()
    if not text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    for wd in ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "ВХ"):
        if wd in text:
            text = text.replace(wd, " ")

    for t in TAGS:
        if t.symbol in text:
            key = canonicalize_tag_key(t.key, usage=usage)
            if key and key not in seen:
                found.append(key)
                seen.add(key)
            text = text.replace(t.symbol, " ")

    if "🧱" in text:
        if "сложная" not in seen:
            found.append("сложная")
            seen.add("сложная")
        text = text.replace("🧱", " ")

    for part in text.replace(",", " ").split():
        key = normalize_tag_token(part, usage=usage)
        if key and key not in seen:
            found.append(key)
            seen.add(key)

    return found


def tags_to_cell(keys: list[str]) -> str:
    parts: list[str] = []
    for key in keys:
        canon = canonicalize_tag_key(key)
        if not canon:
            continue
        t = BY_KEY.get(canon)
        if t:
            parts.append(t.symbol)
        else:
            parts.append(canon)
    return " ".join(parts)


def display_symbol(key: str, *, prefer_fallback: bool = False) -> str:
    canon = canonicalize_tag_key(key)
    t = BY_KEY.get(canon)
    if not t:
        return key or ""
    if canon == IMPORTANT_TAG and prefer_fallback:
        return "❗"
    return t.symbol


def is_system_tag(key: str) -> bool:
    return canonicalize_tag_key(key) in SYSTEM_TAG_KEYS


def clear_inbox_tag(task) -> bool:
    """Снять входящая / legacy входящие. True, если что-то сняли."""
    changed = False
    if task.remove_tag(INBOX_TAG):
        changed = True
    if task.remove_tag("входящие"):
        changed = True
    return changed


def clear_actual_tag(task) -> bool:
    """Снять актуальная / legacy актуально."""
    changed = False
    if task.remove_tag(ACTUAL_TAG):
        changed = True
    if task.remove_tag("актуально"):
        changed = True
    return changed


def assign_start_at(task, new_start, *, clear_inbox: bool = True) -> None:
    """Выставить start_at; по умолчанию снять входящую (планирование во времени)."""
    if clear_inbox:
        clear_inbox_tag(task)
    task.start_at = new_start


def apply_control_tag(task, today=None) -> None:
    """Контроль: тег + старт завтра + снять актуальную."""
    from datetime import date, timedelta

    today = today or date.today()
    task.add_tag(CONTROL_TAG)
    assign_start_at(task, today + timedelta(days=1))
    clear_actual_tag(task)


def control_followup_tags(tags: Iterable[str]) -> list[str]:
    """Копия тегов для контроля: делегируемая→контроль, актуальная→входящая."""
    out: list[str] = []
    for tag in tags:
        key = canonicalize_tag_key(str(tag)) or str(tag).strip()
        if not key:
            continue
        if key in DONE_ALIASES or key in CANCEL_ALIASES or key in {DONE_TAG, CANCEL_TAG}:
            continue
        if key == DELEGATE_TAG:
            key = CONTROL_TAG
        elif key == ACTUAL_TAG:
            key = INBOX_TAG
        if key not in out:
            out.append(key)
    return out


def migrate_tag_list(
    tags: list[str],
    *,
    usage: Counter[str] | None = None,
) -> list[str]:
    """Нормализовать список тегов: legacy map, weekday drop, fuzzy, дедуп."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        key = normalize_tag_token(str(tag), usage=usage) or canonicalize_tag_key(
            str(tag), usage=usage
        )
        if not key:
            continue
        if key == "лягушка":
            key = "сложная"
        if key in LEGACY_WEEKDAY_KEYS:
            continue
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out
