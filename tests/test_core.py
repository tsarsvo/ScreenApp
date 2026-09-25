"""Базовые тесты. Запуск: QT_QPA_PLATFORM=offscreen python -m pytest -q"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from kadr.hotkeys import Hotkey


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- hotkeys
def test_hotkey_roundtrip():
    hk = Hotkey.parse("shift+ctrl+print_screen")
    assert hk.serialize() == "ctrl+shift+print_screen"
    assert "PrtSc" in hk.label()
    assert Hotkey.parse("ctrl+alt+s").win_vk() == ord("S")
    assert Hotkey.parse("f5").win_vk() == 0x74


@pytest.mark.parametrize("bad", ["", "ctrl+", "hyper+a", "ctrl+ф", "ctrl+enter"])
def test_hotkey_rejects_garbage(bad):
    assert Hotkey.parse(bad) is None


# ---------------------------------------------------------------- history
def test_history_undo_redo():
    from kadr.overlay.history import History
    from kadr.overlay.shapes import RectShape

    h = History()
    a, b, c = (RectShape(QColor("red"), 2) for _ in range(3))
    h.push(a)
    h.push(b)
    assert h.undo() and h.shapes == [a]
    assert h.redo() and h.shapes == [a, b]
    h.undo()
    h.push(c)                     # новое действие очищает redo
    assert not h.can_redo() and h.shapes == [a, c]


# ---------------------------------------------------------------- saving
@pytest.mark.parametrize("fmt", ["png", "jpg", "webp"])
def test_save_formats(qapp, tmp_path, fmt):
    from kadr.config import Settings
    from kadr.saver import save_image

    img = QImage(64, 48, QImage.Format.Format_RGB32)
    img.fill(QColor("#3F6BFF"))
    path = save_image(img, Settings(save_dir=str(tmp_path), image_format=fmt, quality=80))
    assert path.suffix == f".{fmt}" and path.stat().st_size > 0
    assert QImage(str(path)).size() == img.size() or fmt == "webp"
    # второй файл в ту же секунду не перезаписывает первый
    assert save_image(img, Settings(save_dir=str(tmp_path), image_format=fmt)) != path


# ---------------------------------------------------------------- autostart
@pytest.mark.skipif(sys.platform != "linux", reason="XDG autostart")
def test_autostart_linux(tmp_path, monkeypatch):
    from kadr import autostart

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    autostart.set_enabled(True)
    desktop = tmp_path / "autostart" / "kadr.desktop"
    assert autostart.is_enabled() and "main.py" in desktop.read_text()
    autostart.set_enabled(False)
    assert not autostart.is_enabled()


# ---------------------------------------------------------------- overlay
def _overlay(qapp, w=800, h=600):
    from kadr.capture import ScreenShot
    from kadr.overlay.overlay import Overlay
    from kadr.theme import LIGHT

    px = QPixmap(w * 2, h * 2)
    px.fill(QColor("white"))
    px.setDevicePixelRatio(2)
    shot = ScreenShot(QGuiApplication.primaryScreen(), QRect(0, 0, w, h), px)
    o = Overlay(shot, LIGHT, QColor("#FF3B30"), 4)
    o.show()
    o.resize(w, h)
    return o


def _drag(o, a, b):
    QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*a))
    QTest.mouseMove(o, QPoint(*b))
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*b))


def test_overlay_select_draw_export(qapp):
    from kadr.overlay.shapes import Tool

    o = _overlay(qapp)
    _drag(o, (100, 100), (300, 250))
    assert o._sel == QRect(QPoint(100, 100), QPoint(300, 250))
    assert o.toolbar.isVisible()
    # панель не перекрывает выделение
    tb = o.toolbar.geometry().adjusted(10, 10, -10, -10)
    assert not tb.intersects(o._sel)

    for tool in (Tool.PEN, Tool.ARROW, Tool.RECT, Tool.ELLIPSE):
        o.set_tool(tool)
        _drag(o, (120, 120), (200, 200))
    assert len(o._history.shapes) == 4
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert len(o._history.shapes) == 3
    QTest.keyClick(o, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert len(o._history.shapes) == 4

    img = o.render_selection()
    assert (img.width(), img.height()) == (402, 302)  # физические пиксели при DPR 2
    o.close()


def test_overlay_move_resize_and_click_fullscreen(qapp):
    o = _overlay(qapp)
    QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
    assert o._sel == o.rect()                          # клик без протяжки — весь экран
    o.reset_selection()
    _drag(o, (100, 100), (300, 250))
    _drag(o, (200, 200), (250, 220))                   # перемещение (инструмент «Выделение»)
    assert o._sel.topLeft() == QPoint(150, 120)
    _drag(o, (o._sel.right(), o._sel.bottom()), (500, 400))   # ручка правого нижнего угла
    assert o._sel.bottomRight() == QPoint(500, 400)
    o.close()


def test_toolbar_goes_above_when_no_room_below(qapp):
    o = _overlay(qapp)
    _drag(o, (100, 300), (500, 590))
    assert o.toolbar.geometry().center().y() < o._sel.top()
    o.close()
