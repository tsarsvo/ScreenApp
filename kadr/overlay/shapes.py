"""Фигуры, которые рисуются поверх скриншота.

Все координаты — логические координаты оверлея. При экспорте тот же paint()
вызывается на painter'е, масштабированном под физические пиксели, поэтому
результат остаётся чётким на HiDPI.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF


class Tool(Enum):
    SELECT = "select"
    PEN = "pen"
    ARROW = "arrow"
    LINE = "line"
    RECT = "rect"
    ELLIPSE = "ellipse"
    TEXT = "text"
    MARKER = "marker"
    PIXELATE = "pixelate"
    STEP = "step"


def _pen(color: QColor, width: float, join=Qt.PenJoinStyle.RoundJoin) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(join)
    return pen


@dataclass
class Shape:
    color: QColor
    width: float

    def paint(self, p: QPainter) -> None:
        raise NotImplementedError

    def is_empty(self) -> bool:
        return False

    def bounds(self) -> QRectF:
        """Область, которую занимает фигура на экране (с запасом на толщину линии) —
        чтобы перерисовывать только её, а не весь экран."""
        return QRectF()


@dataclass
class PenStroke(Shape):
    points: list[QPointF] = field(default_factory=list)

    def paint(self, p: QPainter) -> None:
        if not self.points:
            return
        p.setPen(_pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if len(self.points) == 1:
            p.drawPoint(self.points[0])  # клик без движения — точка
            return
        # Сглаживание: квадратичные кривые через середины соседних точек
        path = QPainterPath(self.points[0])
        for a, b in zip(self.points[1:-1], self.points[2:], strict=True):
            path.quadTo(a, (a + b) / 2)
        path.lineTo(self.points[-1])
        p.drawPath(path)

    def bounds(self) -> QRectF:
        if not self.points:
            return QRectF()
        m = self.width + 2
        return QPolygonF(self.points).boundingRect().adjusted(-m, -m, m, m)


@dataclass
class TwoPointShape(Shape):
    start: QPointF = field(default_factory=QPointF)
    end: QPointF = field(default_factory=QPointF)

    def rect(self) -> QRectF:
        return QRectF(self.start, self.end).normalized()

    def is_empty(self) -> bool:
        return QLineF(self.start, self.end).length() < 3

    def bounds(self) -> QRectF:
        # у стрелки наконечник шире линии — берём запас с учётом его размера
        m = max(self.width * 4, 12) + 2
        return self.rect().adjusted(-m, -m, m, m)


@dataclass
class ArrowShape(TwoPointShape):
    def paint(self, p: QPainter) -> None:
        line = QLineF(self.start, self.end)
        if line.length() < 1:
            return
        # Размер наконечника растёт с толщиной, но не больше половины длины стрелки
        head = min(max(10.0, self.width * 3.6), line.length() * 0.5)
        angle = math.atan2(line.dy(), line.dx())
        spread = math.radians(26)
        tip = self.end
        left = tip - QPointF(math.cos(angle - spread), math.sin(angle - spread)) * head
        right = tip - QPointF(math.cos(angle + spread), math.sin(angle + spread)) * head
        # Линия заканчивается у основания наконечника, чтобы кончик был острым
        base = tip - QPointF(math.cos(angle), math.sin(angle)) * head * 0.8

        p.setPen(_pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(self.start, base)
        p.setPen(_pen(self.color, max(1.0, self.width * 0.5)))
        p.setBrush(self.color)
        p.drawPolygon(QPolygonF([tip, left, right]))


@dataclass
class LineShape(TwoPointShape):
    """Прямая линия (Shift — с шагом 45°)."""

    def paint(self, p: QPainter) -> None:
        p.setPen(_pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(self.start, self.end)


@dataclass
class RectShape(TwoPointShape):
    def paint(self, p: QPainter) -> None:
        p.setPen(_pen(self.color, self.width, Qt.PenJoinStyle.MiterJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect())


@dataclass
class EllipseShape(TwoPointShape):
    def paint(self, p: QPainter) -> None:
        p.setPen(_pen(self.color, self.width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(self.rect())


def font_px_for_width(width: float) -> int:
    """Размер шрифта инструмента «Текст» привязан к толщине кисти (Ctrl+колесо меняет оба)."""
    return int(10 + width * 3)


@dataclass
class TextShape(Shape):
    pos: QPointF = field(default_factory=QPointF)  # левый верхний угол
    text: str = ""

    def font(self) -> QFont:
        f = QFont()
        f.setPixelSize(font_px_for_width(self.width))
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def lines(self) -> list[str]:
        return self.text.split("\n")

    def bounds_text(self) -> QRectF:
        fm = QFontMetricsF(self.font())
        w = max((fm.horizontalAdvance(l) for l in self.lines()), default=0)
        return QRectF(self.pos, QPointF(self.pos.x() + max(w, 2), self.pos.y() + fm.lineSpacing() * len(self.lines())))

    def caret_line(self) -> QLineF:
        fm = QFontMetricsF(self.font())
        lines = self.lines()
        x = self.pos.x() + fm.horizontalAdvance(lines[-1]) + 1
        y = self.pos.y() + fm.lineSpacing() * (len(lines) - 1)
        return QLineF(x, y + 2, x, y + fm.height() - 2)

    def is_empty(self) -> bool:
        return not self.text.strip()

    def bounds(self) -> QRectF:
        return self.bounds_text().adjusted(-8, -6, 10, 6)

    def paint(self, p: QPainter) -> None:
        f = self.font()
        fm = QFontMetricsF(f)
        p.setFont(f)
        p.setPen(self.color)
        for i, line in enumerate(self.lines()):
            p.drawText(QPointF(self.pos.x(), self.pos.y() + fm.ascent() + i * fm.lineSpacing()), line)


@dataclass
class MarkerStroke(PenStroke):
    """Маркер: широкая полупрозрачная линия, как у текстовыделителя."""

    ALPHA = 0.38

    def paint(self, p: QPainter) -> None:
        if not self.points:
            return
        p.save()
        c = QColor(self.color)
        c.setAlphaF(self.ALPHA)
        pen = QPen(c, self.width)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap if len(self.points) == 2 else Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Весь штрих рисуется одним путём — полупрозрачность не «накладывается» сама на себя
        path = QPainterPath(self.points[0])
        if len(self.points) == 1:
            path.lineTo(self.points[0] + QPointF(0.01, 0))
        for a, b in zip(self.points[1:-1], self.points[2:], strict=True):
            path.quadTo(a, (a + b) / 2)
        if len(self.points) > 1:
            path.lineTo(self.points[-1])
        p.drawPath(path)
        p.restore()


def marker_width(width: float) -> float:
    return max(12.0, width * 3.0)


@dataclass
class PixelateShape(TwoPointShape):
    """Пикселизация области: берёт пиксели исходного скриншота (не нарисованных фигур)
    и укрупняет их блоками. Восстановить исходное изображение по такому результату нельзя."""

    source: QImage | None = None     # снимок экрана в физических пикселях
    dpr: float = 1.0
    _cache_key: tuple | None = None
    _cache: QImage | None = None

    def block(self) -> int:
        return max(6, int(self.width * 2.5))   # размер «пикселя» в физических пикселях экрана

    def _pixelated(self) -> QImage | None:
        r = self.rect()
        if self.source is None or r.width() < 1 or r.height() < 1:
            return None
        key = (r.x(), r.y(), r.width(), r.height(), self.block())
        if key != self._cache_key:
            dev = QRectF(r.x() * self.dpr, r.y() * self.dpr, r.width() * self.dpr, r.height() * self.dpr).toRect()
            dev = dev.intersected(self.source.rect())
            if dev.isEmpty():
                return None
            b = self.block()
            small = self.source.copy(dev).scaled(max(1, dev.width() // b), max(1, dev.height() // b),
                                                 Qt.AspectRatioMode.IgnoreAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
            self._cache = small
            self._cache_key = key
        return self._cache

    def paint(self, p: QPainter) -> None:
        img = self._pixelated()
        if img is None:
            return
        p.save()
        # увеличиваем «ступеньками», без сглаживания — получаются чёткие квадраты
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(self.rect(), img)
        p.restore()

    def bounds(self) -> QRectF:
        return self.rect().adjusted(-2, -2, 2, 2)

    def is_empty(self) -> bool:
        r = self.rect()
        return r.width() < 3 or r.height() < 3


@dataclass
class StepShape(Shape):
    """Нумерованный шаг: цветной кружок с номером — для инструкций."""

    pos: QPointF = field(default_factory=QPointF)
    number: int = 1

    def radius(self) -> float:
        return 11 + self.width * 1.6

    def paint(self, p: QPainter) -> None:
        r = self.radius()
        p.save()
        p.setPen(QPen(QColor(255, 255, 255, 230), max(1.5, r * 0.12)))
        p.setBrush(self.color)
        p.drawEllipse(self.pos, r, r)
        f = QFont()
        f.setPixelSize(int(r * (1.05 if self.number < 10 else 0.85)))
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        # белая цифра на светлом кружке не видна — тогда цифра тёмная
        p.setPen(QColor("#1C1C1E") if self.color.lightnessF() > 0.72 else QColor("#FFFFFF"))
        p.drawText(QRectF(self.pos.x() - r, self.pos.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter,
                   str(self.number))
        p.restore()

    def bounds(self) -> QRectF:
        r = self.radius() + 3
        return QRectF(self.pos.x() - r, self.pos.y() - r, 2 * r, 2 * r)
