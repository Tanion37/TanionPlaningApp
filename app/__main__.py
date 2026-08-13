"""Точка входа для PyInstaller: python -m app / frozen exe."""

from __future__ import annotations

import sys
from pathlib import Path

# При запуске из исходников — корень репо в sys.path
if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from app.main_window import run_app


def main() -> int:
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
