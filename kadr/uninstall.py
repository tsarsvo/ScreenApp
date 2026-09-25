"""Удаление приложения из окна настроек.

* Установлено через Kadr-Setup.exe → запускаем штатный деинсталлятор (unins000.exe):
  он удалит программу, ярлыки и запись в «Приложения и возможности».
* Портативная версия / запуск из исходников → удаляем всё, что приложение создало
  вне своей папки, а саму папку пользователь удаляет вручную (удалять запущенный
  .exe и произвольную папку автоматически небезопасно).

В обоих случаях удаляются настройки, автозапуск и временные файлы записи повтора.
Скриншоты и записи в папке сохранения НЕ трогаем.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from . import APP_NAME, autostart
from .config import config_dir


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def installer_uninstaller() -> Path | None:
    """unins000.exe рядом с Kadr.exe — признак установки через Kadr-Setup.exe."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    found = sorted(app_dir().glob("unins*.exe"))
    return found[0] if found else None


def remove_user_data() -> None:
    try:
        autostart.set_enabled(False)
    except OSError:
        pass
    shutil.rmtree(config_dir(), ignore_errors=True)
    shutil.rmtree(Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}-replay", ignore_errors=True)


def remove_shortcuts() -> None:
    """Ярлыки, которые создаёт install_windows.bat."""
    for loc in (QStandardPaths.StandardLocation.DesktopLocation,
                QStandardPaths.StandardLocation.ApplicationsLocation):
        folder = QStandardPaths.writableLocation(loc)
        if folder:
            (Path(folder) / f"{APP_NAME}.lnk").unlink(missing_ok=True)


def uninstall() -> str:
    """Возвращает режим: "installer" — запущен деинсталлятор, иначе "manual"."""
    remove_user_data()
    unins = installer_uninstaller()
    if unins:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(unins), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                         creationflags=flags, close_fds=True)
        return "installer"
    remove_shortcuts()
    return "manual"
