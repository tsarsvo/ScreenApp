"""Контроллер приложения: трей, одна копия, горячие клавиши, запуск захвата."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME, APP_ID, autostart, icons
from .capture import grab_full_desktop, grab_screens
from .config import SettingsStore
from .hotkeys import HotkeyManager, label_for
from .overlay import CaptureSession
from .saver import copy_to_clipboard, save_image
from .theme import ThemeManager

# Задержка перед снимком: даём ОС убрать меню трея / отпустить клавиши
CAPTURE_DELAY_MS = 120


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

        self._build_tray()
        self._hotkey_errors = self._register_hotkeys()
        self._sync_autostart()
        self.theme.changed.connect(self._retheme_tray)

        if self.hotkeys.error:
            self.notify(self.hotkeys.error, error=True)

    # -------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        mono = sys.platform == "darwin"  # на macOS — template-иконка под цвет строки меню
        self.tray = QSystemTrayIcon(icons.logo_icon(mono), self)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.act_region = self.menu.addAction("Выделить область", lambda: self.capture_region())
        self.act_full = self.menu.addAction("Весь экран", lambda: self.capture_full())
        self.menu.addSeparator()
        self.act_folder = self.menu.addAction("Открыть папку", self.open_folder)
        self.act_settings = self.menu.addAction("Настройки…", self.open_settings)
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
        self._update_menu_shortcuts()

    def _update_menu_shortcuts(self) -> None:
        s = self.store.data
        self.act_region.setText(f"Выделить область\t{label_for(s.hotkey_region)}")
        self.act_full.setText(f"Весь экран\t{label_for(s.hotkey_full)}")

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_settings()

    def notify(self, text: str, error: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(APP_NAME, text, icon, 3500 if error else 2000)

    # ----------------------------------------------------------------- hotkeys
    def _register_hotkeys(self) -> dict[str, str]:
        s = self.store.data
        errors = self.hotkeys.set_bindings({"full": s.hotkey_full, "region": s.hotkey_region})
        self._show_hotkey_errors(errors)
        return errors

    def _show_hotkey_errors(self, errors: dict[str, str]) -> None:
        names = {"full": "весь экран", "region": "выделение области"}
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

    def _on_hotkey_recording(self, recording: bool) -> None:
        if recording:
            self.hotkeys.pause()
        else:
            self._show_hotkey_errors(self.hotkeys.resume())

    # ---------------------------------------------------------------- settings
    def _on_setting_changed(self, name: str) -> None:
        if name in ("hotkey_full", "hotkey_region"):
            self._register_hotkeys()
            self._update_menu_shortcuts()
        elif name == "theme":
            self.theme.set_mode(self.store.data.theme)

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

            self.settings_window = SettingsWindow(self.store, self.theme)
            self.settings_window.hotkey_recording.connect(self._on_hotkey_recording)
            self.settings_window.show_hotkey_error(
                "; ".join(e for e in self._hotkey_errors.values() if e))
        self.settings_window.present()

    def open_folder(self) -> None:
        folder = Path(self.store.data.save_dir)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ----------------------------------------------------------------- capture
    def capture_full(self, delay: int = CAPTURE_DELAY_MS) -> None:
        if self.session:
            return
        QTimer.singleShot(delay, self._do_capture_full)

    def _do_capture_full(self) -> None:
        img = grab_full_desktop(self.store.data.show_cursor)
        if img.isNull():
            self.notify("Не удалось сделать снимок экрана", error=True)
            return
        self._save(img)

    def capture_region(self, delay: int = CAPTURE_DELAY_MS) -> None:
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
        self.session = CaptureSession(shots, self.theme.tokens, QColor(s.pen_color), s.pen_width)
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
        try:
            path = save_image(img, self.store.data)
        except Exception as exc:
            self.notify(f"Ошибка сохранения: {exc}", error=True)
            return
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
    cmd = "region" if "--region" in args else "full" if "--full" in args else "settings" if "--settings" in args else ""

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
