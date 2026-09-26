"""Перезапуск Kadr с правами администратора (Windows).

Диспетчер задач и другие программы, запущенные «от администратора», стоят выше
обычных программ: пока такое окно активно, Windows не передаёт обычной программе
нажатия горячих клавиш, и снять его по PrtSc нельзя. Kadr, запущенный с правами
администратора, таких ограничений не имеет.

Режим включается тумблером в настройках и сохраняется: при каждом запуске Kadr сам
перезапускается с правами администратора через обычный запрос Windows «Разрешить
этому приложению вносить изменения…». В системе ничего не прописывается — выключили
тумблер, и со следующего запуска Kadr работает как обычная программа.
"""
from __future__ import annotations

import sys

from .autostart import launch_command

RESTARTED_FLAG = "--restarted"   # новая копия ждёт, пока старая освободит место; повторно не повышает права


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


def should_elevate_at_start(args: list[str], wanted: bool) -> bool:
    """Нужно ли при запуске перезапуститься с правами администратора.
    Копия, уже запущенная так (флаг --restarted), не пытается снова — иначе при отказе
    в правах (или без прав администратора у пользователя) запуск шёл бы по кругу."""
    return supported() and wanted and RESTARTED_FLAG not in args and not is_elevated()


def relaunch_as_admin(extra_args: list[str] | tuple = ()) -> bool:
    """Запускает новую копию Kadr с правами администратора (с запросом Windows).
    extra_args — команды для новой копии (например, --region). True — копия запущена,
    текущую нужно закрыть; False — пользователь отказал."""
    if not supported():
        return False
    import ctypes

    cmd = [*launch_command(), *extra_args, RESTARTED_FLAG]
    params = " ".join(_quote(a) for a in cmd[1:])
    # SW_SHOWNORMAL = 1; код больше 32 — успех (ShellExecute), иначе ошибка или отказ
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, None, 1)
    return rc > 32
