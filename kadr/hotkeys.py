"""Глобальные горячие клавиши.

* Windows — нативный RegisterHotKey + WM_HOTKEY через QAbstractNativeEventFilter.
  Работает без хуков, не требует прав и «съедает» сочетание (оно не уйдёт в другие программы).
* macOS / Linux (X11) — слушатель клавиатуры pynput в фоновом потоке,
  событие передаётся в GUI-поток через Qt-сигнал (queued connection).

Сочетание хранится строкой вида "ctrl+shift+print_screen".
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent

MOD_ORDER = ("ctrl", "alt", "shift", "cmd")

# name -> (Qt key, Windows VK, подпись)
_SPECIAL: dict[str, tuple[int, int, str]] = {
    "print_screen": (Qt.Key.Key_Print, 0x2C, "PrtSc"),
    "space": (Qt.Key.Key_Space, 0x20, "Space"),
    "insert": (Qt.Key.Key_Insert, 0x2D, "Insert"),
    "delete": (Qt.Key.Key_Delete, 0x2E, "Delete"),
    "home": (Qt.Key.Key_Home, 0x24, "Home"),
    "end": (Qt.Key.Key_End, 0x23, "End"),
    "page_up": (Qt.Key.Key_PageUp, 0x21, "PgUp"),
    "page_down": (Qt.Key.Key_PageDown, 0x22, "PgDn"),
    "up": (Qt.Key.Key_Up, 0x26, "↑"),
    "down": (Qt.Key.Key_Down, 0x28, "↓"),
    "left": (Qt.Key.Key_Left, 0x25, "←"),
    "right": (Qt.Key.Key_Right, 0x27, "→"),
    "pause": (Qt.Key.Key_Pause, 0x13, "Pause"),
    "scroll_lock": (Qt.Key.Key_ScrollLock, 0x91, "ScrLk"),
}
for _n in range(1, 25):
    _SPECIAL[f"f{_n}"] = (int(Qt.Key.Key_F1) + _n - 1, 0x70 + _n - 1, f"F{_n}")

# Клавиши, которые можно назначить без модификатора
_STANDALONE = {"print_screen", "pause", "scroll_lock", *(f"f{n}" for n in range(1, 25))}

# macOS virtual key codes (kVK_ANSI_*) — чтобы сочетание работало при любой раскладке
_MAC_VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
    "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21,
    "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
    "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
}
_MAC_VK_REV = {v: k for k, v in _MAC_VK.items()}


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset[str]
    key: str  # 'a'..'z', '0'..'9' или имя из _SPECIAL

    # --- сериализация -----------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> "Hotkey | None":
        parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
        if not parts:
            return None
        *mods, key = parts
        if any(m not in MOD_ORDER for m in mods):
            return None
        if not (len(key) == 1 and key.isascii() and key.isalnum()) and key not in _SPECIAL:
            return None
        return cls(frozenset(mods), key)

    def serialize(self) -> str:
        return "+".join([m for m in MOD_ORDER if m in self.mods] + [self.key])

    def label(self) -> str:
        names = {"ctrl": "Ctrl", "alt": "Option" if sys.platform == "darwin" else "Alt",
                 "shift": "Shift", "cmd": "Cmd" if sys.platform == "darwin" else "Win"}
        key = _SPECIAL[self.key][2] if self.key in _SPECIAL else self.key.upper()
        return " + ".join([names[m] for m in MOD_ORDER if m in self.mods] + [key])

    # --- платформенные коды ----------------------------------------------
    def win_vk(self) -> int:
        if self.key in _SPECIAL:
            return _SPECIAL[self.key][1]
        return ord(self.key.upper())

    def native_vk(self) -> int | None:
        """Код клавиши в терминах pynput на текущей ОС (для сравнения независимо от раскладки)."""
        if self.key in _SPECIAL:
            return None
        if sys.platform == "win32":
            return ord(self.key.upper())
        if sys.platform == "darwin":
            return _MAC_VK.get(self.key)
        return ord(self.key)  # X11 keysym латинских букв/цифр совпадает с ASCII


def label_for(text: str) -> str:
    hk = Hotkey.parse(text)
    return hk.label() if hk else "—"


def hotkey_from_event(event: QKeyEvent) -> "Hotkey | None | str":
    """Преобразует нажатие в Qt в Hotkey. Возвращает строку-ошибку, если сочетание не подходит."""
    qk = event.key()
    if qk in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
              Qt.Key.Key_AltGr, Qt.Key.Key_unknown):
        return None  # ждём основную клавишу

    m = event.modifiers()
    mods: set[str] = set()
    if sys.platform == "darwin":
        # В Qt на macOS ControlModifier — это Cmd, а MetaModifier — физический Control
        if m & Qt.KeyboardModifier.ControlModifier:
            mods.add("cmd")
        if m & Qt.KeyboardModifier.MetaModifier:
            mods.add("ctrl")
    else:
        if m & Qt.KeyboardModifier.ControlModifier:
            mods.add("ctrl")
        if m & Qt.KeyboardModifier.MetaModifier:
            mods.add("cmd")
    if m & Qt.KeyboardModifier.AltModifier:
        mods.add("alt")
    if m & Qt.KeyboardModifier.ShiftModifier:
        mods.add("shift")

    key = None
    if Qt.Key.Key_A <= qk <= Qt.Key.Key_Z or Qt.Key.Key_0 <= qk <= Qt.Key.Key_9:
        key = chr(qk).lower()
    else:
        for name, (qt_key, _vk, _lbl) in _SPECIAL.items():
            if qk == qt_key:
                key = name
                break
    if key is None:
        # Нелатинская раскладка: восстанавливаем букву по физической клавише
        vk = event.nativeVirtualKey()
        if sys.platform == "win32" and (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39):
            key = chr(vk).lower()
        elif sys.platform == "darwin" and vk in _MAC_VK_REV:
            key = _MAC_VK_REV[vk]
    if key is None:
        return "Эту клавишу нельзя назначить"
    if not mods and key not in _STANDALONE:
        return "Добавьте Ctrl, Alt, Shift или Win/Cmd"
    return Hotkey(frozenset(mods), key)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
class _WinBackend(QAbstractNativeEventFilter):
    """RegisterHotKey(NULL, ...) шлёт WM_HOTKEY в очередь GUI-потока; ловим его фильтром Qt."""

    MOD = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "cmd": 0x8}
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312

    def __init__(self, on_fire) -> None:
        super().__init__()
        import ctypes
        from ctypes import wintypes

        self._user32 = ctypes.windll.user32
        self._MSG = wintypes.MSG
        self._on_fire = on_fire
        self._ids: dict[int, str] = {}
        QCoreApplication.instance().installNativeEventFilter(self)

    def register(self, action: str, hk: Hotkey) -> str | None:
        hid = len(self._ids) + 1
        mods = sum(self.MOD[m] for m in hk.mods) | self.MOD_NOREPEAT
        if not self._user32.RegisterHotKey(None, hid, mods, hk.win_vk()):
            return "Сочетание уже занято другой программой"
        self._ids[hid] = action
        return None

    def unregister_all(self) -> None:
        for hid in self._ids:
            self._user32.UnregisterHotKey(None, hid)
        self._ids.clear()

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = self._MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam in self._ids:
                self._on_fire(self._ids[msg.wParam])
                return True, 0
        return False, 0


class _PynputBackend:
    """Сам сопоставляет нажатия с сочетаниями: так надёжнее, чем GlobalHotKeys
    (учитываем физический код клавиши и игнорируем автоповтор)."""

    _MOD_NAMES = {
        "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
        "shift": "shift", "shift_l": "shift", "shift_r": "shift",
        "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
        "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
    }

    def __init__(self, on_fire) -> None:
        from pynput import keyboard

        self._kb = keyboard
        self._on_fire = on_fire
        self._bindings: dict[str, Hotkey] = {}
        self._mods: set[str] = set()
        self._down: set = set()
        self.paused = False
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.daemon = True
        self._listener.start()

    def register(self, action: str, hk: Hotkey) -> str | None:
        self._bindings[action] = hk
        return None

    def unregister_all(self) -> None:
        self._bindings.clear()

    def _ident(self, key):
        if isinstance(key, self._kb.Key):
            return ("key", key.name)
        return ("code", getattr(key, "vk", None), (getattr(key, "char", None) or "").lower())

    def _matches(self, hk: Hotkey, key) -> bool:
        if hk.key in _SPECIAL:
            if isinstance(key, self._kb.Key):
                return key.name == hk.key
            special = getattr(self._kb.Key, hk.key, None)
            vk = getattr(getattr(special, "value", None), "vk", None)
            return vk is not None and getattr(key, "vk", None) == vk
        if isinstance(key, self._kb.Key):
            return False
        char = (getattr(key, "char", None) or "").lower()
        return char == hk.key or (hk.native_vk() is not None and getattr(key, "vk", None) == hk.native_vk())

    def _press(self, key) -> None:
        name = key.name if isinstance(key, self._kb.Key) else None
        if name in self._MOD_NAMES:
            self._mods.add(self._MOD_NAMES[name])
            return
        ident = self._ident(key)
        if ident in self._down:  # автоповтор при удержании
            return
        self._down.add(ident)
        if self.paused:
            return
        for action, hk in self._bindings.items():
            if hk.mods == self._mods and self._matches(hk, key):
                self._on_fire(action)  # вызывается из потока pynput -> см. HotkeyManager
                break

    def _release(self, key) -> None:
        name = key.name if isinstance(key, self._kb.Key) else None
        if name in self._MOD_NAMES:
            self._mods.discard(self._MOD_NAMES[name])
        else:
            self._down.discard(self._ident(key))


class HotkeyManager(QObject):
    """Единый интерфейс поверх платформенных backend'ов."""

    triggered = Signal(str)  # имя действия: "full" | "region"

    def __init__(self) -> None:
        super().__init__()
        self._bindings: dict[str, Hotkey] = {}
        self.error: str | None = None
        # emit из чужого потока безопасен: Qt доставит сигнал в GUI-поток (QueuedConnection)
        fire = self.triggered.emit
        try:
            self._backend = _WinBackend(fire) if sys.platform == "win32" else _PynputBackend(fire)
        except Exception as exc:  # нет X11, нет прав Accessibility и т.п.
            self._backend = None
            self.error = f"Глобальные горячие клавиши недоступны: {exc}"

    def set_bindings(self, bindings: dict[str, str]) -> dict[str, str]:
        """Перерегистрирует все сочетания. Возвращает {действие: ошибка}."""
        self._bindings = {a: hk for a, s in bindings.items() if (hk := Hotkey.parse(s))}
        return self._apply()

    def _apply(self) -> dict[str, str]:
        if self._backend is None:
            return {a: self.error or "" for a in self._bindings}
        self._backend.unregister_all()
        errors = {}
        for action, hk in self._bindings.items():
            if err := self._backend.register(action, hk):
                errors[action] = err
        return errors

    def pause(self) -> None:
        """На время записи нового сочетания в настройках глобальные хоткеи отключаются."""
        if isinstance(self._backend, _PynputBackend):
            self._backend.paused = True
        elif self._backend is not None:
            self._backend.unregister_all()

    def resume(self) -> dict[str, str]:
        if isinstance(self._backend, _PynputBackend):
            self._backend.paused = False
            return {}
        return self._apply()
