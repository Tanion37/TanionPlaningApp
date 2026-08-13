"""Иконка приложения (календарь) и Windows AppUserModelID."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def set_windows_app_id(app_id: str = "Tanion37.TanionPlaning") -> None:
    """Чтобы панель задач не группировала окно под python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def calendar_pixmap(size: int = 256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size // 12
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    body = pm.rect().adjusted(margin, margin + size // 10, -margin, -margin)
    p.drawRoundedRect(body, size // 16, size // 16)

    p.setBrush(QColor("#E53935"))
    header = body.adjusted(0, 0, 0, -(body.height() * 2 // 3))
    p.drawRoundedRect(header, size // 16, size // 16)
    p.drawRect(header.adjusted(0, header.height() // 2, 0, 0))

    p.setBrush(QColor("#BDBDBD"))
    ring_w = size // 14
    ring_h = size // 8
    for frac in (0.28, 0.72):
        cx = int(body.left() + body.width() * frac)
        p.drawRoundedRect(
            cx - ring_w // 2,
            margin // 2,
            ring_w,
            ring_h,
            ring_w // 3,
            ring_w // 3,
        )

    p.setPen(QColor("#BDBDBD"))
    rows, cols = 4, 5
    grid = body.adjusted(size // 14, header.height() + size // 20, -size // 14, -size // 14)
    cell_w = grid.width() / cols
    cell_h = grid.height() / rows
    for r in range(rows + 1):
        y = int(grid.top() + r * cell_h)
        p.drawLine(grid.left(), y, grid.right(), y)
    for c in range(cols + 1):
        x = int(grid.left() + c * cell_w)
        p.drawLine(x, grid.top(), x, grid.bottom())

    p.setPen(QColor("#212121"))
    font = QFont("Segoe UI", max(8, size // 5))
    font.setBold(True)
    p.setFont(font)
    p.drawText(grid, int(Qt.AlignmentFlag.AlignCenter), "18")
    p.end()
    return pm


def _pixmap_png_bytes(pm: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    return bytes(buf.data())


def _write_ico(path: Path, sizes: tuple[int, ...] = (16, 32, 48, 256)) -> None:
    """ICO с PNG-вложениями (Windows Vista+)."""
    images: list[tuple[int, bytes]] = []
    for size in sizes:
        png = _pixmap_png_bytes(calendar_pixmap(size))
        images.append((size, png))

    count = len(images)
    offset = 6 + 16 * count
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    payloads = b""
    for size, png in images:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        payloads += png
        offset += len(png)
    path.write_bytes(header + entries + payloads)


def ensure_app_icon_file(root: Path | None = None) -> Path:
    from .paths import app_root

    base = root or app_root()
    assets = base / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    png = assets / "app_icon.png"
    ico = assets / "app_icon.ico"
    if not png.exists():
        calendar_pixmap(256).save(str(png), "PNG")
    if not ico.exists():
        _write_ico(ico)
    return png


def ensure_app_icon_ico(root: Path | None = None) -> Path:
    from .paths import app_root

    base = root or app_root()
    ensure_app_icon_file(base)
    return base / "assets" / "app_icon.ico"


def app_icon(root: Path | None = None) -> QIcon:
    from .paths import app_root

    base = root or app_root()
    ensure_app_icon_file(base)
    ico = base / "assets" / "app_icon.ico"
    if ico.exists():
        return QIcon(str(ico))
    return QIcon(str(base / "assets" / "app_icon.png"))
