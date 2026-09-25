"""Проверка и установка обновлений через GitHub Releases.

* Раз в сутки (и по кнопке в меню трея) спрашиваем GitHub о последнем релизе.
* Установленная версия (Kadr-Setup.exe) обновляется сама: скачиваем новый
  установщик, сверяем SHA-256 с контрольной суммой, которую публикует GitHub,
  и запускаем его в тихом режиме — он закроет Kadr, обновит файлы и запустит снова.
* Портативная версия и запуск из исходников — открываем страницу релиза.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import __version__
from .uninstall import installer_uninstaller

REPO = "tsarsvo/ScreenApp"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_ASSET = "Kadr-Setup.exe"


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.10.2' → (1, 10, 2). Нечисловой хвост (например, '-beta') отбрасывается."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", text.strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(remote: str, local: str = __version__) -> bool:
    r, l = parse_version(remote), parse_version(local)
    width = max(len(r), len(l))
    return bool(r) and r + (0,) * (width - len(r)) > l + (0,) * (width - len(l))


@dataclass
class Release:
    version: str            # без «v»
    page_url: str
    installer_url: str | None
    installer_sha256: str | None
    notes: str


def parse_release(data: dict) -> Release:
    asset = next((a for a in data.get("assets", []) if a.get("name") == INSTALLER_ASSET), None)
    digest = (asset or {}).get("digest") or ""
    return Release(
        version=str(data.get("tag_name", "")).lstrip("v"),
        page_url=data.get("html_url", f"https://github.com/{REPO}/releases/latest"),
        installer_url=(asset or {}).get("browser_download_url"),
        installer_sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
        notes=data.get("body", "") or "",
    )


def _fetch(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"Kadr/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def can_self_update() -> bool:
    """Автоустановка — только для версии, поставленной установщиком на Windows."""
    return installer_uninstaller() is not None


class Updater(QObject):
    available = Signal(object)        # Release — вышла новая версия
    up_to_date = Signal()
    failed = Signal(str)
    downloading = Signal()
    ready_to_quit = Signal()          # установщик запущен — Kadr должен закрыться

    def __init__(self) -> None:
        super().__init__()
        self.latest: Release | None = None
        self._busy = False

    def check(self, manual: bool = False) -> None:
        """Проверка в фоне. manual=True — сообщить и тогда, когда обновлений нет."""
        if self._busy:
            return
        self._busy = True

        def work() -> None:
            try:
                release = parse_release(json.loads(_fetch(API_LATEST)))
                if is_newer(release.version):
                    self.latest = release
                    self.available.emit(release)
                elif manual:
                    self.up_to_date.emit()
            except Exception as exc:
                if manual:
                    self.failed.emit(f"Не удалось проверить обновления: {exc}")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True, name="kadr-update-check").start()

    def install(self) -> None:
        """Скачать и запустить установщик (или открыть страницу релиза)."""
        rel = self.latest
        if rel is None or self._busy:
            return
        if not can_self_update() or not rel.installer_url:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(rel.page_url))
            return
        self._busy = True
        self.downloading.emit()

        def work() -> None:
            try:
                data = _fetch(rel.installer_url, timeout=300)
                if rel.installer_sha256 and hashlib.sha256(data).hexdigest() != rel.installer_sha256:
                    raise RuntimeError("контрольная сумма не совпала — файл повреждён или подменён")
                path = Path(tempfile.gettempdir()) / f"Kadr-Setup-{rel.version}.exe"
                path.write_bytes(data)
                # Тихая установка: закроет Kadr, обновит файлы и запустит новую версию
                subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                                 creationflags=0x00000008 | 0x00000200 if sys.platform == "win32" else 0,
                                 close_fds=True)
                self.ready_to_quit.emit()
            except Exception as exc:
                self.failed.emit(f"Обновление не установлено: {exc}")
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True, name="kadr-update-download").start()
