#!/usr/bin/env python3
"""Точка входа: python -m app  или  python app/main.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main_window import run_app  # noqa: E402


def main() -> int:
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
