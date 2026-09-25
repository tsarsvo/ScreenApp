"""Закреплённый скриншот: небольшое окно поверх всех окон.

Удобно, чтобы держать перед глазами образец, пока работаешь в другой программе.
  • перетаскивание мышью, колесо — масштаб, Ctrl+колесо — прозрачность;
  • двойной клик или Esc — закрыть, правый клик — меню (копировать, сохранить…).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QWidget

BORDER = 1


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
        self.setToolTip("Перетащите · колесо — масштаб · Ctrl+колесо — прозрачность · "
                        "двойной клик или Esc — закрыть · правый клик — меню")
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._pixmap.setDevicePixelRatio(dpr)
        self._base = QRectF(0, 0, image.width() / dpr, image.height() / dpr).size()
        self._scale = 1.0
        self._accent = QColor(accent)
        self._drag: QPoint | None = None
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

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = None

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
            self._scale = min(4.0, max(0.2, self._scale * (1.1 if step > 0 else 1 / 1.1)))
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
