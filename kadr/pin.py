"""Закреплённый скриншот: небольшое окно поверх всех окон.

Удобно, чтобы держать перед глазами образец, пока работаешь в другой программе.
  • перетаскивание мышью, край или угол — изменить размер (пропорции сохраняются);
  • колесо — масштаб, Ctrl+колесо — прозрачность;
  • двойной клик или Esc — закрыть, правый клик — меню (копировать, сохранить…).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

BORDER = 1
EDGE = 8                 # зона у края, за которую тянут размер
MIN_SCALE, MAX_SCALE = 0.1, 8.0

_EDGE_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
}


class PinWindow(QWidget):
    copy_requested = Signal(QImage)
    save_requested = Signal(QImage)
    closed = Signal(object)

    def __init__(self, image: QImage, dpr: float, top_left: QPoint, accent: str = "#3F6BFF") -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Kadr — закреплённый снимок")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMouseTracking(True)
        self.setToolTip("Перетащите · тяните за край — размер · колесо — масштаб · "
                        "Ctrl+колесо — прозрачность · двойной клик или Esc — закрыть · правый клик — меню")
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._pixmap.setDevicePixelRatio(dpr)
        self._base = QRectF(0, 0, image.width() / dpr, image.height() / dpr).size()
        self._scale = 1.0
        self._accent = QColor(accent)
        self._drag: QPoint | None = None
        self._edge: str | None = None           # какой край тянем
        self._resize_start: tuple[QPoint, QRect, float] | None = None
        self._resize_to_scale()
        self.move(top_left - QPoint(BORDER, BORDER))

    def _resize_to_scale(self) -> None:
        w = max(40, round(self._base.width() * self._scale)) + 2 * BORDER
        h = max(30, round(self._base.height() * self._scale)) + 2 * BORDER
        self.resize(w, h)

    # ----------------------------------------------------------------- events
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(QRect(BORDER, BORDER, self.width() - 2 * BORDER, self.height() - 2 * BORDER), self._pixmap)
        p.setPen(QPen(self._accent, BORDER))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))

    def _edge_at(self, pos) -> str | None:
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        # маленький снимок: зона края не должна съедать всю площадь для перетаскивания
        k = min(EDGE, w / 4, h / 4)
        v = "t" if y < k else "b" if y >= h - k else ""
        hz = "l" if x < k else "r" if x >= w - k else ""
        return (v + hz) or None

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        gp = e.globalPosition().toPoint()
        self._edge = self._edge_at(e.position())
        if self._edge:
            self._resize_start = (gp, self.geometry(), self._scale)
        else:
            self._drag = gp - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        gp = e.globalPosition().toPoint()
        if self._edge and self._resize_start and e.buttons() & Qt.MouseButton.LeftButton:
            self._resize_by_edge(gp)
        elif self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(gp - self._drag)
        else:
            edge = self._edge_at(e.position())
            self.setCursor(_EDGE_CURSORS[edge] if edge else Qt.CursorShape.SizeAllCursor)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = None
        self._edge = None
        self._resize_start = None

    def _resize_by_edge(self, gp: QPoint) -> None:
        """Размер меняется с сохранением пропорций; противоположный край стоит на месте."""
        start, geo, scale = self._resize_start
        d, edge = gp - start, self._edge
        bw, bh = self._base.width(), self._base.height()
        w0, h0 = geo.width() - 2 * BORDER, geo.height() - 2 * BORDER
        candidates = []
        if "l" in edge or "r" in edge:
            candidates.append((w0 + (d.x() if "r" in edge else -d.x())) / bw)
        if "t" in edge or "b" in edge:
            candidates.append((h0 + (d.y() if "b" in edge else -d.y())) / bh)
        # угол: берём то направление, в котором тянут сильнее
        new = max(candidates, key=lambda c: abs(c - scale))
        self._scale = min(MAX_SCALE, max(MIN_SCALE, new))
        self._resize_to_scale()
        x = geo.right() + 1 - self.width() if "l" in edge else geo.left()
        y = geo.bottom() + 1 - self.height() if "t" in edge else geo.top()
        self.move(x, y)

    def mouseDoubleClickEvent(self, _e) -> None:
        self.close()

    def wheelEvent(self, e) -> None:
        step = 1 if e.angleDelta().y() > 0 else -1
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.setWindowOpacity(min(1.0, max(0.2, self.windowOpacity() + 0.1 * step)))
        else:
            # масштаб вокруг курсора
            before = e.position()
            old = self._scale
            self._scale = min(MAX_SCALE, max(MIN_SCALE, self._scale * (1.1 if step > 0 else 1 / 1.1)))
            k = self._scale / old
            shift = QPoint(round(before.x() * (k - 1)), round(before.y() * (k - 1)))
            self._resize_to_scale()
            self.move(self.pos() - shift)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif e.key() == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.copy_requested.emit(self._image)

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        for text, fn in (("Копировать", lambda: self.copy_requested.emit(self._image)),
                         ("Сохранить в папку", lambda: self.save_requested.emit(self._image)),
                         ("Исходный размер", self._reset_scale),
                         (None, None),
                         ("Закрыть", self.close)):
            if text is None:
                menu.addSeparator()
            else:
                act = QAction(text, menu)
                act.triggered.connect(fn)
                menu.addAction(act)
        menu.exec(e.globalPos())

    def _reset_scale(self) -> None:
        self._scale = 1.0
        self.setWindowOpacity(1.0)
        self._resize_to_scale()

    def closeEvent(self, e) -> None:
        self.closed.emit(self)
        super().closeEvent(e)
