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
    assert o._sel is None and not o.toolbar.isVisible()   # клик без протяжки ничего не выделяет
    QTest.keyClick(o, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert o._sel == o.rect()                             # Ctrl+A — весь экран
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
    for tool in (Tool.PEN, Tool.ARROW, Tool.ELLIPSE, Tool.MARKER, Tool.PIXELATE, Tool.STEP):
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


def test_rapid_clicks_do_not_select_screen_or_copy(qapp):
    """Баг: резкий повторный клик выделял весь экран, панель уезжала в угол, а двойной клик
    копировал весь экран и закрывал оверлей. Воспроизводим точную последовательность Windows:
    нажатие, отпускание, двойной клик, отпускание."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    o = _overlay(qapp)
    copied = []
    o.copy_requested.connect(copied.append)

    def send(kind, x, y):
        p = QPointF(x, y)
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        qapp.sendEvent(o, QMouseEvent(kind, p, o.mapToGlobal(p), Qt.MouseButton.LeftButton, buttons,
                                      Qt.KeyboardModifier.NoModifier))

    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                 QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease):
        send(kind, 300, 200)
    assert o._sel is None and not o.toolbar.isVisible() and not copied

    # второй резкий клик сразу переходит в протяжку — это должно стать обычным выделением
    send(QEvent.Type.MouseButtonPress, 100, 100)
    send(QEvent.Type.MouseButtonRelease, 100, 100)
    send(QEvent.Type.MouseButtonDblClick, 100, 100)
    QTest.mouseMove(o, QPoint(260, 220))
    send(QEvent.Type.MouseButtonRelease, 260, 220)
    assert o._sel == QRect(QPoint(100, 100), QPoint(260, 220)) and not copied

    # а двойной клик внутри готового выделения по-прежнему копирует
    send(QEvent.Type.MouseButtonPress, 180, 160)
    send(QEvent.Type.MouseButtonRelease, 180, 160)
    send(QEvent.Type.MouseButtonDblClick, 180, 160)
    assert copied
    o.close()


def test_marker_pixelate_and_steps(qapp):
    from PySide6.QtGui import QPainter

    from kadr.overlay.shapes import MarkerStroke, PixelateShape, StepShape, Tool

    o = _overlay(qapp)
    # мелкая «шахматка» — секрет, который должна скрыть пикселизация
    p = QPainter(o._shot.pixmap)
    for y in range(200, 260, 2):
        for x in range(200, 300, 2):
            p.fillRect(QRect(x, y, 1, 1), QColor("#000000"))
    p.end()
    _drag(o, (100, 100), (500, 400))

    o.set_tool(Tool.PIXELATE)
    _drag(o, (190, 190), (310, 270))
    o.set_tool(Tool.MARKER)
    QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(120, 350))
    QTest.mouseMove(o, QPoint(200, 380))
    QTest.mouseMove(o, QPoint(300, 352), )
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(300, 352))
    o.set_tool(Tool.STEP)
    for x in (150, 250, 350):
        QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, 320))

    kinds = [type(s) for s in o._history.shapes]
    assert kinds == [PixelateShape, MarkerStroke, StepShape, StepShape, StepShape]
    marker = o._history.shapes[1]
    assert len(marker.points) == 2                         # Shift → ровная линия
    assert [s.number for s in o._history.shapes[2:]] == [1, 2, 3]
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 320))
    assert o._history.shapes[-1].number == 3               # после отмены нумерация продолжается верно

    # В сохранённом файле «шахматки» больше нет: соседние пиксели внутри блока одинаковые
    img = o.render_selection()                            # DPR 2 → физические пиксели
    x0, y0 = (220 - 100) * 2, (220 - 100) * 2
    block = [img.pixel(x0 + dx, y0 + dy) for dx in range(4) for dy in range(4)]
    assert len(set(block)) <= 2
    o.close()


def test_history_keeps_last_items(qapp, tmp_path):
    import time

    from kadr.history import MAX_ITEMS, History

    h = History(tmp_path / "history")
    img = QImage(40, 30, QImage.Format.Format_RGB32)
    for i in range(MAX_ITEMS + 3):
        img.fill(QColor(i * 10, 0, 0))
        h.add(img)
        time.sleep(0.01)
    deadline = time.time() + 10
    while len(list((tmp_path / "history").glob("shot_*.png"))) != MAX_ITEMS and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    items = h.items()
    assert len(items) == MAX_ITEMS
    assert QImage(str(items[0])).pixelColor(0, 0).red() == (MAX_ITEMS + 2) * 10   # новые — сверху
    assert "сегодня" in History.label(items[0])
    h.clear()
    assert h.items() == []


def test_pin_window_zoom_opacity_close(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    from kadr.pin import PinWindow

    img = QImage(200, 100, QImage.Format.Format_RGB32)
    img.fill(QColor("#3F6BFF"))
    w = PinWindow(img, 2.0, QPoint(100, 100))          # DPR 2 → 100×50 логических
    w.show()
    assert (w.width(), w.height()) == (102, 52)

    def wheel(delta, mods=Qt.KeyboardModifier.NoModifier):
        qapp.sendEvent(w, QWheelEvent(QPointF(10, 10), QPointF(110, 110), QPoint(), QPoint(0, delta),
                                      Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False))

    wheel(120)
    assert w.width() > 102                               # колесо — увеличить
    wheel(-120, Qt.KeyboardModifier.ControlModifier)
    assert w.windowOpacity() < 1.0                       # Ctrl+колесо — прозрачнее
    closed = []
    w.closed.connect(closed.append)
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert closed


def test_overlay_pin_emits_selection_at_its_screen_position(qapp):
    o = _overlay(qapp)
    _drag(o, (100, 80), (300, 200))
    got = []
    o.pin_requested.connect(lambda img, pt, dpr: got.append((img.size(), pt, dpr)))
    QTest.keyClick(o, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert got and got[0][1] == o.mapToGlobal(QPoint(100, 80)) and got[0][2] == 2.0
    o.close()


# ------------------------------------------------ рисование за выделением, шаги, закреплённый снимок
def test_drawing_outside_selection_keeps_it_and_clips(qapp):
    """Рисовать можно начать и за рамкой, но рамка не меняется: в файл попадает только
    то, что внутри. Текст и номер шага за рамкой не ставятся (их не было бы видно)."""
    from kadr.overlay.shapes import Tool

    o = _overlay(qapp)
    _drag(o, (100, 100), (300, 250))
    sel0 = QRect(o._sel)
    o._set_color(QColor("#0000FF"))
    o.set_tool(Tool.LINE)
    _drag(o, (400, 175), (200, 175))                     # линия «с края» внутрь рамки
    o.set_tool(Tool.PEN)
    _drag(o, (20, 30), (60, 40))                         # штрих целиком снаружи
    assert o._sel == sel0 and len(o._history.shapes) == 2
    img = o.render_selection()
    assert (img.width(), img.height()) == (sel0.width() * 2, sel0.height() * 2)
    assert img.pixelColor((250 - 100) * 2, (175 - 100) * 2).blue() > 200   # часть внутри — в файле
    for tool in (Tool.TEXT, Tool.STEP):
        o.set_tool(tool)
        QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(500, 400))
        o._commit_text()
    assert len(o._history.shapes) == 2 and o._editing is None
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert o._sel == sel0 and len(o._history.shapes) == 1
    o.close()


def test_step_can_be_dragged_by_its_center_and_undone(qapp):
    from PySide6.QtCore import QPointF

    from kadr.overlay.shapes import Tool

    o = _overlay(qapp)
    _drag(o, (100, 100), (500, 400))
    o.set_tool(Tool.STEP)
    for x in (150, 250):
        QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, 200))
    first = o._history.shapes[0]
    QTest.mouseMove(o, QPoint(152, 202))
    assert o.cursor().shape() == Qt.CursorShape.OpenHandCursor   # над кружком — «рука»
    _drag(o, (152, 202), (302, 322))
    assert len(o._history.shapes) == 2                   # новый шаг не появился
    assert first.pos == QPointF(300, 320) and first.number == 1
    o.set_tool(Tool.SELECT)
    _drag(o, (302, 322), (1000, 1000))                   # и в режиме «Выделение»; наружу не уходит
    assert o._sel.contains(first.pos.toPoint())
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert first.pos == QPointF(300, 320)
    QTest.keyClick(o, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert first.pos == QPointF(150, 200) and len(o._history.shapes) == 2
    o.close()


def test_guides_do_not_stay_behind(qapp):
    from PySide6.QtCore import QEvent

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    o = _overlay(qapp)
    qapp.sendEvent(o, QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(200, 200), QPointF(200, 200),
                                  Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert o._mouse == QPoint(200, 200)
    qapp.sendEvent(o, QEvent(QEvent.Type.Leave))         # мышь ушла на другой монитор
    assert not o.rect().contains(o._mouse)
    o.close()


def test_handle_cursor_under_toolbar_shadow(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    o = _overlay(qapp)
    _drag(o, (100, 100), (300, 250))
    o.toolbar.move_now(o.toolbar._slide.endValue())    # анимация появления закончилась
    br = QPoint(o._sel.right(), o._sel.bottom() + 4)     # в зоне ручки правого нижнего угла
    assert o._hit_handle(br) == "br"
    assert o.toolbar.geometry().contains(br)             # …и на прозрачном поле тени панели

    def hover(widget, pt):
        pt = QPointF(pt)
        qapp.sendEvent(widget, QMouseEvent(QMouseEvent.Type.MouseMove, pt, QPointF(widget.mapToGlobal(pt)),
                                           Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                                           Qt.KeyboardModifier.NoModifier))

    hover(o, QPoint(200, 200))
    assert o.cursor().shape() == Qt.CursorShape.OpenHandCursor
    hover(o.toolbar, o.toolbar.mapFrom(o, br))           # движение приходит панели, а не оверлею
    assert o.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    o.close()


def test_pin_resize_by_edge_keeps_aspect(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    from kadr.pin import PinWindow

    img = QImage(200, 100, QImage.Format.Format_RGB32)
    img.fill(QColor("#3F6BFF"))
    w = PinWindow(img, 1.0, QPoint(100, 100))
    w.show()
    geo = w.geometry()

    def send(kind, local, buttons):
        g = QPointF(w.mapToGlobal(local))
        btn = Qt.MouseButton.LeftButton if kind != QMouseEvent.Type.MouseMove else Qt.MouseButton.NoButton
        qapp.sendEvent(w, QMouseEvent(kind, QPointF(local), g, btn, buttons, Qt.KeyboardModifier.NoModifier))

    L = Qt.MouseButton.LeftButton
    # правый край тянем на 100 px вправо → вдвое шире, пропорции сохранены
    send(QMouseEvent.Type.MouseMove, QPoint(w.width() - 2, 50), Qt.MouseButton.NoButton)
    assert w.cursor().shape() == Qt.CursorShape.SizeHorCursor
    start = QPoint(w.width() - 2, 50)
    send(QMouseEvent.Type.MouseButtonPress, start, L)
    g0 = w.mapToGlobal(start)
    qapp.sendEvent(w, QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(start + QPoint(200, 0)),
                                  QPointF(g0 + QPoint(200, 0)), Qt.MouseButton.NoButton, L,
                                  Qt.KeyboardModifier.NoModifier))
    send(QMouseEvent.Type.MouseButtonRelease, start, Qt.MouseButton.NoButton)
    assert (w.width(), w.height()) == (402, 202)
    assert w.geometry().topLeft() == geo.topLeft()       # левый верхний угол на месте
    w.close()


def test_line_tool_draws_straight_line_snapped_with_shift(qapp):
    from kadr.overlay.shapes import LineShape, Tool

    o = _overlay(qapp)
    _drag(o, (100, 100), (500, 400))
    QTest.keyClick(o, Qt.Key.Key_L)
    assert o._tool == Tool.LINE and o.toolbar._tool_buttons[Tool.LINE].isChecked()
    QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 300))
    QTest.mouseMove(o, QPoint(300, 290))
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(300, 290))
    line = o._history.shapes[-1]
    assert isinstance(line, LineShape)
    assert abs(line.end.y() - 300) < 0.01                 # Shift → ровно горизонтально
    img = o.render_selection()
    assert img.pixelColor((200 - 100) * 2, (300 - 100) * 2).red() > 200   # линия есть в файле
    o.close()


def test_layer_rebuild_leaves_nothing_behind_after_undo(qapp):
    """Слой не пересоздаётся, а стирается по области фигур: после отмены всех фигур
    (включая самые толстые) в нём не должно остаться ни пикселя."""
    from kadr.overlay.shapes import Tool

    o = _overlay(qapp)
    _drag(o, (20, 20), (780, 580))
    o._set_width(40)
    for k, tool in enumerate((Tool.PEN, Tool.ARROW, Tool.LINE, Tool.RECT, Tool.ELLIPSE, Tool.MARKER,
                              Tool.PIXELATE, Tool.STEP)):
        o.set_tool(tool)
        _drag(o, (100 + k * 70, 150), (160 + k * 70, 400))
    o.set_tool(Tool.TEXT)
    QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 480))
    QTest.keyClicks(o, "Kadr")
    o._commit_text()
    buf = o._ensure_layer()
    assert len(o._history.shapes) == 9
    while o._history.can_undo():
        o.undo()
    layer = o._ensure_layer()
    assert layer is buf                                  # буфер переиспользован, а не создан заново
    empty = QImage(layer.size(), QImage.Format.Format_ARGB32_Premultiplied)
    empty.fill(Qt.GlobalColor.transparent)
    assert layer.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied) == empty
    o.close()


@pytest.mark.parametrize("dpr", [1.25, 1.5, 1.75])
def test_partial_layer_rebuild_matches_full_rebuild(qapp, dpr):
    """Ctrl+Z и перенос шага пересобирают только кусок слоя — результат должен совпадать
    с полной сборкой пиксель в пиксель (в том числе при дробном масштабе Windows)."""
    from kadr.capture import ScreenShot
    from kadr.overlay.overlay import Overlay
    from kadr.overlay.shapes import StepShape, Tool
    from kadr.theme import LIGHT

    w, h = 640, 480
    px = QPixmap(round(w * dpr), round(h * dpr))
    px.fill(QColor("white"))
    px.setDevicePixelRatio(dpr)
    o = Overlay(ScreenShot(QGuiApplication.primaryScreen(), QRect(0, 0, w, h), px), LIGHT, QColor("#FF3B30"), 6)
    o.show()
    o.resize(w, h)
    _drag(o, (10, 10), (630, 470))
    for k, tool in enumerate((Tool.RECT, Tool.MARKER, Tool.ARROW, Tool.ELLIPSE, Tool.PEN, Tool.LINE) * 2):
        o.set_tool(tool)
        _drag(o, (60 + k * 37, 80 + (k % 3) * 40), (200 + k * 29, 300 - (k % 4) * 30))   # фигуры перекрываются
    o.set_tool(Tool.STEP)
    for x in (120, 260, 400):
        QTest.mouseClick(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, 200))
    o._ensure_layer()

    step = [s for s in o._history.shapes if isinstance(s, StepShape)][1]
    _drag(o, (260, 200), (330, 260))                     # перенос шага поверх других фигур
    o.undo()
    o.undo()                                             # отмена переноса и последнего шага
    o.redo()
    o._ensure_layer()
    assert step.pos.toPoint() == QPoint(260, 200)
    partial = o._layer.toImage()
    o._invalidate_layer()                                # полная сборка для сравнения
    full = o._ensure_layer().toImage()
    # Qt по-разному округляет сглаженные края внутри и вне обрезки: ±1 из 255 допустимо,
    # а вот пропавшая или «застрявшая» фигура дала бы разницу в десятки единиц
    assert _max_channel_diff(partial, full) <= 2
    o.close()



def _max_channel_diff(a, b) -> int:
    assert a.size() == b.size()
    a = a.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    b = b.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    da, db = bytes(a.constBits()), bytes(b.constBits())
    if da == db:
        return 0
    return max(abs(x - y) for x, y in zip(da, db) if x != y)


def test_no_guides_or_hint_while_selection_is_being_dragged(qapp):
    """Нажали ЛКМ и тянем: направляющие и подсказка «Выделите область» должны исчезнуть
    сразу при нажатии. Раньше выделение 0×0 в момент нажатия считалось «пустым», и они
    рисовались заново, а при протяжке стирались только там, где прошло выделение."""
    o = _overlay(qapp)
    o._dim = 1.0

    def grab():                     # то, что сейчас нарисовано на оверлее
        img = QImage(o.size(), QImage.Format.Format_RGB32)
        o.render(img)
        return img

    bg = lambda img, x, y: img.pixelColor(x, y).name()               # noqa: E731
    QTest.mouseMove(o, QPoint(200, 200))
    img = grab()
    assert bg(img, 600, 200) != bg(img, 600, 260)                     # до нажатия направляющие есть
    QTest.mousePress(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 200))
    img = grab()
    assert bg(img, 600, 200) == bg(img, 600, 260)                     # горизонтальная направляющая пропала
    assert bg(img, 200, 500) == bg(img, 260, 500)                     # и вертикальная
    assert bg(img, 400, 39) == bg(img, 400, 300)                      # и подсказка сверху
    QTest.mouseMove(o, QPoint(260, 240))
    img = grab()
    assert bg(img, 600, 200) == bg(img, 600, 260) and bg(img, 400, 39) == bg(img, 400, 300)
    QTest.mouseRelease(o, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(260, 240))
    o.close()


def test_settings_admin_toggle(qapp, tmp_path, monkeypatch):
    """Тумблер «Права администратора»: включение перезапускает Kadr с правами и сохраняется;
    отказ в запросе Windows возвращает тумблер; выключение просто сохраняется."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from kadr import admin
    from kadr.config import SettingsStore
    from kadr.theme import ThemeManager
    from kadr.ui.settings_window import SettingsWindow

    monkeypatch.setattr(admin, "supported", lambda: True)
    monkeypatch.setattr(admin, "is_elevated", lambda: False)
    store = SettingsStore()
    w = SettingsWindow(store, ThemeManager("light"))
    restarted = []
    w.restarting.connect(lambda: restarted.append(True))
    assert not w.admin_toggle.isChecked()

    monkeypatch.setattr(admin, "relaunch_as_admin", lambda *a: False)   # нажали «Нет» в запросе Windows
    w.admin_toggle.click()
    assert not restarted and not w.admin_toggle.isChecked() and not store.data.run_as_admin
    assert "не дала разрешение" in w.admin_status.text()

    monkeypatch.setattr(admin, "relaunch_as_admin", lambda *a: True)
    w.admin_toggle.click()
    assert restarted and store.data.run_as_admin                        # сохраняется на следующие запуски
    w.close()

    monkeypatch.setattr(admin, "is_elevated", lambda: True)              # новая копия — уже с правами
    w = SettingsWindow(store, ThemeManager("light"))
    assert w.admin_toggle.isChecked() and "Работает с правами" in w.admin_status.text()
    w.admin_toggle.click()                                               # выключили
    assert not store.data.run_as_admin and "после перезапуска" in w.admin_status.text()
    w.close()


def test_elevate_at_start_decision(monkeypatch):
    from kadr import admin

    monkeypatch.setattr(admin, "supported", lambda: True)
    monkeypatch.setattr(admin, "is_elevated", lambda: False)
    assert admin.should_elevate_at_start([], wanted=True)
    assert not admin.should_elevate_at_start([], wanted=False)
    assert not admin.should_elevate_at_start(["--restarted"], wanted=True)   # без запуска по кругу
    monkeypatch.setattr(admin, "is_elevated", lambda: True)
    assert not admin.should_elevate_at_start([], wanted=True)


def test_topmost_task_manager_hidden_during_selection_and_restored(monkeypatch):
    """Диспетчер задач «поверх всех» прячется на время выделения и возвращается."""
    import types

    from kadr import topmost

    state = {"visible": True, "shown_with": None}
    user32 = types.SimpleNamespace(
        FindWindowW=lambda cls, _t: 77 if cls == "TaskManagerWindow" else 0,
        IsWindowVisible=lambda h: state["visible"],
        GetWindowLongW=lambda h, i: 0x8,                 # WS_EX_TOPMOST
        ShowWindow=lambda h, cmd: state.update(visible=cmd != 0, shown_with=cmd),
        IsWindow=lambda h: True,
    )
    monkeypatch.setattr(topmost.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(user32=user32)))
    hidden = topmost.hide_over_overlay()
    assert hidden == [77] and not state["visible"]
    topmost.restore(hidden)
    assert state["visible"] and state["shown_with"] == 8           # SW_SHOWNA — без кражи фокуса

    user32.GetWindowLongW = lambda h, i: 0                         # обычное окно — не трогаем
    assert topmost.hide_over_overlay() == [] and state["visible"]

def test_admin_restart_command_line(monkeypatch):
    """Новая копия получает флаг --restarted (ждёт, пока старая закроется)."""
    import types

    from kadr import admin

    calls = []
    shell32 = types.SimpleNamespace(ShellExecuteW=lambda *a: calls.append(a) or 42)
    monkeypatch.setattr(admin, "supported", lambda: True)
    monkeypatch.setattr(admin, "launch_command", lambda: [r"C:\Program Files\Kadr\Kadr.exe"])
    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace(windll=types.SimpleNamespace(shell32=shell32)))
    assert admin.relaunch_as_admin(["--region"])
    _, verb, exe, params, _, show = calls[0]
    assert (verb, exe, params, show) == ("runas", r"C:\Program Files\Kadr\Kadr.exe", '"--region" "--restarted"', 1)


def test_pin_drawing_mode_quick_colors_and_copy(qapp):
    """Карандаш в углу закреплённого снимка: рисование тремя быстрыми цветами, Ctrl+Z,
    копирование вместе с рисунком; снова карандаш — режим выключен, окно снова двигается."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    from kadr.pin import PinWindow

    img = QImage(400, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("#FFFFFF"))
    w = PinWindow(img, 2.0, QPoint(100, 100), colors=["#0000FF", "#00FF00", "#FF0000"])   # 200×100 логических
    w.show()
    copied = []
    w.copy_requested.connect(copied.append)
    w._hover = True                                        # мышь над снимком — панель видна

    def mouse(kind, pt, buttons=Qt.MouseButton.LeftButton):
        pt = QPointF(*pt)
        btn = Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        qapp.sendEvent(w, QMouseEvent(kind, pt, QPointF(w.mapToGlobal(pt)), btn, buttons,
                                      Qt.KeyboardModifier.NoModifier))

    def click(r):
        c = r.center()
        mouse(QMouseEvent.Type.MouseButtonPress, (c.x(), c.y()))
        mouse(QMouseEvent.Type.MouseButtonRelease, (c.x(), c.y()), Qt.MouseButton.NoButton)

    ctrls = dict(w._controls())
    assert set(ctrls) == {"pen", "copy"}                   # без режима рисования — только две кнопки
    click(ctrls["pen"])
    ctrls = dict(w._controls())
    assert w._drawing and {"color0", "color1", "color2"} <= set(ctrls)
    click(ctrls["color2"])                                 # красный
    mouse(QMouseEvent.Type.MouseButtonPress, (20, 50))
    mouse(QMouseEvent.Type.MouseMove, (120, 50))
    mouse(QMouseEvent.Type.MouseButtonRelease, (120, 50), Qt.MouseButton.NoButton)
    assert w.pos() == QPoint(100 - 1, 100 - 1)             # в режиме рисования окно не двигается
    click(dict(w._controls())["copy"])
    out = copied[-1]
    assert out.size() == img.size()                        # копия в полном разрешении снимка
    px = out.pixelColor(70 * 2, 50 * 2)                    # точка на линии (DPR 2)
    assert px.red() > 200 and px.green() < 80
    QTest.keyClick(w, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert w.rendered_image().pixelColor(140, 100) == QColor("#FFFFFF")   # отменили
    click(dict(w._controls())["pen"])
    assert not w._drawing and set(dict(w._controls())) == {"pen", "copy"}
    w.close()


def test_shape_outside_selection_is_visible_faded_but_not_saved(qapp):
    from kadr.overlay.shapes import Tool

    o = _overlay(qapp)
    o._dim = 1.0
    _drag(o, (100, 100), (300, 250))
    o._set_color(QColor("#FF0000"))
    o._set_width(10)
    o.set_tool(Tool.LINE)
    _drag(o, (150, 175), (600, 175))                      # линия уходит далеко за правый край рамки

    def shot():
        img = QImage(o.size(), QImage.Format.Format_RGB32)
        o.render(img)
        return img

    img = shot()
    inside, outside, empty = img.pixelColor(200, 175), img.pixelColor(500, 175), img.pixelColor(500, 300)
    assert inside.red() > 230 and inside.green() < 40            # внутри — как в файле
    assert outside.red() > empty.red() + 30                      # снаружи линию видно…
    assert outside.red() < 230 and outside.green() > 40          # …но полупрозрачной
    saved = o.render_selection()
    assert saved.width() == o._sel.width() * 2                   # в файл — только рамка
    o.close()
