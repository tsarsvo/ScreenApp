"""Сборка приложения, которое запускается двойным кликом (без консоли и без Python).

    pip install pyinstaller
    python scripts/fetch_ffmpeg.py      # Windows: FFmpeg для записи повтора
    python scripts/build.py

Windows: dist/Kadr/Kadr.exe, портативный dist/Kadr-portable.zip и, если установлен
Inno Setup 6, установщик dist/Kadr-Setup.exe (ярлыки на рабочем столе и в «Пуске»).
macOS: dist/Kadr.app. Linux: dist/Kadr/Kadr.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Консоль Windows / CI часто в cp1252 — без этого print() с кириллицей падает
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from kadr import APP_NAME, __version__  # noqa: E402
from kadr.icons import LOGO_SVG, logo_image  # noqa: E402

DIST = ROOT / "dist"


def make_icons() -> Path:
    global _APP
    _APP = QGuiApplication.instance() or QGuiApplication([])  # нужен для рендера SVG
    res = ROOT / "kadr" / "resources"
    res.mkdir(exist_ok=True)
    (res / "logo.svg").write_text(LOGO_SVG, encoding="utf-8")
    logo_image(1024).save(str(res / "logo.png"))
    img = Image.open(res / "logo.png")
    img.save(res / "logo.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        img.save(res / "logo.icns")
    return res


def find_iscc() -> str | None:
    """Компилятор Inno Setup: в PATH или в стандартных папках установки."""
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
        if base and (p := Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return str(p)
    return None


def main() -> None:
    res = make_icons()
    icon = res / ("logo.icns" if sys.platform == "darwin" else "logo.ico")
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "main.py"),
        "--name", APP_NAME, "--windowed", "--noconfirm", "--clean",
        "--icon", str(icon),
        # onedir, а не onefile: запускается мгновенно, не распаковывая ~100 МБ FFmpeg при каждом старте
        "--onedir",
        "--hidden-import", "pynput.keyboard._xorg",
        "--hidden-import", "pynput.keyboard._darwin",
        "--hidden-import", "pynput.keyboard._win32",
        "--add-data", f"{res / 'logo.ico'}{sep}kadr/resources",
    ]
    if sys.platform == "win32":
        cmd += ["--hidden-import", "pyaudiowpatch"]
        ffmpeg = ROOT / "kadr" / "bin" / "ffmpeg.exe"
        if ffmpeg.exists():
            cmd += ["--add-binary", f"{ffmpeg}{sep}kadr/bin"]
            lic = ffmpeg.with_name("FFMPEG-LICENSE.txt")
            if lic.exists():
                cmd += ["--add-data", f"{lic}{sep}kadr/bin"]
        else:
            print("ВНИМАНИЕ: kadr/bin/ffmpeg.exe нет — запись повтора в сборке работать не будет. "
                  "Запустите: python scripts/fetch_ffmpeg.py")
    if sys.platform == "darwin":
        cmd += ["--osx-bundle-identifier", "app.kadr.screenshot"]
    subprocess.run(cmd, check=True, cwd=ROOT)

    if sys.platform == "win32":
        portable = shutil.make_archive(str(DIST / f"{APP_NAME}-portable"), "zip", DIST, APP_NAME)
        print(f"Портативная версия: {portable}")
        iscc = find_iscc()
        if iscc:
            subprocess.run([iscc, f"/DAppVersion={__version__}", str(ROOT / "installer" / "kadr.iss")],
                           check=True, cwd=ROOT)
            print(f"Установщик: {DIST / 'Kadr-Setup.exe'}")
        else:
            print("Inno Setup 6 не найден — установщик не собран (https://jrsoftware.org/isdl.php)")
    print(f"Готово: {DIST}")


if __name__ == "__main__":
    main()
