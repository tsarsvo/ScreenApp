"""Окна «поверх оверлея» на время выделения (Windows).

Диспетчер задач с включённым «Поверх остальных окон» живёт в особом слое Windows —
выше всех обычных окон «поверх всех», в том числе оверлея Kadr. Выделение области
тогда оказывалось под ним. Снимок экрана к этому моменту уже сделан (Диспетчер в нём
есть), поэтому на время выделения окно просто прячется и сразу возвращается.

Спрятать окно программы, запущенной от администратора, может только Kadr с правами
администратора; без них Windows запрос игнорирует — ничего не ломается.
"""
from __future__ import annotations

import sys

# Классы окон, которые Windows держит выше обычных «поверх всех»
_CLASSES = ("TaskManagerWindow",)

_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_SW_HIDE = 0
_SW_SHOWNA = 8          # показать, не забирая фокус


def hide_over_overlay() -> list[int]:
    """Прячет такие окна; возвращает список спрятанных, чтобы потом вернуть их."""
    if sys.platform != "win32":
        return []
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hidden = []
        for cls in _CLASSES:
            hwnd = user32.FindWindowW(cls, None)
            if not hwnd or not user32.IsWindowVisible(hwnd):
                continue
            if not user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST:
                continue            # обычное окно — оверлей и так будет выше
            user32.ShowWindow(hwnd, _SW_HIDE)
            if not user32.IsWindowVisible(hwnd):
                hidden.append(hwnd)
        return hidden
    except Exception:
        return []


def restore(hidden: list[int]) -> None:
    if not hidden or sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        for hwnd in hidden:
            if user32.IsWindow(hwnd):
                user32.ShowWindow(hwnd, _SW_SHOWNA)
    except Exception:
        pass
