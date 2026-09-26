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
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QKeyEvent, QKeySequence,
                           QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QTransform, QWheelEvent)
from PySide6.QtWidgets import QWidget

from ..capture import ScreenShot
from ..hotkeys import _MAC_VK
from ..theme import Tokens
from .history import History
from .shapes import (ArrowShape, EllipseShape, LineShape, MarkerStroke, PenStroke, PixelateShape, RectShape, Shape, StepShape,
                     TextShape, Tool, TwoPointShape, font_px_for_width, marker_width)
from .toolbar import SHADOW, StylePopup, Toolbar

DIM_ALPHA = 115          # непрозрачность затемнения (из 255) — примерно 45%
HANDLE_R = 4.0           # радиус «ручки» изменения размера
HANDLE_HIT = 9           # зона попадания по ручке
GAP = 8                  # отступ панели от выделения
MIN_SELECTION = 4        # меньше — считаем кликом, а не выделением
GUIDE_PAD = 3            # запас при перерисовке направляющих (дробный масштаб Windows)

# Ручки: (id, доля по x, доля по y)
_HANDLES = [("tl", 0, 0), ("t", .5, 0), ("tr", 1, 0), ("r", 1, .5),
            ("br", 1, 1), ("b", .5, 1), ("bl", 0, 1), ("l", 0, .5)]
_HANDLE_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
}
_TOOL_KEYS = {Qt.Key.Key_V: Tool.SELECT, Qt.Key.Key_P: Tool.PEN, Qt.Key.Key_A: Tool.ARROW, Qt.Key.Key_L: Tool.LINE,
              Qt.Key.Key_R: Tool.RECT, Qt.Key.Key_E: Tool.ELLIPSE, Qt.Key.Key_T: Tool.TEXT,
              Qt.Key.Key_M: Tool.MARKER, Qt.Key.Key_B: Tool.PIXELATE, Qt.Key.Key_N: Tool.STEP}


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


class _Fonts:
    """Шрифты подписей создаются один раз, а не в каждом кадре."""

    def __init__(self) -> None:
        self.small_medium = QFont()
        self.small_medium.setPixelSize(11)
        self.small_medium.setWeight(QFont.Weight.Medium)
        self.small_medium_metrics = QFontMetrics(self.small_medium)
        self.hint = QFont()
        self.hint.setPixelSize(12)
        self.hint_metrics = QFontMetrics(self.hint)


class Overlay(QWidget):
    selection_started = Signal(object)   # self — чтобы сессия сбросила выделение на других экранах
    copy_requested = Signal(QImage)
    save_requested = Signal(QImage)
    cancelled = Signal()
    style_changed = Signal(QColor, int)
    palette_changed = Signal(list)
    pin_requested = Signal(QImage, QPoint, float)   # снимок, левый верхний угол на экране, DPR

    def __init__(self, shot: ScreenShot, tokens: Tokens, color: QColor, width: int,
                 palette: list[str] | None = None) -> None:
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
        # Перетаскивание нумерованного шага
        self._drag_step: StepShape | None = None
        self._drag_from = QPointF()
        self._drag_offset = QPointF()

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
        self.toolbar.pin.connect(self._pin)
        self.toolbar.cancel.connect(self.cancelled)
        self.toolbar.style_clicked.connect(self._toggle_popup)

        self.popup = StylePopup(self, palette)
        self.popup.color_changed.connect(self._set_color)
        self.popup.width_changed.connect(self._set_width)
        self.popup.palette_changed.connect(self.palette_changed)
        self.popup.pick_requested.connect(self.start_picking)
        self.popup.resized.connect(lambda: self._place_popup(animate=False))

        # Пипетка: берём цвет прямо со снимка экрана
        self._picking = False
        self._shot_image: QImage | None = None

        # Кэш: все готовые фигуры нарисованы в прозрачный слой. Перерисовывается он только
        # при undo/redo, а новая фигура просто дорисовывается сверху — поэтому движение
        # мыши не заставляет заново рисовать сотни штрихов.
        # Буфер слоя (экран целиком, ~33 МБ на 4K) создаётся один раз: при сборке заново
        # стирается только та часть, где были фигуры, — первое заполнение нового буфера
        # стоило больше, чем рисование сотни фигур.
        self._layer: QPixmap | None = None
        self._layer_valid = False
        self._layer_dirty = QRect()     # где в буфере могут быть нарисованные фигуры
        self._layer_pending: QRectF | None = None   # что пересобрать при частичной сборке
        self._fonts = _Fonts()

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
        self._layer = None
        self._layer_valid = False
        self._mode = "idle"
        self.toolbar.hide()
        self.popup.hide()
        self.update()

    def select_all(self) -> None:
        """Ctrl+A — выделить весь экран."""
        self._commit_text()
        if self._sel is None:
            self.selection_started.emit(self)
        self._sel = QRect(self.rect())
        self._mode = "idle"
        self._place_toolbar()
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
        else:
            action = self._history.undo()
            if not action:
                return
            if action.sel_before is not None:
                self._set_selection(action.sel_before)
            self._invalidate_layer(self._action_area(action))
        self._sync_toolbar()
        self.update()

    def redo(self) -> None:
        self._commit_text()
        action = self._history.redo()
        if action:
            if action.sel_after is not None:
                self._set_selection(action.sel_after)
            if action.kind == "move":
                self._invalidate_layer(self._action_area(action))
            else:
                self._layer_add(action.shape)       # вернулась последней — просто дорисовать
            self._sync_toolbar()
            self.update()

    def _action_area(self, action) -> QRectF:
        """Где на слое изменилось что-то после отмены/повтора действия."""
        r = QRectF(self._shape_rect(action.shape))
        if action.kind == "move":
            d = action.new_pos - action.old_pos
            r = r.united(r.translated(d)).united(r.translated(-d))
        return r

    def _set_selection(self, r: QRect) -> None:
        self._sel = QRect(r)
        if self.toolbar.isVisible():
            self._place_toolbar()

    def _push_shape(self, shape: Shape) -> None:
        """Готовая фигура → в историю. Если она вышла за край выделения, выделение
        расширяется до неё: в файл попадает ровно то, что нарисовано."""
        before = QRect(self._sel)
        grown = before.united(shape.bounds().toAlignedRect()).intersected(self.rect())
        if grown != before:
            self._history.push(shape, before, grown)
            self._set_selection(grown)
            self._layer_add(shape)
            self.update()
        else:
            self._history.push(shape)
            self._layer_add(shape)

    # ------------------------------------------------------------- actions
    def _copy(self) -> None:
        if self._sel is not None:
            self.copy_requested.emit(self.render_selection())

    def _save(self) -> None:
        if self._sel is not None:
            self.save_requested.emit(self.render_selection())

    def _pin(self) -> None:
        if self._sel is not None:
            self.pin_requested.emit(self.render_selection(), self.mapToGlobal(self._sel.topLeft()), self._shot.dpr)

    def _toggle_popup(self) -> None:
        if self.popup.isVisible():
            self.popup.hide()
            return
        self._place_popup()

    def _place_popup(self, animate: bool = True) -> None:
        self.popup.layout().activate()
        self.popup.adjustSize()
        tb = self.toolbar.geometry()
        btn = self.toolbar.style_btn.geometry().translated(tb.topLeft())
        x = btn.center().x() - self.popup.width() // 2
        x = max(-SHADOW + 4, min(x, self.width() - self.popup.width() + SHADOW - 4))
        below = tb.bottom() - SHADOW + GAP - SHADOW
        above = tb.top() + SHADOW - GAP - self.popup.height() + SHADOW
        fits_below = below + self.popup.height() - SHADOW <= self.height()
        # Открываем в сторону «от выделения», чтобы не закрывать скриншот
        toolbar_above_sel = self._sel is not None and tb.center().y() < self._sel.center().y()
        if fits_below and not (toolbar_above_sel and above >= -SHADOW):
            pos, offset = QPoint(x, below), QPoint(0, -6)
        else:
            pos, offset = QPoint(x, above), QPoint(0, 6)
        # Раскрытый выбор цвета высокий — не даём панели уйти за край экрана
        pos.setY(max(-SHADOW + 4, min(pos.y(), self.height() - self.popup.height() + SHADOW - 4)))
        if animate or not self.popup.isVisible():
            self.popup.appear_at(pos, offset)
        else:
            self.popup.move_now(pos)

    # ------------------------------------------------------------- пипетка
    def _source_image(self) -> QImage:
        """Снимок экрана как QImage (нужен пипетке и пикселизации) — создаётся один раз."""
        if self._shot_image is None:
            self._shot_image = self._shot.pixmap.toImage()
        return self._shot_image

    def start_picking(self) -> None:
        """Режим пипетки: курсор-прицел с лупой, клик берёт цвет пикселя скриншота."""
        self._source_image()
        self._picking = True
        self.popup.hide_for_picking()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._mouse = self.mapFromGlobal(QCursor.pos())
        self.update()

    def _stop_picking(self) -> None:
        self._picking = False
        self._update_cursor(self._mouse)
        self.update()

    def _color_at(self, pos: QPoint) -> QColor:
        img, dpr = self._shot_image, self._shot.dpr
        x = min(max(0, int(pos.x() * dpr)), img.width() - 1)
        y = min(max(0, int(pos.y() * dpr)), img.height() - 1)
        return img.pixelColor(x, y)

    # -------------------------------------------------------------- geometry
    def _handle_points(self) -> list[tuple[str, QPointF]]:
        r = QRectF(self._sel)
        return [(hid, QPointF(r.left() + fx * r.width(), r.top() + fy * r.height())) for hid, fx, fy in _HANDLES]

    def _hit_handle(self, pos: QPoint) -> str | None:
        if self._sel is None:
            return None
        for hid, pt in self._handle_points():
            if abs(pt.x() - pos.x()) <= HANDLE_HIT and abs(pt.y() - pos.y()) <= HANDLE_HIT:
                return hid
        return None

    def _step_at(self, pos: QPoint) -> StepShape | None:
        """Нумерованный шаг, за кружок которого можно взяться (верхний — первым)."""
        if self._sel is None or self._mode == "drawing":
            return None
        pt = QPointF(pos)
        for s in reversed(self._history.shapes):
            if isinstance(s, StepShape) and QLineF(s.pos, pt).length() <= s.radius():
                return s
        return None

    def _place_toolbar(self) -> None:
        """Панель рядом с выделением, не перекрывая его: снизу → сверху → внутри (крайний случай)."""
        if self._sel is None:
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
        if self._picking:
            self._stop_picking()
            if e.button() == Qt.MouseButton.LeftButton:
                self.popup.apply_color(self._color_at(pos))
            self._place_popup()   # показываем панель снова — с выбранным цветом
            return
        self.popup.hide()
        if e.button() == Qt.MouseButton.RightButton:
            # ПКМ: сбросить выделение, а если его нет — закрыть оверлей
            if self._sel is not None and not self._history and not self._editing:
                self.reset_selection()
            else:
                self.cancelled.emit()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return

        self._commit_text()
        self._press = pos
        handle = self._hit_handle(pos)
        step = None if handle else self._step_at(pos)
        if handle:
            self._mode, self._handle, self._sel_origin = "resizing", handle, QRect(self._sel)
            self.toolbar.hide()
        elif step:
            # взяли нумерованный шаг — тащим его; слой собирается без него
            self._mode, self._drag_step = "dragging", step
            self._drag_from = QPointF(step.pos)
            self._drag_offset = step.pos - QPointF(e.position())
            self._invalidate_layer(QRectF(self._shape_rect(step)))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._sel is not None and self._tool != Tool.SELECT:
            # рисовать можно и за пределами выделения — оно расширится до фигуры
            self._start_drawing(QPointF(e.position()))
        elif self._sel is not None and self._sel.contains(pos):
            self._mode, self._sel_origin = "moving", QRect(self._sel)
            self.toolbar.hide()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._sel is None or (self._tool == Tool.SELECT and not self._history):
            # Новое выделение (если на старом ещё ничего не нарисовано)
            self._mode = "selecting"
            self._sel = QRect(pos, QSize(0, 0))
            self.toolbar.hide()
            self.selection_started.emit(self)
        self.update()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pos = e.position().toPoint()
        old_mouse, self._mouse = self._mouse, pos
        shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        bounds = self.rect()

        if self._picking:
            self.update()
            return
        old_sel = QRect(self._sel) if self._sel is not None else None
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
            before = self._current.bounds()
            self._continue_drawing(QPointF(e.position()), shift)
            self._update_shape_area(before)
            return
        elif self._mode == "dragging" and self._drag_step:
            before = self._drag_step.bounds()
            c = QPointF(e.position()) + self._drag_offset
            s = self._sel
            # центр шага остаётся внутри выделения, иначе номер пропадёт из файла
            self._drag_step.pos = QPointF(min(max(c.x(), s.left()), s.right()),
                                          min(max(c.y(), s.top()), s.bottom()))
            self._update_shape_area(before)
            return
        else:
            self._update_cursor(pos)
            self._update_hover(old_mouse)
            return
        # Перерисовываем только область старого и нового выделения (+ ручки и подпись размера)
        self.update(self._selection_area(old_sel).united(self._selection_area(self._sel)))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        mode, self._mode = self._mode, "idle"
        if mode == "selecting":
            if self._sel.width() < MIN_SELECTION or self._sel.height() < MIN_SELECTION:
                # Клик без протяжки (или случайное «дрожание» мыши) ничего не выделяет —
                # раньше он выделял весь экран, и при быстрых кликах панель «уезжала» в угол
                self._sel = None
                self.update()        # направляющие снова видны целиком
                return
            self._place_toolbar()
        elif mode in ("moving", "resizing"):
            if self._sel.width() < 3 or self._sel.height() < 3:
                self._sel = QRect(self._sel_origin)
            self._place_toolbar()
        elif mode == "drawing" and self._current:
            shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._continue_drawing(QPointF(e.position()), shift)
            cur, self._current = self._current, None
            if not cur.is_empty():
                self._push_shape(cur)
                self._sync_toolbar()
        elif mode == "dragging" and self._drag_step:
            step, self._drag_step = self._drag_step, None
            area = QRectF(self._shape_rect(step))
            if step.pos != self._drag_from:
                self._history.push_move(step, self._drag_from, step.pos)
                self._sync_toolbar()
            self._invalidate_layer(area)             # шаг возвращается в слой на новом месте
        self._update_cursor(e.position().toPoint())
        self.update()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        # Двойной клик внутри уже готового выделения в режиме «Выделение» — скопировать.
        # Во всех остальных случаях (например, два резких клика по пустому месту) второй
        # клик — это обычное нажатие: Qt присылает его как DoubleClick вместо Press.
        pos = e.position().toPoint()
        if (e.button() == Qt.MouseButton.LeftButton and self._tool == Tool.SELECT and self._sel
                and self._sel.contains(pos) and self._hit_handle(pos) is None and not self._picking):
            self._copy()
            return
        self.mousePressEvent(e)

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
        old, self._mouse = self._mouse, e.position().toPoint()
        self._update_hover(old)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        # Мышь ушла на другой монитор — направляющие здесь не должны «зависать»
        if self._mode == "idle":
            old, self._mouse = self._mouse, QPoint(-100, -100)
            self._update_hover(old)
        super().leaveEvent(e)

    def _update_cursor(self, pos: QPoint) -> None:
        handle = self._hit_handle(pos)
        if handle:
            self.setCursor(_HANDLE_CURSORS[handle])
        elif self._step_at(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif self._sel is not None and self._sel.contains(pos):
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

    # ------------------------------------------------------ частичная перерисовка
    def _selection_area(self, r: QRect | None) -> QRect:
        if r is None:
            return QRect()
        # ручки, рамка и «таблетка» с размером над левым верхним углом
        return r.adjusted(-HANDLE_HIT - 2, -34, 160, HANDLE_HIT + 2)

    def _update_shape_area(self, before: QRectF) -> None:
        # Во время рисования перерисовываем всё выделение целиком (фигуры живут только
        # в нём). Раньше перерисовывался лишь «хвост» штриха или рамка фигуры — это быстрее,
        # но на некоторых экранах (дробный масштаб Windows, драйверы) по краям таких
        # кусочков оставалась «рябь», пропадавшая только после отпускания кнопки.
        # Благодаря кэшу готовых фигур полная перерисовка выделения всё равно дешёвая.
        # Фигура, вышедшая за выделение, перерисовывается с запасом вокруг себя.
        area = self._selection_area(self._sel)
        shape = self._current or self._drag_step
        now = shape.bounds() if shape else QRectF()
        for r in (before, now):
            if not r.isEmpty() and not QRectF(area).contains(r):
                area = area.united(r.toAlignedRect().adjusted(-GAP, -GAP, GAP, GAP))
        self.update(area)

    def _update_hover(self, old: QPoint) -> None:
        """Простое движение мыши. Без выделения — двигаются тонкие направляющие,
        иначе перерисовывать нечего (кроме подсказки толщины)."""
        if self._sel is None:
            w, h = self.width(), self.height()
            k = GUIDE_PAD
            for pt in (old, self._mouse):
                self.update(QRect(0, pt.y() - k, w, 2 * k + 1))
                self.update(QRect(pt.x() - k, 0, 2 * k + 1, h))
        elif self._width_hint:
            r = self._width + 90
            for pt in (old, self._mouse):
                self.update(QRect(pt.x() - r, pt.y() - r, 2 * r, 2 * r))

    def _invalidate_layer(self, area: QRectF | None = None) -> None:
        """Слой пересоберётся при следующей отрисовке: целиком или только в области area
        (логические координаты) — после Ctrl+Z или переноса шага меняется лишь маленький кусок."""
        if area is None or not self._layer_valid:
            self._layer_valid = False
            self._layer_pending = None
        else:
            self._layer_pending = area if self._layer_pending is None else self._layer_pending.united(area)

    def _ensure_layer(self) -> QPixmap:
        if self._layer is None:
            dpr = self._shot.dpr
            self._layer = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
            self._layer.setDevicePixelRatio(dpr)
            self._layer.fill(Qt.GlobalColor.transparent)
            self._layer_dirty = QRect()
            self._layer_valid = False
        if not self._layer_valid:
            p = QPainter(self._layer)
            if not self._layer_dirty.isEmpty():
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                p.fillRect(self._layer_dirty, Qt.GlobalColor.transparent)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            dirty = QRect()
            for s in self._history.shapes:
                if s is not self._drag_step:
                    s.paint(p)
                    dirty = dirty.united(self._shape_rect(s))
            p.end()
            self._layer_dirty = dirty
            self._layer_valid = True
            self._layer_pending = None
        elif self._layer_pending is not None:
            self._rebuild_layer_area(self._layer_pending)
            self._layer_pending = None
        return self._layer

    def _rebuild_layer_area(self, area: QRectF) -> None:
        # Стираем и обрезаем по целым физическим пикселям — иначе при дробном масштабе
        # на краю области остался бы полупрозрачный «шов».
        dpr = self._shot.dpr
        dev = QRectF(area.x() * dpr, area.y() * dpr, area.width() * dpr, area.height() * dpr)
        dev = dev.toAlignedRect().adjusted(-1, -1, 1, 1).intersected(self._layer.rect())
        if dev.isEmpty():
            return
        p = QPainter(self._layer)
        p.setWorldTransform(QTransform.fromScale(1 / dpr, 1 / dpr))   # → физические пиксели
        p.setClipRect(dev)                     # обрезка запоминается в физических пикселях
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(dev, Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setWorldTransform(QTransform())      # обратно в логические координаты
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        logical = QRectF(dev.x() / dpr, dev.y() / dpr, dev.width() / dpr, dev.height() / dpr)
        for s in self._history.shapes:
            if s is not self._drag_step and QRectF(self._shape_rect(s)).intersects(logical):
                s.paint(p)
        p.end()
        self._layer_dirty = self._layer_dirty.united(logical.toAlignedRect())

    @staticmethod
    def _shape_rect(shape: Shape) -> QRect:
        # bounds() уже с запасом на толщину; ещё 2 px — на сглаживание при дробном масштабе
        return shape.bounds().toAlignedRect().adjusted(-2, -2, 2, 2)

    def _layer_add(self, shape: Shape) -> None:
        """Дорисовать одну новую фигуру в готовый слой (без полной перерисовки)."""
        if not self._layer_valid:
            return  # слой соберётся целиком при следующей отрисовке
        p = QPainter(self._layer)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        shape.paint(p)
        p.end()
        self._layer_dirty = self._layer_dirty.united(self._shape_rect(shape))

    # --------------------------------------------------------------- drawing
    def _start_drawing(self, pos: QPointF) -> None:
        c, w = QColor(self._color), self._width
        if self._tool == Tool.TEXT:
            self._editing = TextShape(c, w, pos=pos - QPointF(0, font_px_for_width(w) * 0.6))
            self._caret_on = True
            self._caret_timer.start()
            return
        self._mode = "drawing"
        self.update(self._selection_area(self._sel))   # ручки выделения прячутся на время рисования
        if self._tool == Tool.PEN:
            self._current = PenStroke(c, w, points=[pos])
        elif self._tool == Tool.MARKER:
            self._current = MarkerStroke(c, marker_width(w), points=[pos])
        elif self._tool == Tool.PIXELATE:
            self._current = PixelateShape(c, w, start=pos, end=pos, source=self._source_image(), dpr=self._shot.dpr)
        elif self._tool == Tool.STEP:
            # номер = количество шагов на снимке + 1 (после Ctrl+Z нумерация продолжается верно)
            number = sum(isinstance(s, StepShape) for s in self._history.shapes) + 1
            self._current = StepShape(c, w, pos=pos, number=number)
        else:
            cls = {Tool.ARROW: ArrowShape, Tool.LINE: LineShape, Tool.RECT: RectShape, Tool.ELLIPSE: EllipseShape}[self._tool]
            self._current = cls(c, w, start=pos, end=pos)

    def _continue_drawing(self, pos: QPointF, shift: bool) -> None:
        cur = self._current
        if isinstance(cur, MarkerStroke) and shift:
            cur.points = [cur.points[0], pos]            # Shift: ровная линия маркером
        elif isinstance(cur, PenStroke):
            if QLineF(cur.points[-1], pos).length() >= 1.0:
                cur.points.append(pos)
        elif isinstance(cur, StepShape):
            cur.pos = pos                                # номер можно перетащить, пока кнопка зажата
        elif isinstance(cur, TwoPointShape):
            if shift and isinstance(cur, (ArrowShape, LineShape)):
                # Shift: стрелка и линия с шагом 45°
                line = QLineF(cur.start, pos)
                line.setAngle(round(line.angle() / 45) * 45)
                pos = line.p2()
            elif shift:
                pos = self._constrain_square(cur.start, pos)  # квадрат / круг
            cur.end = pos

    def _commit_text(self) -> None:
        if not self._editing:
            return
        ed, self._editing = self._editing, None
        if not ed.is_empty():
            self._push_shape(ed)
        self._caret_timer.stop()
        self._sync_toolbar()
        self.update()

    def _blink(self) -> None:
        self._caret_on = not self._caret_on
        if self._editing:
            self.update(self._editing.bounds().toAlignedRect())

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

        if self._picking:
            if e.key() == Qt.Key.Key_Escape:
                self._stop_picking()
                self._place_popup()
            return
        if e.key() == Qt.Key.Key_Escape:
            if self.popup.isVisible():
                self.popup.hide()
                return
            self.cancelled.emit()
        elif ctrl and _is_key(e, Qt.Key.Key_Z):
            self.redo() if shift else self.undo()
        elif ctrl and _is_key(e, Qt.Key.Key_Y):
            self.redo()
        elif ctrl and _is_key(e, Qt.Key.Key_C) or e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._copy()
        elif ctrl and _is_key(e, Qt.Key.Key_S):
            self._save()
        elif ctrl and _is_key(e, Qt.Key.Key_A):
            self.select_all()
        elif ctrl and _is_key(e, Qt.Key.Key_T):
            self._pin()
        elif self._sel is not None and not ctrl and _is_key(e, Qt.Key.Key_I):
            self.start_picking()
        elif self._sel is not None and not ctrl:
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
    def paintEvent(self, event) -> None:
        # Qt уже ограничил отрисовку изменённой областью (event.region), выровненной по
        # физическим пикселям. Фон и слой фигур рисуем ЦЕЛИКОМ от (0,0) и даём обрезке
        # сделать своё: так каждый пиксель области перезаписывается полностью.
        # Раньше рисовался только кусок с дробными координатами источника — при масштабе
        # экрана 125% пиксели на границах куска накладывались на старые, и во время
        # рисования появлялась «рябь», исчезавшая лишь после полной перерисовки.
        exposed = event.rect()
        p = QPainter(self)
        p.setClipRegion(event.region())
        p.drawPixmap(0, 0, self._shot.pixmap)

        # Затемнение вокруг выделения (с анимацией появления): 4 прямоугольника
        # вместо вычитания контуров — в разы быстрее на больших экранах
        dim = QColor(0, 0, 0, int(DIM_ALPHA * self._dim))
        w, h = self.width(), self.height()
        s = self._sel
        if s and not s.isEmpty():
            for r in (QRect(0, 0, w, s.top()), QRect(0, s.bottom() + 1, w, h - s.bottom() - 1),
                      QRect(0, s.top(), s.left(), s.height()),
                      QRect(s.right() + 1, s.top(), w - s.right() - 1, s.height())):
                if r.intersects(exposed):
                    p.fillRect(r, dim)
        else:
            p.fillRect(self.rect(), dim)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)

        if self._sel is None:
            self._paint_guides(p)
            self._paint_hint(p)
            return

        # Фигуры обрезаются по границе выделения — ровно так, как попадут в файл
        p.save()
        p.setClipRect(self._sel, Qt.ClipOperation.IntersectClip)
        if self._history.shapes and self._sel.intersects(exposed):
            p.drawPixmap(0, 0, self._ensure_layer())
        p.restore()
        # Рисуемая сейчас фигура видна и за выделением: после отпускания оно расширится
        if self._current:
            self._current.paint(p)
        if self._drag_step:
            self._drag_step.paint(p)
        if self._editing:
            self._paint_text_editor(p)

        self._paint_frame(p)
        self._paint_size_label(p)
        if self._width_hint:
            self._paint_width_hint(p)
        if self._picking:
            self._paint_loupe(p)

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
        f = self._fonts.small_medium
        w = self._fonts.small_medium_metrics.horizontalAdvance(text) + 16
        y = self._sel.top() - 26 if self._sel.top() >= 30 else self._sel.top() + 6
        x = self._sel.left() if self._sel.top() >= 30 else self._sel.left() + 6
        self._pill(p, QRectF(x, y, w, 20), text, f)

    def _paint_hint(self, p: QPainter) -> None:
        text = "Выделите область  ·  Ctrl+A — весь экран  ·  Esc — отмена"
        f = self._fonts.hint
        w = self._fonts.hint_metrics.horizontalAdvance(text) + 28
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
        box = ed.bounds_text().adjusted(-4, -2, 6, 2)
        pen = QPen(self._t.q("accent"), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, 3, 3)
        if self._caret_on:
            p.setPen(QPen(ed.color, 1.5))
            p.drawLine(ed.caret_line())

    def _paint_loupe(self, p: QPainter) -> None:
        """Лупа пипетки: 15×15 пикселей снимка под курсором, увеличенные в 8 раз."""
        cells, zoom = 15, 8
        size = cells * zoom
        m = self._mouse
        dpr = self._shot.dpr
        cx, cy = int(m.x() * dpr), int(m.y() * dpr)
        src = self._shot_image.copy(cx - cells // 2, cy - cells // 2, cells, cells)
        # Лупа справа-снизу от курсора, у края экрана — с другой стороны
        x = m.x() + 24 if m.x() + 24 + size < self.width() else m.x() - 24 - size
        y = m.y() + 24 if m.y() + 24 + size + 30 < self.height() else m.y() - 24 - size - 30
        box = QRectF(x, y, size, size)
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(box, 12, 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(box.adjusted(-3, -2, 3, 5), 14, 14)
        p.setClipPath(clip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(box, src)
        # центральный пиксель
        p.setClipping(False)
        mid = QRectF(x + (cells // 2) * zoom, y + (cells // 2) * zoom, zoom, zoom)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.drawRect(mid.adjusted(-1, -1, 1, 1))
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.drawRect(mid)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawRoundedRect(box, 12, 12)
        p.restore()
        color = self._color_at(m)
        f = QFont()
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.Medium)
        pill = QRectF(x, y + size + 8, size, 24)
        self._pill(p, pill, "      " + color.name().upper(), f)
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.setBrush(color)
        p.drawEllipse(QPointF(pill.left() + 18, pill.center().y()), 6, 6)

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
