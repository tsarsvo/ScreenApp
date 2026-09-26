"""Автозапуск при входе в систему — реально прописывает приложение в автозагрузку ОС.

* Windows — значение в HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
* macOS   — LaunchAgent ~/Library/LaunchAgents/<id>.plist (RunAtLoad)
* Linux   — XDG Autostart ~/.config/autostart/kadr.desktop (GNOME, KDE, XFCE, Cinnamon…)
"""
from __future__ import annotations

import contextlib
import os
import plistlib
import sys
from pathlib import Path

from . import APP_ID, APP_NAME

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> list[str]:
    """Команда запуска текущей копии приложения."""
    if getattr(sys, "frozen", False):  # собрано PyInstaller / Nuitka
        return [sys.executable]
    main_py = str(Path(__file__).resolve().parent.parent / "main.py")
    python = Path(sys.executable)
    if sys.platform == "win32":
        # pythonw.exe — без чёрного окна консоли
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    return [str(python), main_py]


# --------------------------------------------------------------------- Windows
def _win_set(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = " ".join(f'"{a}"' for a in launch_command())
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, APP_NAME)


def _win_get() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


# ----------------------------------------------------------------------- macOS
def _mac_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def _mac_set(enabled: bool) -> None:
    path = _mac_plist()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            plistlib.dump({
                "Label": APP_ID,
                "ProgramArguments": launch_command(),
                "RunAtLoad": True,
                "ProcessType": "Interactive",
            }, f)
    else:
        path.unlink(missing_ok=True)


# ----------------------------------------------------------------------- Linux
def _linux_desktop() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{APP_NAME.lower()}.desktop"


def _linux_set(enabled: bool) -> None:
    path = _linux_desktop()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        exec_line = " ".join('"' + a.replace('"', '\\"') + '"' for a in launch_command())
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            "Comment=Screenshot tool\n"
            f"Exec={exec_line}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "X-GNOME-Autostart-Delay=2\n",
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------- public
def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_get()
    if sys.platform == "darwin":
        return _mac_plist().exists()
    return _linux_desktop().exists()


def set_enabled(enabled: bool) -> None:
    """Включает/выключает автозапуск. Бросает OSError при неудаче."""
    if sys.platform == "win32":
        _win_set(enabled)
    elif sys.platform == "darwin":
        _mac_set(enabled)
    else:
        _linux_set(enabled)
