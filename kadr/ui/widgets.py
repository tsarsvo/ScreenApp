"""Небольшие собственные виджеты для окна настроек."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QHBoxLayout, QPushButton, QWidget

from ..hotkeys import hotkey_from_event, label_for
from ..theme import Tokens


class ToggleSwitch(QAbstractButton):
    """iOS-подобный тумблер с анимацией бегунка."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._t: Tokens | None = None
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def apply_theme(self, t: Tokens) -> None:
        self._t = t
        self.update()

    def setChecked(self, on: bool) -> None:  # без анимации при программной установке
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float) -> None:
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def paintEvent(self, _event) -> None:
        if not self._t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, 38, 22).translated(0, (self.height() - 22) / 2)
        off, on = QColor(self._t.border), QColor(self._t.accent)
        k = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * k), int(off.green() + (on.green() - off.green()) * k),
                       int(off.blue() + (on.blue() - off.blue()) * k))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, 11, 11)
        p.setBrush(QColor("#FFFFFF"))
        x = r.left() + 2 + k * (r.width() - 22)
        p.drawEllipse(QRectF(x, r.top() + 2, 18, 18))


class HotkeyEdit(QPushButton):
    """Кнопка записи сочетания: клик → нажмите сочетание → готово.
    Esc — отмена, Backspace/Delete — очистить."""

    recording_changed = Signal(bool)
    hotkey_changed = Signal(str)
    error = Signal(str)

    def __init__(self, value: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Hotkey")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value = value
        self._recording = False
        self.clicked.connect(self._start)
        self._refresh()

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        self._refresh()

    def _refresh(self) -> None:
        self.setProperty("recording", self._recording)
        self.setText("Нажмите сочетание…" if self._recording else label_for(self._value))
        self.style().unpolish(self)
        self.style().polish(self)

    def _start(self) -> None:
        if self._recording:
            return
        self._recording = True
        self.grabKeyboard()
        self.recording_changed.emit(True)
        self._refresh()

    def _stop(self) -> None:
        self._recording = False
        self.releaseKeyboard()
        self.recording_changed.emit(False)
        self._refresh()

    def focusOutEvent(self, e) -> None:
        if self._recording:
            self._stop()
        super().focusOutEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not self._recording:
            return super().keyPressEvent(e)
        if e.key() == Qt.Key.Key_Escape and not e.modifiers():
            self._stop()
            return
        if e.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not e.modifiers():
            self._value = ""
            self._stop()
            self.hotkey_changed.emit("")
            return
        result = hotkey_from_event(e)
        if result is None:
            return  # пока нажаты только модификаторы
        if isinstance(result, str):
            self.error.emit(result)
            return
        self._value = result.serialize()
        self._stop()
        self.hotkey_changed.emit(self._value)


class Segmented(QWidget):
    """Сегментированный переключатель (PNG | JPG | WEBP)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._group = QButtonGroup(self)
        for i, (key, text) in enumerate(options):
            b = QPushButton(text, self)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("first", i == 0)
            b.setProperty("last", i == len(options) - 1)
            b.setProperty("key", key)
            b.setChecked(key == value)
            self._group.addButton(b)
            row.addWidget(b)
        self._group.buttonClicked.connect(lambda b: self.changed.emit(b.property("key")))
