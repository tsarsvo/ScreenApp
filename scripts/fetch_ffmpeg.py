"""Скачивает FFmpeg для Windows (LGPL-сборка BtbN) в kadr/bin/ffmpeg.exe.

    python scripts/fetch_ffmpeg.py            # последняя стабильная ветка
    python scripts/fetch_ffmpeg.py --url URL  # конкретный архив

LGPL-сборка выбрана специально: её можно распространять вместе с приложением
(FFmpeg — отдельная программа, текст лицензии кладётся рядом).
Контрольная сумма архива сверяется с checksums.sha256 из того же релиза.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
DEST = Path(__file__).resolve().parent.parent / "kadr" / "bin"


# Консоль Windows / CI часто в cp1252 — без этого print() с кириллицей падает
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def fetch(url: str) -> bytes:
    if not url.startswith("https://"):
        raise SystemExit(f"Загрузка только по https: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "kadr-build"})  # noqa: S310 — https проверен
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
        return r.read()


def pick_asset(checksums: str) -> tuple[str, str]:
    """Самая свежая стабильная ветка вида ffmpeg-n7.1-latest-win64-lgpl-7.1.zip."""
    entries = {}
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) == 2:
            entries[parts[1].lstrip("*")] = parts[0]
    stable = []
    for name in entries:
        m = re.fullmatch(r"ffmpeg-n(\d+)\.(\d+)-latest-win64-lgpl-\d+\.\d+\.zip", name)
        if m:
            stable.append(((int(m[1]), int(m[2])), name))
    if stable:
        name = max(stable)[1]
    elif "ffmpeg-master-latest-win64-lgpl.zip" in entries:
        name = "ffmpeg-master-latest-win64-lgpl.zip"
    else:
        raise SystemExit("В checksums.sha256 не найдена win64-lgpl сборка — укажите --url")
    return name, entries[name]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="прямая ссылка на zip-архив FFmpeg (без проверки суммы)")
    args = ap.parse_args()

    if args.url:
        url, expected = args.url, None
    else:
        name, expected = pick_asset(fetch(RELEASE + "checksums.sha256").decode())
        url = RELEASE + name
    print(f"Скачиваю {url}")
    data = fetch(url)
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit("Контрольная сумма не совпала — архив повреждён или подменён")

    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        exe = next(n for n in z.namelist() if n.endswith("/bin/ffmpeg.exe"))
        (DEST / "ffmpeg.exe").write_bytes(z.read(exe))
        lic = next((n for n in z.namelist() if n.endswith("LICENSE.txt")), None)
        if lic:
            (DEST / "FFMPEG-LICENSE.txt").write_bytes(z.read(lic))
    size = (DEST / "ffmpeg.exe").stat().st_size / 1e6
    print(f"Готово: {DEST / 'ffmpeg.exe'} ({size:.0f} МБ)")


if __name__ == "__main__":
    sys.exit(main())
