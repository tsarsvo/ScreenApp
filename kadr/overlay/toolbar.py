"""Плавающая панель инструментов и всплывающая панель «цвет + толщина».

Обе панели — дочерние виджеты оверлея (а не отдельные окна), поэтому не
воруют фокус и не прячутся за полноэкранным окном.
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QScrollArea, QSlider, QToolButton, QVBoxLayout, QWidget)

from .. import icons
from ..config import DEFAULT_PALETTE
from ..theme import Tokens
from ..ui.color_picker import ColorField, HueBar
from . import emoji_data
from .emoji_data import CATEGORY_TITLES
from .shapes import EMOJI_FONTS, Tool

SHADOW = 10          # поле под мягкую тень вокруг панели
RADIUS = 12

PALETTE = DEFAULT_PALETTE


class Panel(QWidget):
    """Скруглённая «карточка» с мягкой тенью и анимацией появления."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._t: Tokens | None = None
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(1.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(180)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Прозрачное поле под тень заходит на ручки выделения. Без слежения за мышью
        # движение над ним до оверлея не доходило: курсор не менялся на «изменить размер»,
        # хотя нажатие (оно передаётся родителю) всё равно тянуло ручку.
        self.setMouseTracking(True)

    def _body(self) -> QRectF:
        return QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)

    def mouseMoveEvent(self, e) -> None:
        if self._body().contains(e.position()):
            self.setCursor(Qt.CursorShape.ArrowCursor)
            e.accept()
        else:
            self.unsetCursor()     # курсор оверлея (ручка, прицел…)
            e.ignore()             # → событие получит оверлей

    def apply_theme(self, t: Tokens) -> None:
        self._t = t
        self.update()

    def appear_at(self, pos: QPoint, from_offset: QPoint | None = None) -> None:
        """Плавно показать панель в точке pos (с небольшим «выездом»)."""
        if from_offset is None:
            from_offset = QPoint(0, 6)
        was_visible = self.isVisible()
        self.show()
        self.raise_()
        if was_visible:
            self.move(pos)
            return
        self._slide.stop()
        self._slide.setStartValue(pos + from_offset)
        self._slide.setEndValue(pos)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self.move(pos + from_offset)
        self._slide.start()
        self._anim.start()

    def move_now(self, pos: QPoint) -> None:
        """Переставить без анимации (останавливая незаконченную анимацию появления)."""
        self._slide.stop()
        self._anim.stop()
        self._fx.setOpacity(1.0)
        self.move(pos)

    def paintEvent(self, _event) -> None:
        if not self._t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(self.rect()).adjusted(SHADOW, SHADOW, -SHADOW, -SHADOW)
        # Мягкая тень: несколько полупрозрачных слоёв со смещением вниз
        for i in range(SHADOW, 0, -2):
            alpha = int(4 + (SHADOW - i) * (4 if self._t.dark else 2.2))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(body.adjusted(-i / 2, -i / 2 + 2, i / 2, i / 2 + 2), RADIUS + i / 2, RADIUS + i / 2)
        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        p.setPen(self._t.q("border"))
        p.setBrush(self._t.q("surface"))
        p.drawPath(path)


class IconButton(QToolButton):
    def __init__(self, icon_name: str, tip: str, parent=None, checkable: bool = False) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self.setToolTip(tip)
        self.setCheckable(checkable)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # фокус клавиатуры остаётся у оверлея

    def apply_theme(self, t: Tokens) -> None:
        ic = QIcon()
        ic.addPixmap(icons.icon(self.icon_name, t.text).pixmap(20, 20), QIcon.Mode.Normal, QIcon.State.Off)
        ic.addPixmap(icons.icon(self.icon_name, t.accent).pixmap(20, 20), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(icons.icon(self.icon_name, t.muted).pixmap(20, 20), QIcon.Mode.Disabled, QIcon.State.Off)
        self.setIcon(ic)


class PrimaryButton(QToolButton):
    """Главное действие панели — «Копировать»: значок на заливке цветом акцента, чтобы не искать глазами."""

    def __init__(self, icon_name: str, tip: str, parent=None) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self.setToolTip(tip)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def apply_theme(self, t: Tokens) -> None:
        self.setIcon(icons.icon(self.icon_name, t.accent_text))
        self.setStyleSheet(f"""
            QToolButton {{ background: {t.accent}; border: none; border-radius: 8px; }}
            QToolButton:hover {{ background: {QColor(t.accent).lighter(110).name()}; }}
            QToolButton:pressed {{ background: {QColor(t.accent).darker(110).name()}; }}
        """)


class StyleButton(QAbstractButton):
    """Кнопка «цвет/толщина»: кружок текущего цвета, размер кружка ~ толщине."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Цвет и толщина  (Ctrl + колесо — толщина)")
        self.color = QColor(PALETTE[0])
        self.width_ = 4
        self._t: Tokens | None = None

    def set_style(self, color: QColor, width: int) -> None:
        self.color, self.width_ = QColor(color), width
        self.update()

    def apply_theme(self, t: Tokens) -> None:
        self._t = t
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._t and (self.underMouse() or self.isDown()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._t.q("hover"))
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        d = 8 + min(self.width_, 20) * 0.6          # визуальный намёк на толщину
        r = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        p.setPen(QColor(0, 0, 0, 70) if not (self._t and self._t.dark) else QColor(255, 255, 255, 90))
        p.setBrush(self.color)
        p.drawEllipse(r)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class Toolbar(Panel):
    tool_selected = Signal(object)  # Tool
    undo = Signal()
    redo = Signal()
    copy = Signal()
    save = Signal()
    pin = Signal()
    cancel = Signal()  # не `close` — иначе затеним QWidget.close()
    style_clicked = Signal()

    # Инструменты по смыслу: выбрать | рисовать | подписать | скрыть
    TOOL_GROUPS = [
        [(Tool.SELECT, "cursor", "Выделение и перемещение  (V)")],
        [(Tool.PEN, "pen", "Кисть  (P)"),
         (Tool.MARKER, "highlighter", "Маркер  (M) · Shift — ровная линия"),
         (Tool.LINE, "line", "Линия  (L) · Shift — под 45°"),
         (Tool.ARROW, "arrow", "Стрелка  (A)"),
         (Tool.RECT, "rect", "Прямоугольник  (R)"),
         (Tool.ELLIPSE, "ellipse", "Овал  (E)")],
        [(Tool.TEXT, "text", "Текст  (T)"),
         (Tool.EMOJI, "emoji", "Эмодзи  (J)"),
         (Tool.STEP, "step", "Нумерованные шаги  (N) · можно ставить и за рамкой")],
        [(Tool.PIXELATE, "pixelate", "Скрыть: пикселизация  (B)")],
    ]
    TOOLS = [t for group in TOOL_GROUPS for t in group]
    # Фигуры прячутся за одной кнопкой: панель короче, а выбрать фигуру — один клик на кнопку и один на фигуру
    SHAPE_TOOLS = (Tool.MARKER, Tool.LINE, Tool.ARROW, Tool.RECT, Tool.ELLIPSE)
    shapes_toggled = Signal()   # панель стала длиннее или короче — оверлей переставит её

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(SHADOW + 5, SHADOW + 5, SHADOW + 5, SHADOW + 5)
        row.setSpacing(2)

        self._buttons: list = []
        self._tool_buttons: dict[Tool, IconButton] = {}
        self._icon_of: dict[Tool, str] = {}
        self._t: Tokens | None = None
        group = QButtonGroup(self)
        group.setExclusive(True)

        self._shape_box = QWidget(self)
        shapes = QHBoxLayout(self._shape_box)
        shapes.setContentsMargins(0, 0, 0, 0)
        shapes.setSpacing(2)
        self._shape_box.hide()
        self._shape_toggle = IconButton("rect", "Фигуры: маркер, линия, стрелка, прямоугольник, овал  (клик — раскрыть)",
                                        self, checkable=True)
        self._shape_toggle.clicked.connect(self._on_shape_toggle)
        self._shape_toggle.hide()
        self._shapes_open = False
        self._current = Tool.SELECT

        for i, tools in enumerate(self.TOOL_GROUPS):
            if i:
                row.addWidget(self._sep())
            for tool, name, tip in tools:
                b = IconButton(name, tip, self, checkable=True)
                b.clicked.connect(lambda _=False, t=tool: self.tool_selected.emit(t))
                group.addButton(b)
                self._tool_buttons[tool] = b
                self._icon_of[tool] = name
                if tool in self.SHAPE_TOOLS:
                    if shapes.count() == 0:
                        row.addWidget(self._shape_toggle)
                        self._shape_toggle.show()
                        row.addWidget(self._shape_box)
                    shapes.addWidget(b)
                else:
                    row.addWidget(b)

        row.addWidget(self._sep())
        self.style_btn = StyleButton(self)
        self.style_btn.clicked.connect(self.style_clicked)
        row.addWidget(self.style_btn)
        row.addWidget(self._sep())

        self.undo_btn = self._action("undo", "Назад  (Ctrl+Z)", self.undo, row)
        self.redo_btn = self._action("redo", "Вперёд  (Ctrl+Y)", self.redo, row)
        row.addWidget(self._sep())
        self._action("pin", "Закрепить поверх окон  (Ctrl+T)", self.pin, row)
        self._action("save", "Сохранить в папку  (Ctrl+S)", self.save, row)
        self.copy_btn = PrimaryButton("copy", "Скопировать в буфер  (Ctrl+C / Enter)", self)
        self.copy_btn.clicked.connect(self.copy)
        row.addSpacing(3)
        row.addWidget(self.copy_btn)
        row.addSpacing(3)
        self._action("close", "Закрыть  (Esc)", self.cancel, row)

        self._buttons += list(self._tool_buttons.values()) + [self._shape_toggle]
        self._sync_shape_toggle(Tool.RECT)
        self.adjustSize()

    def _on_shape_toggle(self) -> None:
        self._set_shapes_open(not self._shapes_open)
        self._shape_toggle.setChecked(self._current in self.SHAPE_TOOLS)

    def _set_shapes_open(self, on: bool) -> None:
        if on == self._shapes_open:
            return
        self._shapes_open = on
        self._shape_box.setVisible(on)
        self.adjustSize()
        self.shapes_toggled.emit()

    def _sync_shape_toggle(self, tool: Tool) -> None:
        """Кнопка фигур показывает последнюю выбранную фигуру (по умолчанию прямоугольник)."""
        if tool not in self.SHAPE_TOOLS:
            return
        self._shape_toggle.icon_name = self._icon_of[tool]
        if self._t:
            self._shape_toggle.apply_theme(self._t)

    def _action(self, name, tip, signal, row) -> IconButton:
        b = IconButton(name, tip, self)
        b.clicked.connect(signal)
        row.addWidget(b)
        self._buttons.append(b)
        return b

    def _sep(self) -> QWidget:
        s = QWidget(self)
        s.setFixedSize(9, 20)
        s.setObjectName("Sep")
        self._seps = getattr(self, "_seps", []) + [s]
        return s

    def apply_theme(self, t: Tokens) -> None:
        super().apply_theme(t)
        self._t = t
        accent = QColor(t.accent)
        self.setStyleSheet(f"""
            QToolButton {{ border: none; border-radius: 8px; background: transparent; }}
            QToolButton:hover {{ background: {t.hover}; }}
            QToolButton:checked {{ background: rgba({accent.red()},{accent.green()},{accent.blue()},0.16); }}
            QWidget#Sep {{ background: transparent; border-left: 1px solid {t.border}; margin-left: 4px; }}
        """)
        for b in self._buttons:
            b.apply_theme(t)
        self.copy_btn.apply_theme(t)
        self.style_btn.apply_theme(t)

    def set_tool(self, tool: Tool) -> None:
        self._tool_buttons[tool].setChecked(True)
        self._current = tool
        self._shape_toggle.setChecked(tool in self.SHAPE_TOOLS)
        if tool in self.SHAPE_TOOLS:
            self._sync_shape_toggle(tool)
            self._set_shapes_open(False)            # выбрали фигуру — список сворачиваем

    def set_history_state(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)

    def set_style(self, color: QColor, width: int) -> None:
        self.style_btn.set_style(color, width)


class Swatch(QAbstractButton):
    """Кружок палитры. ЛКМ — выбрать цвет, ПКМ — изменить сам кружок."""

    edit_requested = Signal()

    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self.editing = False
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Клик — выбрать · правый клик — изменить цвет")
        self.ring = QColor("#3F6BFF")
        self.outline = QColor(0, 0, 0, 50)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.RightButton:
            self.edit_requested.emit()
            return
        super().mousePressEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isChecked() or self.editing:
            style = Qt.PenStyle.DashLine if self.editing else Qt.PenStyle.SolidLine
            p.setPen(QPen(self.ring, 1.6, style))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(1.5, 1.5, 23, 23))
        p.setPen(self.outline)
        p.setBrush(self.color)
        p.drawEllipse(QRectF(5, 5, 16, 16))


HINT_DEFAULT = "Правый клик по кружку — изменить цвет палитры"
HINT_EDIT = "Меняем цвет кружка: выберите цвет ниже, пипеткой или в HEX"


class StylePopup(Panel):
    """Цвет (палитра, любой цвет, HEX, пипетка) и толщина."""

    color_changed = Signal(QColor)
    width_changed = Signal(int)
    palette_changed = Signal(list)      # новая палитра — сохраняется в настройках
    pick_requested = Signal()           # пипетка: оверлей переходит в режим выбора цвета с экрана
    resized = Signal()                  # раскрыли/свернули выбор цвета — оверлей переставит панель

    def __init__(self, parent: QWidget, palette: list[str] | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(PALETTE[0])
        self._edit_index: int | None = None
        self._hold_edit = False
        col = QVBoxLayout(self)
        col.setContentsMargins(SHADOW + 12, SHADOW + 10, SHADOW + 12, SHADOW + 12)
        col.setSpacing(10)

        grid = QGridLayout()
        grid.setSpacing(2)
        self._swatches: list[Swatch] = []
        group = QButtonGroup(self)
        colors = list(palette or PALETTE) + PALETTE[len(palette or []):]
        for i, c in enumerate(colors[:len(PALETTE)]):
            sw = Swatch(c, self)
            sw.clicked.connect(lambda _=False, k=i: self._choose_swatch(k))
            sw.edit_requested.connect(lambda k=i: self._start_edit(k))
            group.addButton(sw)
            grid.addWidget(sw, i // 5, i % 5)
            self._swatches.append(sw)
        col.addLayout(grid)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.pipette = IconButton("pipette", "Пипетка — взять цвет со скриншота  (I)", self)
        self.pipette.clicked.connect(self.pick_requested)
        self.more = IconButton("palette", "Любой цвет", self, checkable=True)
        self.more.toggled.connect(self._show_picker)
        self.hex = QLineEdit(self)
        self.hex.setMaxLength(7)
        self.hex.setFixedWidth(84)
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.editingFinished.connect(self._on_hex)
        tools.addWidget(self.pipette)
        tools.addWidget(self.more)
        tools.addStretch(1)
        tools.addWidget(self.hex)
        col.addLayout(tools)

        self.picker = QWidget(self)
        pk = QVBoxLayout(self.picker)
        pk.setContentsMargins(0, 0, 0, 0)
        pk.setSpacing(8)
        self.field = ColorField(self.picker)
        self.hue = HueBar(self.picker)
        self.field.changed.connect(lambda c: self._apply(c, from_picker=True))
        self.hue.changed.connect(self.field.set_hue)
        pk.addWidget(self.field)
        pk.addWidget(self.hue)
        self.picker.hide()
        col.addWidget(self.picker)

        self.hint = QLabel(HINT_DEFAULT, self)
        self.hint.setWordWrap(True)
        self.hint.setObjectName("Hint")
        col.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(1, 40)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.valueChanged.connect(self._on_slider)
        self.value = QLabel("4", self)
        self.value.setFixedWidth(22)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        col.addLayout(row)
        self.setFixedWidth(self.field.width() + 2 * (SHADOW + 12))
        self.adjustSize()
        self.hide()

    # --- палитра -----------------------------------------------------------
    def palette(self) -> list[str]:
        return [sw.color.name().upper() for sw in self._swatches]

    def _choose_swatch(self, i: int) -> None:
        self._stop_edit()
        self._apply(QColor(self._swatches[i].color))

    def _start_edit(self, i: int) -> None:
        """ПКМ по кружку: следующий выбранный цвет (поле, HEX, пипетка) заменит его."""
        self._stop_edit()
        self._edit_index = i
        self._swatches[i].editing = True
        self._swatches[i].update()
        self.hint.setText(HINT_EDIT)
        self.more.setChecked(True)
        self._apply(QColor(self._swatches[i].color))

    def _stop_edit(self) -> None:
        if self._edit_index is not None:
            self._swatches[self._edit_index].editing = False
            self._swatches[self._edit_index].update()
        self._edit_index = None
        self.hint.setText(HINT_DEFAULT)

    # --- выбор цвета -------------------------------------------------------
    def apply_color(self, c: QColor) -> None:
        """Цвет извне — например, с пипетки."""
        self._apply(QColor(c))

    def _apply(self, c: QColor, from_picker: bool = False) -> None:
        if not c.isValid():
            return
        if self._edit_index is not None:
            sw = self._swatches[self._edit_index]
            sw.color = QColor(c)
            sw.update()
            self.palette_changed.emit(self.palette())
        self._set_color_ui(c, update_field=not from_picker)
        self.color_changed.emit(QColor(c))

    def _set_color_ui(self, c: QColor, update_field: bool = True) -> None:
        self._color = QColor(c)
        if not self.hex.hasFocus():
            self.hex.setText(c.name().upper())
        if update_field:
            self.field.set_color(c)
            self.hue.set_hue(c.hsvHueF())
        for sw in self._swatches:
            sw.setChecked(sw.color.rgb() == c.rgb())

    def _on_hex(self) -> None:
        text = self.hex.text().strip()
        if text and not text.startswith("#"):
            text = "#" + text
        c = QColor(text)
        if c.isValid() and len(text) in (4, 7):
            self._apply(c)
        else:
            self.hex.setText(self._color.name().upper())
        if self.parentWidget():
            self.parentWidget().setFocus()  # горячие клавиши снова у оверлея

    def _show_picker(self, on: bool) -> None:
        self.picker.setVisible(on)
        self.layout().activate()   # пересчитать высоту сразу, до перестановки панели
        self.adjustSize()
        self.resized.emit()

    def hide_for_picking(self) -> None:
        """Прячемся на время пипетки, но помним, какой кружок палитры редактируется."""
        self._hold_edit = True
        self.hide()

    def hideEvent(self, e) -> None:
        if not self._hold_edit:
            self._stop_edit()
        self._hold_edit = False
        super().hideEvent(e)

    # --- толщина -----------------------------------------------------------
    def _on_slider(self, v: int) -> None:
        self.value.setText(str(v))
        self.width_changed.emit(v)

    def set_style(self, color: QColor, width: int) -> None:
        self._set_color_ui(QColor(color))
        self.slider.blockSignals(True)
        self.slider.setValue(width)
        self.slider.blockSignals(False)
        self.value.setText(str(width))

    def apply_theme(self, t: Tokens) -> None:
        super().apply_theme(t)
        for sw in self._swatches:
            sw.ring = QColor(t.accent)
            # тёмный кружок на тёмной панели не должен теряться
            sw.outline = QColor(255, 255, 255, 90) if t.dark else QColor(0, 0, 0, 50)
        self.pipette.apply_theme(t)
        self.more.apply_theme(t)
        accent = QColor(t.accent)
        self.setStyleSheet(f"""
            QLabel {{ color: {t.muted}; font-size: 12px; background: transparent; }}
            QLabel#Hint {{ font-size: 11px; }}
            QToolButton {{ border: none; border-radius: 8px; background: transparent; }}
            QToolButton:hover {{ background: {t.hover}; }}
            QToolButton:checked {{ background: rgba({accent.red()},{accent.green()},{accent.blue()},0.16); }}
            QLineEdit {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border};
                         border-radius: 7px; padding: 4px 6px; font-family: monospace; font-size: 12px;
                         selection-background-color: {t.accent}; }}
            QLineEdit:focus {{ border-color: {t.accent}; }}
            QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
                                          background: {t.surface}; border: 1px solid {t.border}; }}
        """)


EMOJI_COLS = 8
EMOJI_CELL = 36
EMOJI_RECENT_MAX = 16


class EmojiButton(QToolButton):
    def __init__(self, char: str, parent=None) -> None:
        super().__init__(parent)
        self.char = char
        self.setText(char)
        f = QFont()
        f.setFamilies(EMOJI_FONTS)
        f.setPixelSize(22)
        self.setFont(f)
        self.setFixedSize(EMOJI_CELL, EMOJI_CELL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class EmojiPopup(Panel):
    """Панель выбора эмодзи, как быстрая панель Discord: поиск сверху, «часто используемые»,
    категории (кнопки-вкладки прокручивают список). Поиск — по русским и английским словам."""

    chosen = Signal(str)
    recent_changed = Signal(list)

    def __init__(self, parent: QWidget, recent: list[str] | None = None) -> None:
        super().__init__(parent)
        self._recent: list[str] = list(recent or [])[:EMOJI_RECENT_MAX]
        self._built = False
        self._anchors: dict[str, QWidget] = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(SHADOW + 10, SHADOW + 10, SHADOW + 10, SHADOW + 10)
        col.setSpacing(8)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Поиск: огонь, кот, fire…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.search.installEventFilter(self)
        col.addWidget(self.search)

        self.tabs = QHBoxLayout()
        self.tabs.setSpacing(2)
        col.addLayout(self.tabs)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedSize(EMOJI_COLS * EMOJI_CELL + 14, 6 * EMOJI_CELL)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        col.addWidget(self.scroll)
        # Виджет прокрутки один на всю жизнь: QScrollArea.setWidget удаляет прежний виджет,
        # поэтому список и результаты поиска меняем внутри него (см. _show)
        self._view = QWidget()
        self._view_lay = QVBoxLayout(self._view)
        self._view_lay.setContentsMargins(0, 0, 0, 0)
        self._view_lay.setSpacing(0)
        self.scroll.setWidget(self._view)
        self._browse: QWidget | None = None

        self.status = QLabel("", self)
        self.status.setObjectName("Hint")
        col.addWidget(self.status)
        self.setFixedWidth(self.scroll.width() + 2 * (SHADOW + 10))
        self.adjustSize()
        self.hide()

    # --- содержимое: собирается при первом показе, а не при создании оверлея ------------------
    def _grid(self, chars: list[str]) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)
        # Ячейки держат свой размер и прижаты влево-вверх, иначе лишняя ширина делит сетку по центру
        g.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for i, ch in enumerate(chars):
            b = EmojiButton(ch, w)
            b.clicked.connect(lambda _=False, c=ch: self.choose(c))
            b.setToolTip(self._name(ch))
            g.addWidget(b, i // EMOJI_COLS, i % EMOJI_COLS)
        return w

    @staticmethod
    def _name(ch: str) -> str:
        words = next((kw for c, kw in emoji_data.ALL if c == ch), "")
        return words.split()[0] if words else ""

    def _header(self, text: str) -> QLabel:
        lab = QLabel(text, self)
        lab.setObjectName("Section")
        return lab

    def _build(self) -> None:
        self._built = True
        self._browse = QWidget()
        lay = QVBoxLayout(self._browse)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(2)
        self._recent_box = QVBoxLayout()
        lay.addLayout(self._recent_box)
        self._fill_recent()
        for name, icon, items in emoji_data.CATEGORIES:
            head = self._header(CATEGORY_TITLES[name])
            lay.addWidget(head)
            lay.addWidget(self._grid([e.partition("|")[0] for e in items]))
            self._anchors[name] = head
            tab = QToolButton(self)
            tab.setText(icon)
            tab.setToolTip(CATEGORY_TITLES[name])
            tab.setFixedSize(30, 28)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            f = QFont()
            f.setFamilies(EMOJI_FONTS)
            f.setPixelSize(16)
            tab.setFont(f)
            tab.clicked.connect(lambda _=False, n=name: self._jump(n))
            self.tabs.addWidget(tab)
        self.tabs.addStretch(1)
        lay.addStretch(1)
        self._show(self._browse)

    def _show(self, w: QWidget) -> None:
        """Показать w в прокрутке. Прежние результаты поиска удаляются, список категорий прячется,
        но не удаляется — его потом снова показываем."""
        while self._view_lay.count():
            old = self._view_lay.takeAt(0).widget()
            if old is None:
                continue
            if old is self._browse:
                old.hide()
            else:
                old.deleteLater()
        self._view_lay.addWidget(w)
        self._view_lay.addStretch(1)
        w.show()

    def _fill_recent(self) -> None:
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        chars = self._recent or emoji_data.QUICK
        self._recent_box.addWidget(self._header("Часто используемые" if self._recent else "Популярные"))
        self._recent_box.addWidget(self._grid(chars))

    def _jump(self, name: str) -> None:
        self.search.clear()
        self._show(self._browse)
        self.scroll.verticalScrollBar().setValue(self._anchors[name].y())

    # --- поиск ---------------------------------------------------------------------------------
    def _on_search(self, text: str) -> None:
        if not self._built:
            return
        if not text.strip():
            self._show(self._browse)
            self.status.setText("")
            return
        found = emoji_data.search(text)
        if not found:
            self.status.setText("Ничего не найдено")
            box = QLabel("Попробуйте другое слово", self)
            box.setObjectName("Hint")
            box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._show(box)
            return
        self.status.setText(f"Найдено: {len(found)}")
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.addWidget(self._grid(found))
        lay.addStretch(1)                       # сетка прижата к верху, а не растянута на всю высоту
        self._show(box)

    def eventFilter(self, obj, e) -> bool:
        # Enter в поиске выбирает первый найденный; Esc закрывает панель, а не оверлей
        if obj is self.search and e.type() == e.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                found = emoji_data.search(self.search.text())
                if found:
                    self.choose(found[0])
                return True
            if e.key() == Qt.Key.Key_Escape:
                self.close_popup()
                return True
        return super().eventFilter(obj, e)

    def close_popup(self) -> None:
        self.hide()
        if self.parentWidget():
            self.parentWidget().setFocus()      # горячие клавиши снова у оверлея

    # --- выбор ---------------------------------------------------------------------------------
    def choose(self, char: str) -> None:
        self._recent = [char] + [c for c in self._recent if c != char]
        self._recent = self._recent[:EMOJI_RECENT_MAX]
        self.recent_changed.emit(list(self._recent))
        self.close_popup()
        self.chosen.emit(char)

    def set_recent(self, recent: list[str]) -> None:
        self._recent = list(recent)[:EMOJI_RECENT_MAX]
        if self._built:
            self._fill_recent()

    def open_fresh(self) -> None:
        if not self._built:
            self._build()
        else:
            self._fill_recent()
        self.search.clear()
        self._show(self._browse)
        self.scroll.verticalScrollBar().setValue(0)
        self.status.setText("")
        self.layout().activate()
        self.adjustSize()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.search.setFocus()

    def apply_theme(self, t: Tokens) -> None:
        super().apply_theme(t)
        accent = QColor(t.accent)
        self.setStyleSheet(f"""
            QLabel {{ color: {t.muted}; font-size: 11px; background: transparent; }}
            QLabel#Section {{ font-weight: 600; padding: 6px 2px 2px 2px; }}
            QToolButton {{ border: none; border-radius: 8px; background: transparent; color: {t.text}; }}
            QToolButton:hover {{ background: {t.hover}; }}
            QLineEdit {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border};
                         border-radius: 8px; padding: 6px 8px; font-size: 13px;
                         selection-background-color: {t.accent}; }}
            QLineEdit:focus {{ border-color: rgba({accent.red()},{accent.green()},{accent.blue()},0.8); }}
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
