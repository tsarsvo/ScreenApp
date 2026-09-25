"""Компактный выбор любого цвета: квадрат «насыщенность × яркость» и полоса оттенка.

Это обычные виджеты (не отдельное окно), поэтому они работают внутри полноэкранного
оверлея, где системный диалог выбора цвета оказался бы под окном «поверх всех».
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class ColorField(QWidget):
    """Квадрат насыщенности (по горизонтали) и яркости (по вертикали) для текущего оттенка."""

    changed = Signal(QColor)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(200, 120)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._h, self._s, self._v = 0.0, 1.0, 1.0

    def set_color(self, c: QColor) -> None:
        h, s, v, _ = c.getHsvF()
        if h >= 0:  # у серых оттенков hue = -1 — оставляем прежний
            self._h = h
        self._s, self._v = s, v
        self.update()

    def set_hue(self, h: float) -> None:
        self._h = h
        self.update()
        self.changed.emit(self.color())

    def color(self) -> QColor:
        return QColor.fromHsvF(self._h, self._s, self._v)

    def _pick(self, pos: QPointF) -> None:
        self._s = min(1.0, max(0.0, pos.x() / (self.width() - 1)))
        self._v = 1.0 - min(1.0, max(0.0, pos.y() / (self.height() - 1)))
        self.update()
        self.changed.emit(self.color())

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._pick(e.position())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.fillRect(r, QColor.fromHsvF(self._h, 1, 1))
        white = QLinearGradient(r.topLeft(), r.topRight())
        white.setColorAt(0, QColor(255, 255, 255))
        white.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(r, white)
        black = QLinearGradient(r.topLeft(), r.bottomLeft())
        black.setColorAt(0, QColor(0, 0, 0, 0))
        black.setColorAt(1, QColor(0, 0, 0))
        p.fillRect(r, black)
        # Маркер текущего цвета
        pt = QPointF(self._s * (self.width() - 1), (1 - self._v) * (self.height() - 1))
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 3))
        p.drawEllipse(pt, 6, 6)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawEllipse(pt, 6, 6)


class HueBar(QWidget):
    """Горизонтальная радуга для выбора оттенка."""

    changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(200, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._h = 0.0

    def set_hue(self, h: float) -> None:
        if h >= 0:
            self._h = h
            self.update()

    def _pick(self, x: float) -> None:
        self._h = min(0.999, max(0.0, x / (self.width() - 1)))
        self.update()
        self.changed.emit(self._h)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._pick(e.position().x())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._pick(e.position().x())

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 2, 0, -2)
        g = QLinearGradient(r.topLeft(), r.topRight())
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF(min(i / 6, 0.999), 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = self._h * (self.width() - 1)
        knob = QRectF(x - 5, 0, 10, self.height())
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(knob.adjusted(2, 0, -2, 0), 3, 3)
