"""Сессия захвата области: по оверлею на каждый монитор, общий результат."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QCursor, QImage

from ..capture import ScreenShot
from ..theme import Tokens
from .overlay import Overlay


class CaptureSession(QObject):
    copy_requested = Signal(QImage)
    save_requested = Signal(QImage)
    style_changed = Signal(QColor, int)
    finished = Signal()

    def __init__(self, shots: list[ScreenShot], tokens: Tokens, color: QColor, width: int) -> None:
        super().__init__()
        self._done = False
        self.overlays: list[Overlay] = []
        for shot in shots:
            o = Overlay(shot, tokens, color, width)
            o.selection_started.connect(self._on_selection_started)
            o.copy_requested.connect(lambda img: self._finish(self.copy_requested, img))
            o.save_requested.connect(lambda img: self._finish(self.save_requested, img))
            o.cancelled.connect(lambda: self._finish(None, None))
            o.style_changed.connect(self._on_style_changed)
            self.overlays.append(o)

    def start(self) -> None:
        cursor = QCursor.pos()
        for o in self.overlays:
            o.open(focus=False)
        # Фокус клавиатуры — оверлею на мониторе под курсором
        target = next((o for o in self.overlays if o.geometry().contains(cursor)), self.overlays[0])
        target.activate()

    def _on_selection_started(self, source: Overlay) -> None:
        for o in self.overlays:
            if o is not source:
                o.reset_selection()

    def _on_style_changed(self, color: QColor, width: int) -> None:
        for o in self.overlays:
            o.set_style(color, width)
        self.style_changed.emit(color, width)

    def _finish(self, signal, image) -> None:
        if self._done:
            return
        self._done = True
        # Сначала убираем оверлеи, потом отдаём картинку (буфер обмена / диск)
        for o in self.overlays:
            o.close()
        self.overlays.clear()
        if signal is not None:
            signal.emit(image)
        self.finished.emit()
