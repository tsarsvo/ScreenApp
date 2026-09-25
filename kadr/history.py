"""История последних скриншотов (меню трея → «Недавние»).

Каждый скопированный или сохранённый снимок кладётся в папку истории (PNG в
фоновом потоке) — поэтому его можно снова скопировать, открыть или закрепить,
даже если он ушёл только в буфер обмена. Хранится не больше MAX_ITEMS снимков.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap

MAX_ITEMS = 12
THUMB = 64


class History(QObject):
    changed = Signal()

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder
        self._lock = threading.Lock()

    def items(self) -> list[Path]:
        """Новые сверху."""
        try:
            return sorted(self.folder.glob("shot_*.png"), reverse=True)[:MAX_ITEMS]
        except OSError:
            return []

    def add(self, image: QImage) -> None:
        img = QImage(image)  # копия для фонового потока

        def work() -> None:
            with self._lock:
                self.folder.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                img.save(str(self.folder / f"shot_{stamp}.png"), "PNG", 80)
                for old in sorted(self.folder.glob("shot_*.png"), reverse=True)[MAX_ITEMS:]:
                    old.unlink(missing_ok=True)
            self.changed.emit()

        threading.Thread(target=work, daemon=True, name="kadr-history").start()

    def clear(self) -> None:
        with self._lock:
            for p in self.folder.glob("shot_*.png"):
                p.unlink(missing_ok=True)
        self.changed.emit()

    @staticmethod
    def label(path: Path) -> str:
        try:
            t = datetime.strptime(path.stem[5:20], "%Y%m%d-%H%M%S")
        except ValueError:
            return path.name
        day = "сегодня" if t.date() == datetime.now().date() else t.strftime("%d.%m")
        return f"{day}, {t.strftime('%H:%M:%S')}"

    @staticmethod
    def thumbnail(path: Path) -> QIcon:
        px = QPixmap(str(path))
        if px.isNull():
            return QIcon()
        return QIcon(px.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
