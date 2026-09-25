"""Полноэкранный оверлей: выделение области, рисование, экспорт.

На каждый монитор создаётся свой оверлей (см. session.py) — это корректно работает
с разным масштабом (DPI) на разных экранах.

Координаты:
  * всё, что видит пользователь (выделение, фигуры) — логические пиксели виджета;
  * self._shot.pixmap — физические пиксели экрана (devicePixelRatio выставлен),
    поэтому при экспорте фрагмент вырезается без потери качества.
"""
from __future__ import annotations

import math
import sys

from PySide6.QtCore import QEasingCurve, QLineF, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication, QImage, QKeyEvent, QKeySequence, QMouseEvent,
                           QPainter, QPainterPath, QPen, QWheelEvent)
from PySide6.QtWidgets import QWidget

from ..capture import ScreenShot
from ..hotkeys import _MAC_VK
from ..theme import Tokens
from .history import History
from .shapes import (ArrowShape, EllipseShape, PenStroke, RectShape, Shape, TextShape, Tool, TwoPointShape,
                     font_px_for_width)
from .toolbar import SHADOW, StylePopup, Toolbar

DIM_ALPHA = 115          # непрозрачность затемнения (из 255) — примерно 45%
HANDLE_R = 4.0           # радиус «ручки» изменения размера
HANDLE_HIT = 9           # зона попадания по ручке
GAP = 8                  # отступ панели от выделения

# Ручки: (id, доля по x, доля по y)
_HANDLES = [("tl", 0, 0), ("t", .5, 0), ("tr", 1, 0), ("r", 1, .5),
            ("br", 1, 1), ("b", .5, 1), ("bl", 0, 1), ("l", 0, .5)]
_HANDLE_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
}
_TOOL_KEYS = {Qt.Key.Key_V: Tool.SELECT, Qt.Key.Key_P: Tool.PEN, Qt.Key.Key_A: Tool.ARROW,
              Qt.Key.Key_R: Tool.RECT, Qt.Key.Key_E: Tool.ELLIPSE, Qt.Key.Key_T: Tool.TEXT}


def _is_key(event: QKeyEvent, key: Qt.Key) -> bool:
    """Сравнение клавиши, устойчивое к раскладке (Ctrl+Я на русской = Ctrl+Z)."""
    if event.key() == key:
        return True
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        vk = event.nativeVirtualKey()
        if sys.platform == "win32":
            return vk == int(key)  # VK_A..VK_Z совпадают с ASCII
        if sys.platform == "darwin":
            return _MAC_VK.get(chr(key).lower()) == vk
    return False


class Overlay(QWidget):
    selection_started = Signal(object)   # self — чтобы сессия сбросила выделение на других экранах
    copy_requested = Signal(QImage)
    save_requested = Signal(QImage)
    cancelled = Signal()
    style_changed = Signal(QColor, int)

    def __init__(self, shot: ScreenShot, tokens: Tokens, color: QColor, width: int) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if sys.platform != "darwin":
            flags |= Qt.WindowType.Tool  # не показывать в панели задач
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(shot.geometry)

        self._shot = shot
        self._t = tokens
        self._color = QColor(color)
        self._width = width
        self._tool = Tool.SELECT
        self._history = History()

        self._sel: QRect | None = None
        self._mode = "idle"            # idle | selecting | moving | resizing | drawing
        self._press = QPoint()
        self._sel_origin = QRect()
        self._handle: str | None = None
        self._current: Shape | None = None
        self._editing: TextShape | None = None
        self._mouse = QPoint(-100, -100)

        # Плавное появление затемнения
        self._dim = 0.0
        self._dim_anim = QVariantAnimation(self)
        self._dim_anim.setStartValue(0.0)
        self._dim_anim.setEndValue(1.0)
        self._dim_anim.setDuration(220)
        self._dim_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._dim_anim.valueChanged.connect(self._set_dim)

        # Мигающая каретка для инструмента «Текст»
        self._caret_on = True
        self._caret_timer = QTimer(self)
        self._caret_timer.setInterval(530)
        self._caret_timer.timeout.connect(self._blink)

        # Подсказка толщины при Ctrl+колесо
        self._width_hint = False
        self._width_hint_timer = QTimer(self)
        self._width_hint_timer.setSingleShot(True)
        self._width_hint_timer.setInterval(700)
        self._width_hint_timer.timeout.connect(self._hide_width_hint)

        self.toolbar = Toolbar(self)
        self.toolbar.hide()
        self.toolbar.tool_selected.connect(self.set_tool)
        self.toolbar.undo.connect(self.undo)
        self.toolbar.redo.connect(self.redo)
        self.toolbar.copy.connect(self._copy)
        self.toolbar.save.connect(self._save)
        self.toolbar.cancel.connect(self.cancelled)
        self.toolbar.style_clicked.connect(self._toggle_popup)

        self.popup = StylePopup(self)
        self.popup.color_changed.connect(self._set_color)
        self.popup.width_changed.connect(self._set_width)

        self.apply_theme(tokens)
        self.toolbar.set_tool(self._tool)
        self._sync_toolbar()

    # ------------------------------------------------------------------ public
    def open(self, focus: bool) -> None:
        if sys.platform == "darwin":
            self.show()  # showFullScreen на macOS создаёт отдельный Space
        else:
            self.showFullScreen()
        self.setGeometry(self._shot.geometry)
        self._dim_anim.start()
        if focus:
            self.activate()

    def activate(self) -> None:
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def apply_theme(self, t: Tokens) -> None:
        self._t = t
        self.toolbar.apply_theme(t)
        self.popup.apply_theme(t)
        self.update()

    def reset_selection(self) -> None:
        """Вызывается, когда пользователь начал выделение на другом мониторе."""
        self._commit_text()
        self._sel = None
        self._history = History()
        self._mode = "idle"
        self.toolbar.hide()
        self.popup.hide()
        self.update()

    def render_selection(self) -> QImage:
        """Вырезает выделенную область в физических пикселях и рисует на ней фигуры."""
        self._commit_text()
        sel = self._sel or self.rect()
        dpr = self._shot.dpr
        src = QRect(round(sel.x() * dpr), round(sel.y() * dpr),
                    max(1, round(sel.width() * dpr)), max(1, round(sel.height() * dpr)))
        img = self._shot.pixmap.copy(src).toImage().convertToFormat(QImage.Format.Format_RGB32)
        img.setDevicePixelRatio(1.0)
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.scale(src.width() / sel.width(), src.height() / sel.height())
        p.translate(-sel.topLeft())
        for s in self._history.shapes:
            s.paint(p)
        p.end()
        return img

    # ------------------------------------------------------------ tools/style
    def set_tool(self, tool: Tool) -> None:
        self._commit_text()
        self._tool = tool
        self.toolbar.set_tool(tool)
        self.popup.hide()
        self._update_cursor(self._mouse)

    def _set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        if self._editing:
            self._editing.color = QColor(color)
        self._sync_toolbar()
        self.style_changed.emit(self._color, self._width)
        self.update()

    def _set_width(self, width: int) -> None:
        self._width = max(1, min(40, width))
        if self._editing:
            self._editing.width = self._width
        self._sync_toolbar()
        self.style_changed.emit(self._color, self._width)
        self.update()

    def set_style(self, color: QColor, width: int) -> None:
        """Синхронизация стиля с другими мониторами (без повторного сигнала)."""
        self._color, self._width = QColor(color), width
        self._sync_toolbar()

    def _sync_toolbar(self) -> None:
        self.toolbar.set_style(self._color, self._width)
        self.toolbar.set_history_state(self._history.can_undo(), self._history.can_redo())
        self.popup.set_style(self._color, self._width)

    # ------------------------------------------------------------------ undo
    def undo(self) -> None:
        if self._editing:  # сначала отменяем незавершённый текст
            self._editing = None
            self._caret_timer.stop()
        elif not self._history.undo():
            return
        self._sync_toolbar()
        self.update()

    def redo(self) -> None:
        self._commit_text()
        if self._history.redo():
            self._sync_toolbar()
            self.update()

    # ------------------------------------------------------------- actions
    def _copy(self) -> None:
        if self._sel:
            self.copy_requested.emit(self.render_selection())

    def _save(self) -> None:
        if self._sel:
            self.save_requested.emit(self.render_selection())

    def _toggle_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
            return
        self.popup.adjustSize()
        tb = self.toolbar.geometry()
        btn = self.toolbar.style_btn.geometry().translated(tb.topLeft())
        x = btn.center().x() - self.popup.width() // 2
        x = max(-SHADOW + 4, min(x, self.width() - self.popup.width() + SHADOW - 4))
        below = tb.bottom() - SHADOW + GAP - SHADOW
        above = tb.top() + SHADOW - GAP - self.popup.height() + SHADOW
        fits_below = below + self.popup.height() - SHADOW <= self.height()
        # Открываем в сторону «от выделения», чтобы не закрывать скриншот
        toolbar_above_sel = self._sel and tb.center().y() < self._sel.center().y()
        if fits_below and not (toolbar_above_sel and above >= -SHADOW):
            self.popup.appear_at(QPoint(x, below), QPoint(0, -6))
        else:
            self.popup.appear_at(QPoint(x, above))

    # -------------------------------------------------------------- geometry
    def _handle_points(self) -> list[tuple[str, QPointF]]:
        r = QRectF(self._sel)
        return [(hid, QPointF(r.left() + fx * r.width(), r.top() + fy * r.height())) for hid, fx, fy in _HANDLES]

    def _hit_handle(self, pos: QPoint) -> str | None:
        if not self._sel:
            return None
        for hid, pt in self._handle_points():
            if abs(pt.x() - pos.x()) <= HANDLE_HIT and abs(pt.y() - pos.y()) <= HANDLE_HIT:
                return hid
        return None

    def _place_toolbar(self) -> None:
        """Панель рядом с выделением, не перекрывая его: снизу → сверху → внутри (крайний случай)."""
        if not self._sel:
            return
        self.toolbar.adjustSize()
        tw, th = self.toolbar.width(), self.toolbar.height()
        body_h = th - 2 * SHADOW
        s = self._sel
        x = s.right() + 1 - tw + SHADOW                      # выравнивание по правому краю
        x = max(-SHADOW + 4, min(x, self.width() - tw + SHADOW - 4))
        if s.bottom() + GAP + body_h <= self.height() - 4:
            y = s.bottom() + GAP - SHADOW
        elif s.top() - GAP - body_h >= 4:
            y = s.top() - GAP - body_h - SHADOW
        else:
            y = s.bottom() - GAP - body_h - SHADOW           # экран занят целиком — внутри снизу
        self.toolbar.appear_at(QPoint(x, y))

    # ----------------------------------------------------------------- mouse
    def mousePressEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        self.popup.hide()
        if e.button() == Qt.MouseButton.RightButton:
            # ПКМ: сбросить выделение, а если его нет — закрыть оверлей
            if self._sel and not self._history and not self._editing:
                self.reset_selection()
            else:
                self.cancelled.emit()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return

        self._commit_text()
        self._press = pos
        handle = self._hit_handle(pos)
        if handle:
            self._mode, self._handle, self._sel_origin = "resizing", handle, QRect(self._sel)
            self.toolbar.hide()
        elif self._sel and self._sel.contains(pos) and self._tool != Tool.SELECT:
            self._start_drawing(QPointF(e.position()))
        elif self._sel and self._sel.contains(pos):
            self._mode, self._sel_origin = "moving", QRect(self._sel)
            self.toolbar.hide()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif not self._sel or (self._tool == Tool.SELECT and not self._history):
            # Новое выделение (если на старом ещё ничего не нарисовано)
            self._mode = "selecting"
            self._sel = QRect(pos, QSize(0, 0))
            self.toolbar.hide()
            self.selection_started.emit(self)
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        self._mouse = pos
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        bounds = self.rect()

        if self._mode == "selecting":
            end = self._constrain_square(self._press, pos) if shift else pos
            self._sel = QRect(self._press, end).normalized().intersected(bounds)
        elif self._mode == "moving":
            r = self._sel_origin.translated(pos - self._press)
            r.moveLeft(max(0, min(r.left(), bounds.width() - r.width())))
            r.moveTop(max(0, min(r.top(), bounds.height() - r.height())))
            self._sel = r
        elif self._mode == "resizing":
            self._sel = self._resized(pos).intersected(bounds)
        elif self._mode == "drawing" and self._current:
            self._continue_drawing(QPointF(e.position()), shift)
        else:
            self._update_cursor(pos)
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        mode, self._mode = self._mode, "idle"
        if mode == "selecting":
            if self._sel.width() < 3 or self._sel.height() < 3:
                self._sel = QRect(self.rect())  # простой клик — весь экран
            self._place_toolbar()
        elif mode in ("moving", "resizing"):
            if self._sel.width() < 3 or self._sel.height() < 3:
                self._sel = QRect(self._sel_origin)
            self._place_toolbar()
        elif mode == "drawing" and self._current:
            shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._continue_drawing(QPointF(e.position()), shift)
            if not self._current.is_empty():
                self._history.push(self._current)
                self._sync_toolbar()
            self._current = None
        self._update_cursor(e.position().toPoint())
        self.update()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        # Двойной клик внутри выделения в режиме «Выделение» — сразу скопировать
        if self._tool == Tool.SELECT and self._sel and self._sel.contains(e.position().toPoint()):
            self._copy()

    def wheelEvent(self, e: QWheelEvent) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            step = 1 if e.angleDelta().y() > 0 else -1 if e.angleDelta().y() < 0 else 0
            if step:
                self._set_width(self._width + step)
                self._width_hint = True
                self._width_hint_timer.start()
            e.accept()

    def enterEvent(self, e) -> None:
        # Несколько мониторов: клавиатура следует за мышью
        if not self.isActiveWindow():
            self.activate()
        super().enterEvent(e)

    def _update_cursor(self, pos: QPoint) -> None:
        handle = self._hit_handle(pos)
        if handle:
            self.setCursor(_HANDLE_CURSORS[handle])
        elif self._sel and self._sel.contains(pos):
            if self._tool == Tool.SELECT:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._tool == Tool.TEXT:
                self.setCursor(Qt.CursorShape.IBeamCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _resized(self, pos: QPoint) -> QRect:
        o, h = self._sel_origin, self._handle
        d = pos - self._press
        left, top, right, bottom = o.left(), o.top(), o.right(), o.bottom()
        if "l" in h:
            left += d.x()
        if "r" in h:
            right += d.x()
        if "t" in h:
            top += d.y()
        if "b" in h:
            bottom += d.y()
        return QRect(QPoint(left, top), QPoint(right, bottom)).normalized()

    @staticmethod
    def _constrain_square(a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        side = max(abs(dx), abs(dy))
        return type(b)(a.x() + math.copysign(side, dx or 1), a.y() + math.copysign(side, dy or 1))

    # --------------------------------------------------------------- drawing
    def _start_drawing(self, pos: QPointF) -> None:
        c, w = QColor(self._color), self._width
        if self._tool == Tool.TEXT:
            self._editing = TextShape(c, w, pos=pos - QPointF(0, font_px_for_width(w) * 0.6))
            self._caret_on = True
            self._caret_timer.start()
            return
        self._mode = "drawing"
        if self._tool == Tool.PEN:
            self._current = PenStroke(c, w, points=[pos])
        else:
            cls = {Tool.ARROW: ArrowShape, Tool.RECT: RectShape, Tool.ELLIPSE: EllipseShape}[self._tool]
            self._current = cls(c, w, start=pos, end=pos)

    def _continue_drawing(self, pos: QPointF, shift: bool) -> None:
        cur = self._current
        if isinstance(cur, PenStroke):
            if QLineF(cur.points[-1], pos).length() >= 1.0:
                cur.points.append(pos)
        elif isinstance(cur, TwoPointShape):
            if shift and isinstance(cur, ArrowShape):
                # Shift: стрелка с шагом 45°
                line = QLineF(cur.start, pos)
                line.setAngle(round(line.angle() / 45) * 45)
                pos = line.p2()
            elif shift:
                pos = self._constrain_square(cur.start, pos)  # квадрат / круг
            cur.end = pos

    def _commit_text(self) -> None:
        if not self._editing:
            return
        if not self._editing.is_empty():
            self._history.push(self._editing)
        self._editing = None
        self._caret_timer.stop()
        self._sync_toolbar()
        self.update()

    def _blink(self) -> None:
        self._caret_on = not self._caret_on
        self.update()

    def _set_dim(self, v) -> None:
        self._dim = float(v)
        self.update()

    def _hide_width_hint(self) -> None:
        self._width_hint = False
        self.update()

    # -------------------------------------------------------------- keyboard
    def keyPressEvent(self, e: QKeyEvent) -> None:
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if self._editing and self._text_key(e, ctrl, shift):
            return

        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif ctrl and _is_key(e, Qt.Key.Key_Z):
            self.redo() if shift else self.undo()
        elif ctrl and _is_key(e, Qt.Key.Key_Y):
            self.redo()
        elif ctrl and _is_key(e, Qt.Key.Key_C) or e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._copy()
        elif ctrl and _is_key(e, Qt.Key.Key_S):
            self._save()
        elif self._sel and not ctrl:
            for key, tool in _TOOL_KEYS.items():
                if _is_key(e, key):
                    self.set_tool(tool)
                    break

    def _text_key(self, e: QKeyEvent, ctrl: bool, shift: bool) -> bool:
        """Ввод текста прямо на скриншоте. True — событие обработано."""
        ed = self._editing
        if e.key() == Qt.Key.Key_Escape:
            self._commit_text()
            return True
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if shift:
                ed.text += "\n"
            else:
                self._commit_text()
        elif e.key() == Qt.Key.Key_Backspace:
            ed.text = ed.text[:-1]
        elif e.matches(QKeySequence.StandardKey.Paste):
            ed.text += QGuiApplication.clipboard().text()
        elif ctrl:
            return False  # Ctrl+Z и т.п. обрабатываются как обычно
        elif e.text() and e.text().isprintable():
            ed.text += e.text()
        else:
            return False
        self._caret_on = True
        self._caret_timer.start()
        self.update()
        return True

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        p.drawPixmap(0, 0, self._shot.pixmap)

        # Затемнение вокруг выделения (с анимацией появления)
        dim = QColor(0, 0, 0, int(DIM_ALPHA * self._dim))
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        if self._sel and not self._sel.isEmpty():
            inner = QPainterPath()
            inner.addRect(QRectF(self._sel))
            outside = outside.subtracted(inner)
        p.fillPath(outside, dim)

        if not self._sel:
            self._paint_guides(p)
            self._paint_hint(p)
            return

        # Фигуры обрезаются по границе выделения — ровно так, как попадут в файл
        p.save()
        p.setClipRect(self._sel)
        for s in self._history.shapes:
            s.paint(p)
        if self._current:
            self._current.paint(p)
        if self._editing:
            self._paint_text_editor(p)
        p.restore()

        self._paint_frame(p)
        self._paint_size_label(p)
        if self._width_hint:
            self._paint_width_hint(p)

    def _paint_frame(self, p: QPainter) -> None:
        accent = self._t.q("accent")
        pen = QPen(accent, 1.5)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self._sel).adjusted(-0.5, -0.5, 0.5, 0.5))
        if self._mode in ("drawing",):
            return
        p.setBrush(QColor("#FFFFFF"))
        for _hid, pt in self._handle_points():
            p.drawEllipse(pt, HANDLE_R, HANDLE_R)

    def _pill(self, p: QPainter, rect: QRectF, text: str, font: QFont) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 22, 200))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_size_label(self, p: QPainter) -> None:
        dpr = self._shot.dpr
        text = f"{round(self._sel.width() * dpr)} × {round(self._sel.height() * dpr)}"
        f = QFont()
        f.setPixelSize(11)
        f.setWeight(QFont.Weight.Medium)
        w = QFontMetrics(f).horizontalAdvance(text) + 16
        y = self._sel.top() - 26 if self._sel.top() >= 30 else self._sel.top() + 6
        x = self._sel.left() if self._sel.top() >= 30 else self._sel.left() + 6
        self._pill(p, QRectF(x, y, w, 20), text, f)

    def _paint_hint(self, p: QPainter) -> None:
        text = "Выделите область  ·  клик — весь экран  ·  Esc — отмена"
        f = QFont()
        f.setPixelSize(12)
        w = QFontMetrics(f).horizontalAdvance(text) + 28
        p.setOpacity(self._dim)
        self._pill(p, QRectF((self.width() - w) / 2, 24, w, 30), text, f)
        p.setOpacity(1.0)

    def _paint_guides(self, p: QPainter) -> None:
        """Тонкие направляющие через курсор — помогают точно начать выделение."""
        if not self.rect().contains(self._mouse):
            return
        pen = QPen(QColor(255, 255, 255, int(70 * self._dim)), 1)
        pen.setCosmetic(True)
        p.setPen(pen)
        m = QPointF(self._mouse) + QPointF(0.5, 0.5)
        p.drawLine(QPointF(0, m.y()), QPointF(self.width(), m.y()))
        p.drawLine(QPointF(m.x(), 0), QPointF(m.x(), self.height()))

    def _paint_text_editor(self, p: QPainter) -> None:
        ed = self._editing
        ed.paint(p)
        box = ed.bounds().adjusted(-4, -2, 6, 2)
        pen = QPen(self._t.q("accent"), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, 3, 3)
        if self._caret_on:
            p.setPen(QPen(ed.color, 1.5))
            p.drawLine(ed.caret_line())

    def _paint_width_hint(self, p: QPainter) -> None:
        center = QPointF(self._mouse)
        r = self._width / 2
        p.setPen(QPen(QColor(255, 255, 255, 220), 1))
        p.setBrush(self._color)
        p.drawEllipse(center, max(r, 1.5), max(r, 1.5))
        f = QFont()
        f.setPixelSize(11)
        text = f"{self._width}px"
        w = QFontMetrics(f).horizontalAdvance(text) + 14
        self._pill(p, QRectF(center.x() + r + 8, center.y() - 10, w, 20), text, f)
