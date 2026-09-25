"""Захват экранов.

Основной путь — QScreen.grabWindow(0): Qt сам учитывает HiDPI на каждой ОС.
Если Qt вернул пустую картинку, используется mss (быстрый нативный захват через
BitBlt / CoreGraphics / XShm).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap, QScreen


@dataclass
class ScreenShot:
    screen: QScreen
    geometry: QRect   # логические координаты экрана на виртуальном рабочем столе
    pixmap: QPixmap   # физические пиксели; devicePixelRatio выставлен

    @property
    def dpr(self) -> float:
        return self.pixmap.devicePixelRatio()


def _grab_with_mss(screen: QScreen) -> QPixmap:
    import mss

    geo = screen.geometry()
    dpr = screen.devicePixelRatio()
    with mss.mss() as sct:
        # Сопоставляем монитор mss с QScreen по положению (mss может отдавать
        # как логические, так и физические координаты — проверяем оба варианта)
        def score(m):
            return min(abs(m["left"] - geo.x()) + abs(m["top"] - geo.y()),
                       abs(m["left"] - geo.x() * dpr) + abs(m["top"] - geo.y() * dpr))

        mon = min(sct.monitors[1:], key=score)
        raw = sct.grab(mon)
        img = QImage(raw.bgra, raw.width, raw.height, raw.width * 4, QImage.Format.Format_RGB32).copy()
    return QPixmap.fromImage(img)


def _cursor_path() -> QPainterPath:
    """Классическая стрелка курсора (остриё в (0,0)), 12×20 логических пикселей."""
    pts = [(0, 0), (0, 16.5), (4.2, 12.6), (7, 19), (9.6, 17.9), (6.9, 11.6), (12.2, 11.6)]
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    path.closeSubpath()
    return path


def draw_cursor(painter: QPainter, pos: QPointF) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(pos)
    pen = QPen(QColor("#000000"), 1.1)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPath(_cursor_path())
    painter.restore()


def grab_screens(include_cursor: bool = False) -> list[ScreenShot]:
    shots = []
    cursor = QCursor.pos()
    for screen in QGuiApplication.screens():
        geo = screen.geometry()
        px = screen.grabWindow(0)
        if px.isNull() or px.width() == 0:
            try:
                px = _grab_with_mss(screen)
            except Exception:
                continue
        # Явно выставляем DPR по фактическому размеру, чтобы не зависеть от поведения платформы
        px.setDevicePixelRatio(px.width() / max(1, geo.width()))
        if include_cursor and geo.contains(cursor):
            p = QPainter(px)
            draw_cursor(p, QPointF(cursor - geo.topLeft()))
            p.end()
        shots.append(ScreenShot(screen, geo, px))
    return shots


def grab_full_desktop(include_cursor: bool = False) -> QImage:
    """Все мониторы, склеенные в одно изображение в их реальном взаимном расположении."""
    shots = grab_screens(include_cursor)
    if not shots:
        return QImage()
    if len(shots) == 1:
        return shots[0].pixmap.toImage()

    union = QRect()
    for s in shots:
        union = union.united(s.geometry)
    scale = max(s.dpr for s in shots)
    img = QImage(round(union.width() * scale), round(union.height() * scale), QImage.Format.Format_RGB32)
    img.fill(QColor("#000000"))  # области вне мониторов (при разной высоте экранов)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    for s in shots:
        g = s.geometry.translated(-union.topLeft())
        target = QRectF(g.x() * scale, g.y() * scale, g.width() * scale, g.height() * scale)
        p.drawPixmap(target, s.pixmap, QRectF(s.pixmap.rect()))
    p.end()
    return img
