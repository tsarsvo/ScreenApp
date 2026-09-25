"""Контроллер приложения: трей, одна копия, горячие клавиши, запуск захвата."""
from __future__ import annotations

import dataclasses
import getpass
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_ID, APP_NAME, __version__, autostart, icons
from .capture import grab_full_desktop, grab_screens
from .config import SettingsStore
from .hotkeys import HotkeyManager, label_for
from .overlay import CaptureSession
from .replay import ReplayOptions, ReplayRecorder
from .saver import copy_to_clipboard, save_image
from .theme import ThemeManager
from .updater import Updater, can_self_update

# Задержка перед снимком из меню трея — чтобы само меню успело исчезнуть с экрана.
# По горячей клавише снимок делается сразу.
MENU_CAPTURE_DELAY_MS = 200


class _SaveSignals(QObject):
    """Мост из фонового потока сохранения в GUI-поток."""

    saved = Signal(object)    # Path
    failed = Signal(str)


class KadrApp(QObject):
    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self.qapp = qapp
        self.store = SettingsStore()
        self.theme = ThemeManager(self.store.data.theme)
        self.session: CaptureSession | None = None
        self.settings_window = None

        self.hotkeys = HotkeyManager()
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.store.changed.connect(self._on_setting_changed)

        # Буфер повтора: запускается в фоне, если включён в настройках
        self.replay = ReplayRecorder()
        self.replay.cache_dir = self.store.path.parent
        self.replay.running_changed.connect(self._on_replay_running)
        self.replay.error.connect(lambda e: self.notify(e, error=True))
        self.replay.saved.connect(lambda p: self.notify(f"Повтор сохранён: {p.name}"))
        self.replay.save_failed.connect(lambda e: self.notify(f"Повтор не сохранён: {e}", error=True))
        self._replay_restart = QTimer(self, singleShot=True, interval=800)  # debounce при смене настроек
        self._replay_restart.timeout.connect(self._apply_replay)
        qapp.aboutToQuit.connect(lambda: self.replay.stop(wait=True))
        qapp.aboutToQuit.connect(self.store.flush)

        # Сохранение файлов идёт в фоне: кодирование 4K PNG/WEBP занимает 0.3–0.8 с,
        # и интерфейс не должен на это время замирать
        self._save_signals = _SaveSignals()
        self._save_signals.saved.connect(self._on_saved)
        self._save_signals.failed.connect(lambda e: self.notify(f"Ошибка сохранения: {e}", error=True))

        self.updater = Updater()
        self.updater.available.connect(self._on_update_available)
        self.updater.up_to_date.connect(lambda: self.notify(f"У вас последняя версия — {__version__}"))
        self.updater.failed.connect(lambda e: self.notify(e, error=True))
        self.updater.downloading.connect(lambda: self.notify("Скачиваю обновление…"))
        self.updater.ready_to_quit.connect(self.qapp.quit)

        self._build_tray()
        self._hotkey_errors = self._register_hotkeys()
        self._sync_autostart()
        self.theme.changed.connect(self._retheme_tray)

        if self.hotkeys.error:
            self.notify(self.hotkeys.error, error=True)
        if self.store.data.replay_enabled:
            QTimer.singleShot(1500, self._apply_replay)

        # Обновления: тихая проверка через 10 с после запуска и затем раз в сутки
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(6 * 3600 * 1000)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start()
        QTimer.singleShot(10_000, self._auto_check_updates)

    # -------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        mono = sys.platform == "darwin"  # на macOS — template-иконка под цвет строки меню
        self.tray = QSystemTrayIcon(icons.logo_icon(mono), self)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.act_region = self.menu.addAction("Выделить область",
                                              lambda: self.capture_region(MENU_CAPTURE_DELAY_MS))
        self.act_full = self.menu.addAction("Весь экран", lambda: self.capture_full(MENU_CAPTURE_DELAY_MS))
        self.menu.addSeparator()
        self.act_replay_save = self.menu.addAction("Сохранить повтор", self.save_replay)
        self.act_replay_toggle = self.menu.addAction("Запись повтора")
        self.act_replay_toggle.setCheckable(True)
        self.act_replay_toggle.setChecked(self.store.data.replay_enabled)
        self.act_replay_toggle.toggled.connect(lambda on: self.store.set("replay_enabled", on))
        self.menu.addSeparator()
        self.act_folder = self.menu.addAction("Открыть папку", self.open_folder)
        self.act_settings = self.menu.addAction("Настройки…", self.open_settings)
        self.act_update = self.menu.addAction("Обновить", lambda: self.updater.install())
        self.act_update.setVisible(False)             # появляется, когда вышла новая версия
        f = self.act_update.font()
        f.setBold(True)
        self.act_update.setFont(f)
        self.act_check_updates = self.menu.addAction("Проверить обновления", lambda: self.updater.check(manual=True))
        self.menu.addSeparator()
        self.act_quit = self.menu.addAction("Выход", self.qapp.quit)
        self._retheme_tray()
        self.tray.setContextMenu(self.menu)
        # Клик по значку открывает настройки (на macOS клик всегда показывает меню)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _retheme_tray(self) -> None:
        c = self.theme.tokens.text
        self.act_region.setIcon(icons.icon("region", c))
        self.act_full.setIcon(icons.icon("monitor", c))
        self.act_folder.setIcon(icons.icon("folder", c))
        self.act_settings.setIcon(icons.icon("settings", c))
        self.act_quit.setIcon(icons.icon("power", c))
        self.act_update.setIcon(icons.icon("download", self.theme.tokens.accent))
        self.act_check_updates.setIcon(icons.icon("refresh", c))
        self.act_replay_save.setIcon(icons.icon("replay", c))
        self._update_menu_shortcuts()

    def _update_menu_shortcuts(self) -> None:
        s = self.store.data
        self.act_region.setText(f"Выделить область\t{label_for(s.hotkey_region)}")
        self.act_full.setText(f"Весь экран\t{label_for(s.hotkey_full)}")
        self.act_replay_save.setText(f"Сохранить повтор ({s.replay_minutes} мин)\t{label_for(s.hotkey_replay)}")
        self.act_replay_save.setEnabled(self.replay.running)

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    def notify(self, text: str, error: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(APP_NAME, text, icon, 3500 if error else 2000)

    # ----------------------------------------------------------------- hotkeys
    def _register_hotkeys(self) -> dict[str, str]:
        s = self.store.data
        errors = self.hotkeys.set_bindings(
            {"full": s.hotkey_full, "region": s.hotkey_region, "replay": s.hotkey_replay})
        self._show_hotkey_errors(errors)
        return errors

    def _show_hotkey_errors(self, errors: dict[str, str]) -> None:
        names = {"full": "весь экран", "region": "выделение области", "replay": "сохранить повтор"}
        text = "; ".join(f"{names[a]}: {e}" for a, e in errors.items() if e)
        if self.settings_window:
            self.settings_window.show_hotkey_error(text)
        elif text:
            self.notify(f"Горячая клавиша не назначена — {text}", error=True)

    def _on_hotkey(self, action: str) -> None:
        if action == "full":
            self.capture_full()
        elif action == "region":
            self.capture_region()
        elif action == "replay":
            self.save_replay()

    def _on_hotkey_recording(self, recording: bool) -> None:
        if recording:
            self.hotkeys.pause()
        else:
            self._show_hotkey_errors(self.hotkeys.resume())

    # ---------------------------------------------------------------- settings
    def _on_setting_changed(self, name: str) -> None:
        if name in ("hotkey_full", "hotkey_region", "hotkey_replay"):
            self._register_hotkeys()
            self._update_menu_shortcuts()
        elif name == "theme":
            self.theme.set_mode(self.store.data.theme)
        elif name.startswith("replay_"):
            if name == "replay_enabled":
                self.act_replay_toggle.blockSignals(True)
                self.act_replay_toggle.setChecked(self.store.data.replay_enabled)
                self.act_replay_toggle.blockSignals(False)
            self._update_menu_shortcuts()
            self._replay_restart.start()

    # ------------------------------------------------------------------ replay
    def _replay_options(self) -> ReplayOptions:
        s = self.store.data
        screens = QGuiApplication.screens()
        idx = s.replay_monitor if 0 <= s.replay_monitor < len(screens) else 0
        scr = screens[idx]
        g, dpr = scr.geometry(), scr.devicePixelRatio()
        rect = QRect(round(g.x() * dpr), round(g.y() * dpr), round(g.width() * dpr), round(g.height() * dpr))
        return ReplayOptions(minutes=s.replay_minutes, fps=s.replay_fps, height=s.replay_height, monitor=idx,
                             screen_rect=rect, system_audio=s.replay_system_audio, mic=s.replay_mic,
                             mic_device=s.replay_mic_device)

    def _apply_replay(self) -> None:
        """(Пере)запускает или останавливает буфер повтора по текущим настройкам."""
        if self.store.data.replay_enabled:
            self.replay.start(self._replay_options())
        else:
            self.replay.stop()

    def _on_replay_running(self, running: bool) -> None:
        # Красная точка на значке — видно, что идёт запись
        self.tray.setIcon(_with_rec_dot(self._tray_icon()) if running else self._tray_icon())
        self.tray.setToolTip(f"{APP_NAME} — идёт запись повтора" if running else APP_NAME)
        self._update_menu_shortcuts()

    def _tray_icon(self) -> QIcon:
        return icons.logo_icon(sys.platform == "darwin")

    # ----------------------------------------------------------------- updates
    def _auto_check_updates(self) -> None:
        s = self.store.data
        if s.check_updates and time.time() - s.last_update_check > 20 * 3600:
            self.store.set("last_update_check", time.time())
            self.updater.check()

    def _on_update_available(self, release) -> None:
        self.act_update.setText(f"Обновить до v{release.version}")
        self.act_update.setVisible(True)
        action = "в меню значка" if can_self_update() else "— откроется страница загрузки"
        self.notify(f"Вышла версия {release.version}. Обновить: «Обновить до v{release.version}» {action}")

    def save_replay(self) -> None:
        if not self.replay.running:
            self.notify("Запись повтора выключена — включите её в настройках", error=True)
            return
        self.replay.save(self.store.data.save_dir)

    def _sync_autostart(self) -> None:
        """Если автозапуск включён — обновляем запись (путь к приложению мог измениться)."""
        if self.store.data.autostart:
            try:
                autostart.set_enabled(True)
            except OSError:
                pass

    def open_settings(self) -> None:
        if self.settings_window is None:
            from .ui.settings_window import SettingsWindow

            self.settings_window = SettingsWindow(self.store, self.theme, self.replay)
            self.settings_window.hotkey_recording.connect(self._on_hotkey_recording)
            self.settings_window.uninstall_done.connect(self.qapp.quit)
            self.settings_window.show_hotkey_error(
                "; ".join(e for e in self._hotkey_errors.values() if e))
        self.settings_window.present()

    def open_folder(self) -> None:
        folder = Path(self.store.data.save_dir)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ----------------------------------------------------------------- capture
    def capture_full(self, delay: int = 0) -> None:
        if self.session:
            return
        QTimer.singleShot(delay, self._do_capture_full)

    def _do_capture_full(self) -> None:
        img = grab_full_desktop(self.store.data.show_cursor)
        if img.isNull():
            self.notify("Не удалось сделать снимок экрана", error=True)
            return
        self._save(img)

    def capture_region(self, delay: int = 0) -> None:
        if self.session:
            return
        QTimer.singleShot(delay, self._do_capture_region)

    def _do_capture_region(self) -> None:
        if self.session:
            return
        shots = grab_screens(self.store.data.show_cursor)
        if not shots:
            self.notify("Не удалось сделать снимок экрана", error=True)
            return
        s = self.store.data
        self.session = CaptureSession(shots, self.theme.tokens, QColor(s.pen_color), s.pen_width, s.palette)
        self.session.palette_changed.connect(lambda pal: self.store.set("palette", list(pal)))
        self.session.copy_requested.connect(self._copy)
        self.session.save_requested.connect(self._save)
        self.session.style_changed.connect(self._remember_style)
        self.session.finished.connect(self._on_session_finished)
        self.session.start()

    def _on_session_finished(self) -> None:
        if self.session:
            self.session.deleteLater()
        self.session = None

    def _remember_style(self, color: QColor, width: int) -> None:
        self.store.set("pen_color", color.name().upper())
        self.store.set("pen_width", width)

    def _copy(self, img: QImage) -> None:
        copy_to_clipboard(img)
        if self.store.data.notify_on_save:
            self.notify("Скопировано в буфер обмена")

    def _save(self, img: QImage) -> None:
        settings = dataclasses.replace(self.store.data)   # снимок настроек для фонового потока
        signals = self._save_signals

        def work() -> None:
            try:
                signals.saved.emit(save_image(img, settings))
            except Exception as exc:
                signals.failed.emit(str(exc))

        threading.Thread(target=work, daemon=False, name="kadr-save").start()

    def _on_saved(self, path) -> None:
        if self.store.data.notify_on_save:
            self.notify(f"Сохранено: {path.name}")

    # --------------------------------------------------------- single instance
    def handle_command(self, cmd: str) -> None:
        if cmd == "region":
            self.capture_region()
        elif cmd == "full":
            self.capture_full()
        elif cmd == "settings":
            self.open_settings()
        elif cmd == "replay":
            self.save_replay()


def _with_rec_dot(icon: QIcon) -> QIcon:
    out = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        px = icon.pixmap(size, size)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = size * 0.42
        p.setPen(QColor("#FFFFFF"))
        p.setBrush(QColor("#FF3B30"))
        p.drawEllipse(round(size - d - 0.5), round(size - d - 0.5), round(d), round(d))
        p.end()
        out.addPixmap(px)
    return out


def _server_name() -> str:
    return f"{APP_ID}-{getpass.getuser()}"


def _send_to_running(cmd: str) -> bool:
    """Если приложение уже запущено — передаём ему команду и выходим."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(cmd.encode())
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def _hide_dock_icon() -> None:
    """macOS: приложение живёт только в строке меню, без иконки в Dock."""
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass


def main() -> int:
    args = sys.argv[1:]
    flags = {"--region": "region", "--full": "full", "--settings": "settings", "--save-replay": "replay"}
    cmd = next((c for f, c in flags.items() if f in args), "")

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)   # закрытие настроек не завершает приложение
    qapp.setStyle("Fusion")                 # одинаковая база на всех ОС, дальше — наш QSS
    qapp.setWindowIcon(icons.logo_icon())

    if _send_to_running(cmd or "settings"):
        return 0

    if sys.platform == "darwin":
        _hide_dock_icon()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("Системный трей недоступен: настройки можно открыть командой `main.py --settings`")

    app = KadrApp(qapp)

    # SIGTERM/Ctrl+C (выключение ПК, kill) → штатный выход: запись повтора остановится,
    # настройки допишутся. Таймер нужен, чтобы Python успевал обрабатывать сигналы,
    # пока крутится цикл событий Qt.
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: qapp.quit())
    _sig_timer = QTimer()
    _sig_timer.start(500)
    _sig_timer.timeout.connect(lambda: None)

    QLocalServer.removeServer(_server_name())  # на случай «зависшего» сокета после сбоя
    server = QLocalServer()
    server.listen(_server_name())

    def on_connection():
        conn = server.nextPendingConnection()
        conn.waitForReadyRead(300)
        app.handle_command(bytes(conn.readAll()).decode(errors="ignore"))
        conn.deleteLater()

    server.newConnection.connect(on_connection)

    if cmd:
        QTimer.singleShot(0, lambda: app.handle_command(cmd))
    elif not app.store.path.exists():
        # Первый запуск — показываем настройки, чтобы было понятно, что приложение работает
        app.store.save()
        QTimer.singleShot(300, app.open_settings)

    return qapp.exec()
