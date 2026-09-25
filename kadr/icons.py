"""Тонкие иконки в едином стиле (24×24, линия 1.6px, скруглённые концы) и логотип.

Иконки хранятся как SVG-строки с `currentColor` и перекрашиваются под тему при рендере,
поэтому не нужны отдельные файлы для светлой и тёмной темы.
"""
from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
         'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">')

_PATHS = {
    # Режим «выделение / перемещение»
    "cursor": '<path d="M5 3.5l13 6.2-5.6 1.7-2.2 5.6z"/><path d="M12.4 11.4l5.4 5.4"/>',
    "pen": '<path d="M4 20l1.2-4.4L15.8 5a2 2 0 0 1 2.9 0l.3.3a2 2 0 0 1 0 2.9L8.4 18.8z"/>'
           '<path d="M13.8 7l3.2 3.2"/>',
    "arrow": '<path d="M5 19L19 5"/><path d="M10 5h9v9"/>',
    "rect": '<rect x="4" y="5.5" width="16" height="13" rx="1.5"/>',
    "ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6.5"/>',
    "text": '<path d="M5 6.5V5h14v1.5"/><path d="M12 5v14"/><path d="M9.5 19h5"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "copy": '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/>'
            '<path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
    "save": '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    "close": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8'
                'l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5'
                ' 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1'
                'H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1'
                'a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0'
                ' 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4'
                'h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "region": '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8"/><path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8"/>'
              '<path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16"/><path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12.5" rx="2"/><path d="M8.5 20h7"/><path d="M12 16.5V20"/>',
    "folder": '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "power": '<path d="M12 3.5v8"/><path d="M6.8 6.8a7.5 7.5 0 1 0 10.4 0"/>',
    "check": '<path d="M5 12.5l4.2 4.2L19 7"/>',
    "download": '<path d="M12 4v11"/><path d="M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/>'
               '<path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>',
    "highlighter": '<path d="M9 11l-5.5 5.5V20h7.5l2.5-2.5"/>'
                   '<path d="M21 11.5l-4.4 4.4a1.8 1.8 0 0 1-2.5 0l-5-5a1.8 1.8 0 0 1 0-2.5L13.5 4"/>',
    "pixelate": '<rect x="4" y="4" width="7" height="7" rx="1.2"/><rect x="13" y="13" width="7" height="7" rx="1.2"/>'
                '<path d="M13 5.5h5.5a1.5 1.5 0 0 1 1.5 1.5v4" stroke-dasharray="2 2.2"/>'
                '<path d="M11 18.5H5.5A1.5 1.5 0 0 1 4 17v-4" stroke-dasharray="2 2.2"/>',
    "step": '<circle cx="12" cy="12" r="8.5"/><path d="M10.3 9.6L12.6 8v8.2"/>',
    "pipette": '<path d="M3 21l1.2-.3 9.3-9.3"/><path d="M4.2 20.7l-.2-3.1 9.3-9.3"/>'
               '<path d="M14.6 5.4l2.6-2.6a2 2 0 0 1 2.9 0l1.1 1.1a2 2 0 0 1 0 2.9l-2.6 2.6.9.9a1.3 1.3 0 0 1-1.9 1.9'
               'l-4.9-4.9a1.3 1.3 0 0 1 1.9-1.9z"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.6-.7 1.6-1.6 0-.5-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1'
               'a1.6 1.6 0 0 1 1.6-1.6h1.9A4.7 4.7 0 0 0 21 11c0-4.4-4-8-9-8z"/>'
               '<circle cx="7.5" cy="11.5" r="1.1"/><circle cx="10" cy="7.3" r="1.1"/>'
               '<circle cx="14.5" cy="7.3" r="1.1"/><circle cx="17.2" cy="11" r="1.1"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/>'
             '<path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>'
             '<path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>',
    "replay": '<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3.5 4v4.5H8"/><circle cx="12" cy="12" r="2.6"/>',
}


def svg(name: str, color: str) -> str:
    return (_HEAD + _PATHS[name] + "</svg>").replace("currentColor", color)


def _render(svg_text: str, size: int, dpr: float = 2.0) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg_text.encode()))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


@lru_cache(maxsize=256)
def icon(name: str, color: str, size: int = 20) -> QIcon:
    """Иконка заданного цвета. Кэшируется по (имя, цвет, размер)."""
    return QIcon(_render(svg(name, color), size))


def check_mark_file(color: str = "#FFFFFF") -> str:
    """Галочка для QCheckBox в QSS (QSS умеет только url(), поэтому пишем во временный файл)."""
    path = Path(tempfile.gettempdir()) / f"kadr-check-{color.strip('#')}.svg"
    if not path.exists():
        text = svg("check", color).replace('stroke-width="1.6"', 'stroke-width="2.6"')
        path.write_text(text, encoding="utf-8")
    return path.as_posix()


# ---------------------------------------------------------------------------
# Логотип: скруглённый квадрат с градиентом, в нём — белые «уголки» рамки выделения
# и точка-прицел по центру. Читается и в 16px (трей), и в 512px (иконка приложения).
# ---------------------------------------------------------------------------
LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4C7DFF"/>
      <stop offset="1" stop-color="#7A5CFF"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#g)"/>
  <g fill="none" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M15 25V18a3 3 0 0 1 3-3h7"/>
    <path d="M39 15h7a3 3 0 0 1 3 3v7"/>
    <path d="M49 39v7a3 3 0 0 1-3 3h-7"/>
    <path d="M25 49h-7a3 3 0 0 1-3-3v-7"/>
  </g>
  <circle cx="32" cy="32" r="4.5" fill="#FFFFFF"/>
</svg>"""

# Монохромный вариант для трея macOS (template-иконка сама перекрашивается под строку меню)
LOGO_MONO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <g fill="none" stroke="#000000" stroke-width="6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M8 22V13a5 5 0 0 1 5-5h9"/><path d="M42 8h9a5 5 0 0 1 5 5v9"/>
    <path d="M56 42v9a5 5 0 0 1-5 5h-9"/><path d="M22 56h-9a5 5 0 0 1-5-5v-9"/>
  </g>
  <circle cx="32" cy="32" r="6" fill="#000000"/>
</svg>"""


@lru_cache(maxsize=4)
def logo_icon(mono: bool = False) -> QIcon:
    ico = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256, 512):
        ico.addPixmap(_render(LOGO_MONO_SVG if mono else LOGO_SVG, size, 1.0))
    if mono:
        ico.setIsMask(True)  # template image на macOS
    return ico


def logo_image(size: int) -> QImage:
    return _render(LOGO_SVG, size, 1.0).toImage()


def color_swatch(color: QColor | str, size: int = 14) -> QIcon:
    """Кружок цвета — для кнопки выбора цвета."""
    px = QPixmap(size * 2, size * 2)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(0, 0, 0, 60))
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, px.width() - 2, px.height() - 2)
    p.end()
    px.setDevicePixelRatio(2)
    return QIcon(px)
