"""Закреплённый скриншот: небольшое окно поверх всех окон.

Удобно, чтобы держать перед глазами образец, пока работаешь в другой программе.
  • перетаскивание мышью, край или угол — изменить размер (пропорции сохраняются);
  • колесо — масштаб, Ctrl+колесо — прозрачность;
  • двойной клик или Esc — закрыть, правый клик — меню (копировать, сохранить…);
  • крестик в правом верхнем углу (при наведении) — закрыть;
  • карандаш в правом нижнем углу — рисование прямо на снимке (три быстрых цвета),
    рядом — копирование в буфер вместе с нарисованным и лупа (колесо — увеличение).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from . import icons

BORDER = 1
EDGE = 8                 # зона у края, за которую тянут размер
MIN_SCALE, MAX_SCALE = 0.1, 8.0
BTN = 22                 # кнопки панели рисования в углу
BTN_GAP = 3
PANEL_PAD = 4
PANEL_MARGIN = 6
PEN_WIDTH = 3.0          # толщина линии в логических пикселях снимка
QUICK_COLORS = ("#FF3B30", "#FF9500", "#FFCC00")
LOUPE_R = 70             # радиус лупы
LOUPE_ZOOM = 3.0
LOUPE_MIN, LOUPE_MAX = 1.5, 12.0
_TIPS = {"pen": "Рисовать на снимке (ещё раз — выключить) · Ctrl+Z — отменить",
         "copy": "Копировать в буфер обмена (вместе с рисунком)",
         "loupe": "Лупа (ещё раз — выключить) · колесо — увеличение",
         "close": "Закрыть снимок"}

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

    def __init__(self, image: QImage, dpr: float, top_left: QPoint, accent: str = "#3F6BFF",
                 colors: list[str] | tuple = QUICK_COLORS) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Kadr — закреплённый снимок")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setMouseTracking(True)
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._pixmap.setDevicePixelRatio(dpr)
        self._base = QRectF(0, 0, image.width() / dpr, image.height() / dpr).size()
        self._scale = 1.0
        self._accent = QColor(accent)
        self._drag: QPoint | None = None
        self._edge: str | None = None           # какой край тянем
        self._resize_start: tuple[QPoint, QRect, float] | None = None
        # Рисование на снимке. Штрихи хранятся в пикселях самого снимка — при масштабе
        # окна они масштабируются вместе с ним и попадают в копию без потери качества.
        self._dpr = dpr
        self._colors = [QColor(c) for c in list(colors)[:3]] or [QColor(c) for c in QUICK_COLORS]
        self._color = self._colors[0]
        self._drawing = False
        self._hover = False
        self._strokes: list[tuple[QColor, float, list[QPointF]]] = []
        self._stroke: list[QPointF] | None = None
        self._icon_cache: dict[str, QPixmap] = {}
        # Лупа: увеличенный кусок снимка вокруг курсора
        self._loupe = False
        self._loupe_zoom = LOUPE_ZOOM
        self._mouse = QPointF(-1000, -1000)
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
        if self._strokes or self._stroke:
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.translate(BORDER, BORDER)
            p.scale(*self._image_scale())
            self._paint_strokes(p)
            p.restore()
        p.setPen(QPen(self._accent, BORDER))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        if self._loupe and self._hover and not self._control_at(self._mouse):
            self._paint_loupe(p)
        if self._hover or self._drawing:
            self._paint_controls(p)
            self._paint_close(p)

    def _paint_loupe(self, p: QPainter) -> None:
        """Круглая лупа с центром под курсором; штрихи увеличиваются вместе со снимком."""
        m = self._mouse
        if not QRectF(self.rect()).adjusted(BORDER, BORDER, -BORDER, -BORDER).contains(m):
            return
        sx, sy = self._image_scale()
        c = self._to_image(m)
        hw, hh = LOUPE_R / (self._loupe_zoom * sx), LOUPE_R / (self._loupe_zoom * sy)
        src = QRectF(c.x() - hw, c.y() - hh, 2 * hw, 2 * hh)
        lens = QRectF(m.x() - LOUPE_R, m.y() - LOUPE_R, 2 * LOUPE_R, 2 * LOUPE_R)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawEllipse(lens.adjusted(-3, -2, 3, 4))             # мягкая тень
        clip = QPainterPath()
        clip.addEllipse(lens)
        p.setClipPath(clip)
        p.fillRect(lens, QColor(32, 32, 34))                     # за краем снимка
        p.translate(lens.topLeft())
        p.scale(lens.width() / src.width(), lens.height() / src.height())
        p.translate(-src.topLeft())
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)   # видны пиксели
        part = src.intersected(QRectF(self._image.rect()))
        if not part.isEmpty():
            p.drawImage(part, self._image, part)
        if self._strokes or self._stroke:
            self._paint_strokes(p)
        p.restore()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawEllipse(lens)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.drawEllipse(lens.adjusted(-1.5, -1.5, 1.5, 1.5))
        p.restore()

    def set_loupe(self, on: bool) -> None:
        self._loupe = on
        self._update_cursor(self._mouse)
        self.update()
    # ------------------------------------------------------------- рисование
    def _image_scale(self) -> tuple[float, float]:
        return ((self.width() - 2 * BORDER) / self._image.width(),
                (self.height() - 2 * BORDER) / self._image.height())

    def _to_image(self, pos: QPointF) -> QPointF:
        sx, sy = self._image_scale()
        return QPointF((pos.x() - BORDER) / sx, (pos.y() - BORDER) / sy)

    def _paint_strokes(self, p: QPainter) -> None:
        items = list(self._strokes)
        if self._stroke:
            items.append((self._color, PEN_WIDTH * self._dpr, self._stroke))
        for color, width, pts in items:
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(pts[0])
            if len(pts) == 1:
                path.lineTo(pts[0] + QPointF(0.01, 0))    # точка от одного клика
            for pt in pts[1:]:
                path.lineTo(pt)
            p.drawPath(path)

    def rendered_image(self) -> QImage:
        """Снимок вместе с нарисованным — для копирования и сохранения."""
        if not self._strokes:
            return self._image
        img = self._image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_strokes(p)
        p.end()
        return img

    def set_drawing(self, on: bool) -> None:
        self._drawing = on
        self._stroke = None
        self._update_cursor(self._mouse)
        self.update()

    def _update_cursor(self, pos) -> None:
        if self._control_at(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._drawing:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif edge := self._edge_at(pos):
            self.setCursor(_EDGE_CURSORS[edge])
        else:
            self.setCursor(Qt.CursorShape.CrossCursor if self._loupe else Qt.CursorShape.SizeAllCursor)

    def _copy(self) -> None:
        self.copy_requested.emit(self.rendered_image())

    # --------------------------------------------------- панель в углу снимка
    def _controls(self) -> list[tuple[str, QRectF]]:
        """Кнопки справа налево: карандаш, копировать, в режиме рисования — цвета."""
        # раскладка справа налево — цвета в обратном порядке, чтобы слева направо шли как в палитре
        colors = [f"color{i}" for i in reversed(range(len(self._colors)))] if self._drawing else []
        ids = ["pen", "copy", "loupe"] + colors
        x = self.width() - BORDER - PANEL_MARGIN - PANEL_PAD - BTN
        y = self.height() - BORDER - PANEL_MARGIN - PANEL_PAD - BTN
        out = []
        for cid in ids:
            out.append((cid, QRectF(x, y, BTN, BTN)))
            x -= BTN + BTN_GAP
        return out

    def _close_rect(self) -> QRectF:
        """Крестик в правом верхнем углу — закрыть без правого клика."""
        return QRectF(self.width() - BORDER - PANEL_MARGIN - BTN, BORDER + PANEL_MARGIN, BTN, BTN)

    def _control_at(self, pos) -> str | None:
        if not (self._hover or self._drawing):
            return None
        pt = QPointF(pos)
        if self._close_rect().contains(pt):
            return "close"
        return next((cid for cid, r in self._controls() if r.contains(pt)), None)

    def _icon(self, name: str) -> QPixmap:
        if name not in self._icon_cache:
            self._icon_cache[name] = icons.icon(name, "#FFFFFF", 16).pixmap(16, 16)
        return self._icon_cache[name]

    def _paint_controls(self, p: QPainter) -> None:
        ctrls = self._controls()
        panel = QRectF(ctrls[-1][1].topLeft(), ctrls[0][1].bottomRight())
        panel.adjust(-PANEL_PAD, -PANEL_PAD, PANEL_PAD, PANEL_PAD)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.85)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 22, 160))
        p.drawRoundedRect(panel, panel.height() / 2, panel.height() / 2)
        for cid, r in ctrls:
            if cid.startswith("color"):
                c = self._colors[int(cid[5:])]
                p.setPen(QPen(QColor("#FFFFFF"), 1.5) if c == self._color else Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(r.adjusted(4, 4, -4, -4))
                p.setPen(Qt.PenStyle.NoPen)
                continue
            if cid == "pen" and self._drawing or cid == "loupe" and self._loupe:   # включено — подсвеченный кружок
                p.setBrush(self._accent)
                p.drawEllipse(r)
            p.drawPixmap(QPointF(r.center().x() - 8, r.center().y() - 8), self._icon(cid))
        p.restore()

    def _paint_close(self, p: QPainter) -> None:
        r = self._close_rect()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.85)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 22, 160))
        p.drawEllipse(r)
        p.drawPixmap(QPointF(r.center().x() - 8, r.center().y() - 8), self._icon("close"))
        p.restore()

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.ToolTip:
            # подсказки только у кнопок: над самим снимком ничего не всплывает
            cid = self._control_at(e.pos())
            if cid:
                QToolTip.showText(e.globalPos(), _TIPS.get(cid, "Цвет линии"), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

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
        cid = self._control_at(e.position())
        if cid == "pen":
            self.set_drawing(not self._drawing)
            return
        if cid == "copy":
            self._copy()
            return
        if cid == "loupe":
            self.set_loupe(not self._loupe)
            return
        if cid == "close":
            self.close()
            return
        if cid:                                   # один из цветов
            self._color = self._colors[int(cid[5:])]
            self.update()
            return
        if self._drawing:
            self._stroke = [self._to_image(e.position())]
            self.update()
            return
        gp = e.globalPosition().toPoint()
        self._edge = self._edge_at(e.position())
        if self._edge:
            self._resize_start = (gp, self.geometry(), self._scale)
        else:
            self._drag = gp - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        gp = e.globalPosition().toPoint()
        self._mouse = e.position()
        if self._loupe:
            self.update()
        if self._stroke is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self._stroke.append(self._to_image(e.position()))
            self.update()
        elif self._control_at(e.position()) or self._drawing:
            self._update_cursor(e.position())
        elif self._edge and self._resize_start and e.buttons() & Qt.MouseButton.LeftButton:
            self._resize_by_edge(gp)
        elif self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(gp - self._drag)
        else:
            self._update_cursor(e.position())

    def mouseReleaseEvent(self, _e) -> None:
        if self._stroke:
            self._strokes.append((QColor(self._color), PEN_WIDTH * self._dpr, self._stroke))
            self.update()
        self._stroke = None
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

    def mouseDoubleClickEvent(self, e) -> None:
        if self._drawing or self._control_at(e.position()):
            self.mousePressEvent(e)          # при рисовании двойной клик — не закрытие
            return
        self.close()

    def wheelEvent(self, e) -> None:
        dy = e.angleDelta().y()
        if not dy:
            return          # горизонтальная прокрутка тачпада — раньше она уменьшала снимок
        step = 1 if dy > 0 else -1
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.setWindowOpacity(min(1.0, max(0.2, self.windowOpacity() + 0.1 * step)))
        elif self._loupe:
            # с лупой колесо меняет её увеличение, а не размер снимка
            k = 1.25 if step > 0 else 1 / 1.25
            self._loupe_zoom = min(LOUPE_MAX, max(LOUPE_MIN, self._loupe_zoom * k))
            self.update()
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
            # сначала выходим из рисования и лупы, потом закрываем
            if self._drawing:
                self.set_drawing(False)
            elif self._loupe:
                self.set_loupe(False)
            else:
                self.close()
        elif e.key() == Qt.Key.Key_C and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._copy()
        elif e.key() == Qt.Key.Key_Z and e.modifiers() & Qt.KeyboardModifier.ControlModifier and self._strokes:
            self._strokes.pop()
            self.update()

    def contextMenuEvent(self, e) -> None:
        menu = QMenu(self)
        for text, fn in (("Копировать", self._copy),
                         ("Сохранить в папку", lambda: self.save_requested.emit(self.rendered_image())),
                         ("Закончить рисование" if self._drawing else "Рисовать на снимке",
                          lambda: self.set_drawing(not self._drawing)),
                         ("Убрать лупу" if self._loupe else "Лупа", lambda: self.set_loupe(not self._loupe)),
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
