"""Надписи и области на холсте (персист в data/board_annotations.json)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class LabelAnn:
    id: str
    text: str
    x: float
    y: float
    screen_id: str
    kind: str = "label"


@dataclass
class RectAnn:
    id: str
    x: float
    y: float
    w: float
    h: float
    screen_id: str
    kind: str = "rect"


@dataclass
class AnnotationStore:
    labels: list[LabelAnn] = field(default_factory=list)
    rects: list[RectAnn] = field(default_factory=list)
    path: Path | None = None

    @classmethod
    def default_path(cls, root: Path | None = None) -> Path:
        from .paths import app_root

        base = root or app_root()
        return base / "data" / "board_annotations.json"

    @classmethod
    def load(cls, root: Path | None = None) -> "AnnotationStore":
        path = cls.default_path(root)
        store = cls(path=path)
        if not path.exists():
            return store
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return store
        for item in raw.get("labels", []):
            store.labels.append(
                LabelAnn(
                    id=str(item.get("id") or uuid.uuid4()),
                    text=str(item.get("text") or ""),
                    x=float(item.get("x") or 0),
                    y=float(item.get("y") or 0),
                    screen_id=str(item.get("screen_id") or "triage"),
                )
            )
        for item in raw.get("rects", []):
            store.rects.append(
                RectAnn(
                    id=str(item.get("id") or uuid.uuid4()),
                    x=float(item.get("x") or 0),
                    y=float(item.get("y") or 0),
                    w=float(item.get("w") or 80),
                    h=float(item.get("h") or 60),
                    screen_id=str(item.get("screen_id") or "triage"),
                )
            )
        return store

    def save(self) -> None:
        path = self.path or self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "labels": [asdict(x) for x in self.labels],
            "rects": [asdict(x) for x in self.rects],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def add_label(self, text: str, x: float, y: float, screen_id: str) -> LabelAnn:
        item = LabelAnn(id=str(uuid.uuid4()), text=text, x=x, y=y, screen_id=screen_id)
        self.labels.append(item)
        self.save()
        return item

    def add_rect(self, x: float, y: float, w: float, h: float, screen_id: str) -> RectAnn:
        item = RectAnn(
            id=str(uuid.uuid4()),
            x=x,
            y=y,
            w=max(40.0, w),
            h=max(30.0, h),
            screen_id=screen_id,
        )
        self.rects.append(item)
        self.save()
        return item

    def update_label(self, item: LabelAnn) -> None:
        self.save()

    def update_rect(self, item: RectAnn) -> None:
        self.save()

    def remove(self, ann_id: str) -> bool:
        before = len(self.labels) + len(self.rects)
        self.labels = [x for x in self.labels if x.id != ann_id]
        self.rects = [x for x in self.rects if x.id != ann_id]
        if len(self.labels) + len(self.rects) != before:
            self.save()
            return True
        return False

    def for_screen(self, screen_id: str) -> tuple[list[LabelAnn], list[RectAnn]]:
        return (
            [x for x in self.labels if x.screen_id == screen_id],
            [x for x in self.rects if x.screen_id == screen_id],
        )
