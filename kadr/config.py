"""Настройки приложения: dataclass + JSON-файл в каталоге конфигурации пользователя."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Signal

from . import APP_NAME


def config_dir() -> Path:
    """Каталог конфигурации по правилам каждой ОС."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME.lower()


def default_save_dir() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return str(Path(pictures or Path.home()) / APP_NAME)


def _default_hotkeys() -> tuple[str, str]:
    # На macOS нет PrtSc, а Cmd+Shift+3/4 заняты системой.
    if sys.platform == "darwin":
        return "ctrl+shift+1", "ctrl+shift+2"
    return "shift+print_screen", "print_screen"


@dataclass
class Settings:
    hotkey_full: str = _default_hotkeys()[0]
    hotkey_region: str = _default_hotkeys()[1]
    save_dir: str = ""
    image_format: str = "png"          # png | jpg | webp
    quality: int = 90                  # 1..100, используется для jpg/webp
    show_cursor: bool = False
    autostart: bool = False
    notify_on_save: bool = True
    theme: str = "system"              # system | light | dark
    # Последние использованные параметры кисти — чтобы не выбирать каждый раз
    pen_color: str = "#FF3B30"
    pen_width: int = 4

    def __post_init__(self) -> None:
        if not self.save_dir:
            self.save_dir = default_save_dir()
        if self.image_format not in ("png", "jpg", "webp"):
            self.image_format = "png"
        self.quality = max(1, min(100, int(self.quality)))
        self.pen_width = max(1, min(40, int(self.pen_width)))


class SettingsStore(QObject):
    """Хранит Settings, сохраняет на диск и оповещает подписчиков об изменениях."""

    changed = Signal(str)  # имя изменённого поля

    def __init__(self) -> None:
        super().__init__()
        self.path = config_dir() / "settings.json"
        self.data = self._load()

    def _load(self) -> Settings:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            return Settings(**{k: v for k, v in raw.items() if k in known})
        except (OSError, ValueError, TypeError):
            return Settings()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.data), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # атомарная запись

    def set(self, name: str, value) -> None:
        if getattr(self.data, name) == value:
            return
        setattr(self.data, name, value)
        self.save()
        self.changed.emit(name)
