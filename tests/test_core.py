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


def test_hotkey_any_key_without_modifiers(qapp):
    """Свободный выбор: одиночная клавиша без Ctrl/Shift допустима."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from kadr.hotkeys import hotkey_from_event
    from kadr.ui.widgets import HotkeyEdit

    for key, name in ((Qt.Key.Key_S, "s"), (Qt.Key.Key_Delete, "delete"), (Qt.Key.Key_F9, "f9")):
        hk = hotkey_from_event(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
        assert isinstance(hk, Hotkey) and hk.serialize() == name

    # Windows шлёт для PrtSc только отпускание клавиши — его тоже нужно ловить
    edit = HotkeyEdit("ctrl+a")
    got = []
    edit.hotkey_changed.connect(got.append)
    edit._start()
    qapp.sendEvent(edit, QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Print, Qt.KeyboardModifier.NoModifier))
    assert got == ["print_screen"] and edit.value() == "print_screen"


def test_pipette_and_palette_editing(qapp):
    """Пипетка берёт цвет пикселя скриншота; ПКМ по кружку меняет палитру."""
    from PySide6.QtGui import QPainter

    o = _overlay(qapp)
    p = QPainter(o._shot.pixmap)
    p.fillRect(QRect(200, 200, 50, 50), QColor("#12AB34"))   # логические координаты
    p.end()
    _drag(o, (100, 100), (400, 300))
    changed = []
    o.palette_changed.connect(changed.append)

    # правый клик по третьему кружку → режим редактирования
    o._toggle_popup()
    sw = o.popup._swatches[2]
    QTest.mouseClick(sw, Qt.MouseButton.RightButton)
    assert o.popup._edit_index == 2 and o.popup.picker.isVisible()

    # пипетка: клик по зелёному квадрату
    o.start_picking()
    assert o._picking and not o.popup.isVisible()
    QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(220, 220))
    assert not o._picking
    assert o._color.name().upper() == "#12AB34"
    assert changed and changed[-1][2] == "#12AB34"          # кружок палитры заменён

    # HEX-поле
    o.popup.hex.setText("ff00aa")
    o.popup._on_hex()
    assert o._color.name().upper() == "#FF00AA"
    o.close()


def test_palette_is_saved_and_validated(tmp_path, monkeypatch):
    from kadr import config

    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    store = config.SettingsStore()
    pal = list(store.data.palette)
    pal[0] = "#ABCDEF"
    store.set("palette", pal)
    store.flush()                                                   # запись отложена — сбрасываем
    assert config.SettingsStore().data.palette[0] == "#ABCDEF"      # сохранилось на диск
    broken = config.Settings(palette=["red", "#12345", 5])
    assert broken.palette == config.DEFAULT_PALETTE                 # мусор → стандартные цвета


def test_uninstall_removes_user_data_not_screenshots(tmp_path, monkeypatch, qapp):
    from kadr import uninstall

    cfg, shots = tmp_path / "cfg", tmp_path / "Pictures"
    cfg.mkdir()
    (cfg / "settings.json").write_text("{}")
    shots.mkdir()
    (shots / "Kadr_1.png").write_bytes(b"x")
    calls = []
    monkeypatch.setattr(uninstall, "config_dir", lambda: cfg)
    monkeypatch.setattr(uninstall.autostart, "set_enabled", lambda on: calls.append(on))
    monkeypatch.setattr(uninstall, "remove_shortcuts", lambda: calls.append("lnk"))
    assert uninstall.uninstall() == "manual"      # не frozen → деинсталлятора нет
    assert not cfg.exists() and (shots / "Kadr_1.png").exists()
    assert calls == [False, "lnk"]


def test_settings_palette_follows_store(qapp, tmp_path, monkeypatch):
    from kadr import config
    from kadr.theme import ThemeManager
    from kadr.ui.settings_window import SettingsWindow

    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    store = config.SettingsStore()
    w = SettingsWindow(store, ThemeManager("light"))
    pal = list(store.data.palette)
    pal[4] = "#010203"
    store.set("palette", pal)                      # например, изменили в оверлее
    assert w._pal_buttons[4].color.name().upper() == "#010203"
    w.close()


def test_partial_repaint_leaves_no_stale_pixels(qapp):
    """Оверлей перерисовывает только изменённые области — на экране не должно оставаться «хвостов»."""
    import math

    from kadr.overlay.shapes import Tool

    o = _overlay(qapp, 400, 300)
    o._dim_anim.stop()
    o._dim = 1.0
    o.update()

    def stale() -> int:
        qapp.processEvents()
        shown = qapp.primaryScreen().grabWindow(o.winId()).toImage().convertToFormat(QImage.Format.Format_RGB32)
        fresh = o.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
        skip = [w.geometry() for w in (o.toolbar, o.popup) if w.isVisible()]
        return sum(shown.pixel(x, y) != fresh.pixel(x, y)
                   for y in range(0, 300, 3) for x in range(0, 400, 3)
                   if not any(r.contains(x, y) for r in skip))

    for i in range(10):
        QTest.mouseMove(o, QPoint(50 + i * 9, 40 + i * 5))
    QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 50))
    for i in range(12):
        QTest.mouseMove(o, QPoint(200 + int(90 * math.sin(i)), 150 + int(60 * math.cos(i))))
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(300, 220))
    assert stale() == 0
    for tool in (Tool.PEN, Tool.ARROW, Tool.ELLIPSE):
        o.set_tool(tool)
        QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100, 100))
        for i in range(15):
            QTest.mouseMove(o, QPoint(100 + i * 12, 100 + int(40 * math.sin(i / 2))))
        QTest.mouseMove(o, QPoint(150, 80))
        QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 80))
        assert stale() == 0, tool
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert stale() == 0
    o.close()
