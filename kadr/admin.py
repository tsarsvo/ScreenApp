"""Перезапуск Kadr с правами администратора (Windows).

Диспетчер задач и другие программы, запущенные «от администратора», стоят выше
обычных программ: пока такое окно активно, Windows не передаёт обычной программе
нажатия горячих клавиш, и снять его по PrtSc нельзя. Kadr, запущенный с правами
администратора, таких ограничений не имеет.

Перезапуск разовый: Windows показывает обычный запрос «Разрешить этому приложению
вносить изменения…», в системе ничего не прописывается, и при следующем обычном
запуске Kadr снова работает без повышенных прав.
"""
from __future__ import annotations

import sys

from .autostart import launch_command

RESTARTED_FLAG = "--restarted"   # новая копия ждёт, пока старая освободит место


def supported() -> bool:
    return sys.platform == "win32"


def is_elevated() -> bool:
    if not supported():
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _quote(arg: str) -> str:
    return '"' + arg.replace('"', '\\"') + '"'


def relaunch_as_admin() -> bool:
    """Запускает новую копию Kadr с правами администратора (с запросом Windows).
    True — копия запущена, текущую нужно закрыть; False — пользователь отказал."""
    if not supported():
        return False
    import ctypes

    cmd = [*launch_command(), RESTARTED_FLAG]
    params = " ".join(_quote(a) for a in cmd[1:])
    # SW_SHOWNORMAL = 1; код больше 32 — успех (ShellExecute), иначе ошибка или отказ
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, None, 1)
    return rc > 32
