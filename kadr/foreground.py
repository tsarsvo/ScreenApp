"""Активное окно до и после выделения области (Windows).

* Оверлей выделения забирает фокус. Когда он закрывается, Windows не всегда отдаёт фокус
  обратно окну, которое было активным до снимка, — например, игре. Игра остаётся без
  фокуса, но под курсором: она прячет курсор, Windows снова показывает его, и курсор
  мигает, пока игру не перезапустишь. Поэтому активное окно запоминается до снимка и
  после него явно активируется снова.
* Некоторые окна (например, «Параметры» Windows) не отдают фокус по обычной просьбе —
  оверлей тогда появлялся без клавиатуры. bring_to_front() активирует его тем же
  способом, что и Alt+Tab: на время присоединяет ввод к потоку активного окна.
"""
from __future__ import annotations

import sys


def _user32():
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    for fn in (u.SetForegroundWindow, u.BringWindowToTop, u.IsWindow, u.IsWindowVisible, u.IsIconic):
        fn.argtypes = [wintypes.HWND]
    return u


def current() -> int:
    """Активное сейчас окно (0 — нет или не Windows)."""
    if sys.platform != "win32":
        return 0
    try:
        return _user32().GetForegroundWindow() or 0
    except Exception:
        return 0


def restore(hwnd: int) -> None:
    """Вернуть фокус окну, которое было активным до снимка."""
    if not hwnd or sys.platform != "win32":
        return
    try:
        u = _user32()
        if u.IsWindow(hwnd) and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd) and u.GetForegroundWindow() != hwnd:
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def bring_to_front(hwnd: int) -> None:
    """Сделать окно активным, даже если активное окно не отдаёт фокус по обычной просьбе."""
    if not hwnd or sys.platform != "win32":
        return
    try:
        import ctypes

        u = _user32()
        fg = u.GetForegroundWindow()
        if not fg or fg == hwnd:
            return
        me = ctypes.windll.kernel32.GetCurrentThreadId()
        other = u.GetWindowThreadProcessId(fg, None)
        attached = bool(other) and other != me and bool(u.AttachThreadInput(me, other, True))
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(me, other, False)
    except Exception:
        pass
