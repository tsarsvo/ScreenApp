"""Картинки для README (docs/*.png) — рисуются настоящими виджетами Kadr, без экрана.

    python scripts/make_screenshots.py

Запускайте после изменений интерфейса, чтобы README показывал актуальную программу.
Экран «снимается» не с рабочего стола: под оверлеем лежит нарисованная сцена, поэтому
картинки одинаковые на любом компьютере и не содержат ничего личного.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Настройки — во временной папке: картинки не зависят от настроек разработчика
_CFG = tempfile.mkdtemp(prefix="kadr-shots-")
os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"] = _CFG

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QLinearGradient, QMouseEvent, QPainter,  # noqa: E402
                           QPixmap)
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from kadr.capture import ScreenShot  # noqa: E402
from kadr.overlay.overlay import Overlay  # noqa: E402
from kadr.overlay.shapes import Tool  # noqa: E402
from kadr.theme import DARK, LIGHT  # noqa: E402

DOCS = ROOT / "docs"
DPR = 2.0            # рисуем с двойной плотностью и уменьшаем — края получаются аккуратными
L = Qt.MouseButton.LeftButton
NO = Qt.KeyboardModifier.NoModifier


# ------------------------------------------------------------------ сцены «рабочего стола»
def _desktop(w: int, h: int, top: str, bottom: str) -> tuple[QPixmap, QPainter]:
    px = QPixmap(round(w * DPR), round(h * DPR))
    px.setDevicePixelRatio(DPR)
    p = QPainter(px)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    p.fillRect(QRectF(0, 0, w, h), g)
    return px, p


def _font(px: int, weight=QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def scene_report(w: int, h: int, dark: bool) -> QPixmap:
    px, p = _desktop(w, h, "#4A505C" if dark else "#7A7F88", "#353A44" if dark else "#6A707A")
    p.fillRect(QRectF(100, 90, 680, 470), QColor("#D6DEEA"))
    p.fillRect(QRectF(120, 110, 620, 420), QColor("#FFFFFF"))
    p.setPen(QColor("#222"))
    p.setFont(_font(28))
    p.drawText(QPointF(160, 172), "Quarterly report")
    for i, wd in enumerate((300, 320, 360, 390, 420, 450)):
        p.fillRect(QRectF(160, 220 + i * 40, wd, 16), QColor("#E1E6EE"))
    p.end()
    return px


def scene_login(w: int, h: int) -> QPixmap:
    px, p = _desktop(w, h, "#83858B", "#7B7E85")
    p.fillRect(QRectF(60, 50, 700, 470), QColor("#E8ECF5"))
    p.fillRect(QRectF(80, 70, 640, 420), QColor("#FFFFFF"))
    p.setPen(QColor("#1C1C1E"))
    p.setFont(_font(22))
    p.drawText(QPointF(110, 131), "Вход в аккаунт")
    p.setFont(_font(16))
    p.drawText(QPointF(110, 191), "Логин:    ivan.petrov@mail.ru")
    p.drawText(QPointF(110, 241), "Пароль:   Kadr-2026!secret")
    p.drawText(QPointF(110, 301), "Важно: смените пароль после первого входа в систему")
    p.fillRect(QRectF(110, 340, 140, 40), QColor("#3F6BFF"))
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(110, 340, 140, 40), Qt.AlignmentFlag.AlignCenter, "Войти")
    p.end()
    return px


def scene_brand(w: int, h: int) -> QPixmap:
    px, p = _desktop(w, h, "#857E77", "#5A6A8E")
    g = QLinearGradient(60, 60, 620, 420)
    g.setColorAt(0, QColor("#F4E6DA"))
    g.setColorAt(1, QColor("#D0DAEC"))
    p.fillRect(QRectF(60, 60, 560, 360), g)
    p.fillRect(QRectF(80, 80, 500, 300), QColor("#FFFFFF"))
    for i, c in enumerate(("#E63946", "#F1C40F", "#2A9D8F", "#264653")):
        p.fillRect(QRectF(110 + i * 110, 130, 90, 90), QColor(c))
    p.setPen(QColor("#1C1C1E"))
    p.setFont(_font(26))
    p.drawText(QPointF(110, 280), "Brand colors")
    p.end()
    return px


# -------------------------------------------------------------------------- помощники
def overlay_for(pixmap: QPixmap, tokens) -> Overlay:
    w, h = round(pixmap.width() / DPR), round(pixmap.height() / DPR)
    shot = ScreenShot(QGuiApplication.primaryScreen(), QRect(0, 0, w, h), pixmap)
    o = Overlay(shot, tokens, QColor("#FF3B30"), 4)
    o.show()
    o.resize(w, h)
    o._dim = 1.0
    o._dim_anim.stop()
    return o


def drag(o: Overlay, a, b, steps: int = 1) -> None:
    QTest.mousePress(o, L, NO, QPoint(*a))
    for k in range(1, steps + 1):
        t = k / steps
        QTest.mouseMove(o, QPoint(round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t)))
    QTest.mouseRelease(o, L, NO, QPoint(*b))


def stroke(o: Overlay, points) -> None:
    QTest.mousePress(o, L, NO, QPoint(*points[0]))
    for pt in points[1:]:
        QTest.mouseMove(o, QPoint(*pt))
    QTest.mouseRelease(o, L, NO, QPoint(*points[-1]))


def hover(o: Overlay, x: int, y: int) -> None:
    pt = QPointF(x, y)
    QApplication.sendEvent(o, QMouseEvent(QMouseEvent.Type.MouseMove, pt, QPointF(o.mapToGlobal(pt)),
                                          Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, NO))


def settle(o: Overlay) -> None:
    """Панели показываются с анимацией — ставим их сразу в конечное положение."""
    QApplication.processEvents()
    for panel in (o.toolbar, o.popup):
        if panel.isVisible() and panel._slide.state() == panel._slide.State.Running:
            panel.move_now(panel._slide.endValue())


def save(widget, name: str) -> None:
    img = widget.grab().toImage()
    size = (img.size().toSizeF() / img.devicePixelRatio()).toSize()
    img = img.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    img.setDevicePixelRatio(1.0)
    path = DOCS / name
    img.save(str(path), "PNG", 9)
    print(f"  {path.relative_to(ROOT)}  {img.width()}×{img.height()}")


# ------------------------------------------------------------------------------ картинки
def make_overlay(dark: bool) -> None:
    o = overlay_for(scene_report(1280, 800, dark), DARK if dark else LIGHT)
    drag(o, (100, 90), (781, 561))
    o.set_tool(Tool.RECT)
    drag(o, (150, 138), (421, 190))
    o.set_tool(Tool.ARROW)
    drag(o, (640, 420), (470, 250))
    o.set_tool(Tool.ELLIPSE)
    drag(o, (480, 420), (720, 520))
    o.set_tool(Tool.PEN)
    stroke(o, [(160, 480), (185, 495), (215, 492), (240, 475), (265, 462), (290, 464), (315, 478),
               (340, 494), (365, 492), (390, 474), (400, 480)])
    o.set_tool(Tool.LINE)
    drag(o, (160, 200), (420, 200))
    o.set_tool(Tool.STEP)
    QTest.mouseClick(o, L, NO, QPoint(135, 164))
    o.set_tool(Tool.TEXT)
    QTest.mouseClick(o, L, NO, QPoint(520, 170))
    o._set_width(5)
    o._editing.text = "Проверить!"      # QTest не умеет набирать кириллицу
    o._commit_text()
    o.set_tool(Tool.LINE)
    settle(o)
    save(o, f"overlay-{'dark' if dark else 'light'}.png")
    o.close()


def make_tools() -> None:
    o = overlay_for(scene_login(1100, 700), LIGHT)
    drag(o, (60, 50), (761, 521))
    o.set_tool(Tool.PIXELATE)
    drag(o, (182, 224), (352, 248))
    o._set_color(QColor("#FFCC00"))
    o.set_tool(Tool.MARKER)
    QTest.mousePress(o, L, NO, QPoint(104, 301))
    QTest.mouseMove(o, QPoint(300, 301))
    QTest.mouseRelease(o, L, Qt.KeyboardModifier.ShiftModifier, QPoint(474, 301))
    o._set_color(QColor("#FF3B30"))
    o.set_tool(Tool.LINE)
    drag(o, (182, 196), (344, 196))
    o.set_tool(Tool.STEP)
    for y in (184, 235, 360):
        QTest.mouseClick(o, L, NO, QPoint(95, y))
    settle(o)
    save(o, "tools.png")
    o.close()


def make_picker() -> None:
    o = overlay_for(scene_brand(1100, 760), LIGHT)
    drag(o, (60, 60), (621, 421))
    o._set_color(QColor("#34C759"))
    o._toggle_popup()
    o.popup.more.click()
    QApplication.processEvents()
    o._place_popup(animate=False)
    settle(o)
    save(o, "picker.png")
    o.close()


def make_pipette() -> None:
    o = overlay_for(scene_brand(1100, 760), LIGHT)
    drag(o, (60, 60), (621, 421))
    o._set_color(QColor("#34C759"))
    o.start_picking()
    settle(o)
    hover(o, 375, 175)          # после settle: иначе событие Enter вернёт курсор в угол
    save(o, "pipette.png")
    o.close()


def make_settings(dark: bool) -> None:
    from kadr.config import SettingsStore
    from kadr.theme import ThemeManager
    from kadr.ui.settings_window import SettingsWindow
    from kadr.updater import Updater

    store = SettingsStore()
    store.data.save_dir = "C:/Users/Ivan/Pictures/Kadr"
    store.data.replay_enabled = True
    store.data.replay_mic = True
    theme = ThemeManager("dark" if dark else "light")
    w = SettingsWindow(store, theme, updater=Updater())     # в сеть не ходит, пока не нажать кнопку
    w.resize(560, 900)
    w.show()
    QApplication.processEvents()
    content = w.findChild(QWidget, "Root")          # прокручиваемое содержимое — целиком, без прокрутки
    content.resize(560, content.sizeHint().height())
    content.layout().activate()
    QApplication.processEvents()
    save(content, f"settings-{'dark' if dark else 'light'}.png")
    w.close()


def main() -> None:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    DOCS.mkdir(exist_ok=True)
    print("Картинки для README:")
    make_overlay(dark=False)
    make_overlay(dark=True)
    make_tools()
    make_picker()
    make_pipette()
    make_settings(dark=False)
    make_settings(dark=True)


if __name__ == "__main__":
    main()
