"""Сборка приложения, которое запускается двойным кликом (без консоли и без Python).

    pip install pyinstaller
    python scripts/fetch_ffmpeg.py      # Windows: FFmpeg для записи повтора
    python scripts/build.py

Windows: dist/Kadr/Kadr.exe, портативный dist/Kadr-portable.zip и, если установлен
Inno Setup 6, установщик dist/Kadr-Setup.exe (ярлыки на рабочем столе и в «Пуске»).
macOS: dist/Kadr.app. Linux: dist/Kadr/Kadr.
"""
import os
import re
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

from kadr import APP_NAME, DEFAULT_VERSION  # noqa: E402
from kadr.icons import LOGO_SVG, logo_image  # noqa: E402

DIST = ROOT / "dist"


def _ensure_qt() -> None:
    global _APP
    _APP = QGuiApplication.instance() or QGuiApplication([])  # нужен для рендера SVG и картинок


def make_icons() -> Path:
    _ensure_qt()
    res = ROOT / "kadr" / "resources"
    res.mkdir(exist_ok=True)
    (res / "logo.svg").write_text(LOGO_SVG, encoding="utf-8")
    logo_image(1024).save(str(res / "logo.png"))
    img = Image.open(res / "logo.png")
    img.save(res / "logo.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    if sys.platform == "darwin":
        img.save(res / "logo.icns")
    return res


def make_installer_images() -> None:
    """Картинки мастера установки Inno Setup: боковой баннер и логотип в шапке.
    Несколько размеров — установщик сам берёт подходящий под масштаб экрана."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter

    _ensure_qt()
    out = ROOT / "installer" / "generated"
    out.mkdir(parents=True, exist_ok=True)

    def save_bmp(img: QImage, path: Path) -> None:
        tmp = path.with_suffix(".png")
        img.save(str(tmp))
        Image.open(tmp).convert("RGB").save(path, "BMP")   # Inno Setup ждёт 24-битный BMP
        tmp.unlink()

    for k in (1.0, 1.5, 2.0):
        w, h = round(164 * k), round(314 * k)
        img = QImage(w, h, QImage.Format.Format_RGB32)
        p = QPainter(img)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        g = QLinearGradient(0, 0, w * 0.4, h)
        g.setColorAt(0, QColor("#4C7DFF"))
        g.setColorAt(1, QColor("#7A5CFF"))
        p.fillRect(img.rect(), g)
        # декоративные «уголки рамки» на фоне
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawEllipse(QRectF(-w * 0.5, h * 0.62, w * 1.3, w * 1.3))
        logo = logo_image(round(84 * k))
        p.drawImage(round((w - logo.width()) / 2), round(h * 0.2), logo)
        p.setPen(QColor("#FFFFFF"))
        f = QFont()
        f.setPixelSize(round(30 * k))
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, h * 0.2 + 100 * k, w, 40 * k), Qt.AlignmentFlag.AlignCenter, APP_NAME)
        f.setPixelSize(round(11 * k))
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 215))
        p.drawText(QRectF(10 * k, h * 0.2 + 140 * k, w - 20 * k, 40 * k),
                   Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, "Скриншоты и повтор экрана")
        p.end()
        save_bmp(img, out / f"wizard-{w}.bmp")

    for size in (55, 83, 110):
        img = QImage(size, size, QImage.Format.Format_RGB32)
        img.fill(QColor("#FFFFFF"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        logo = logo_image(round(size * 0.86))
        p.drawImage(round((size - logo.width()) / 2), round((size - logo.height()) / 2), logo)
        p.end()
        save_bmp(img, out / f"small-{size}.bmp")


def resolve_version() -> str:
    """Версия сборки: тег релиза (v1.2.3) в GitHub Actions, иначе KADR_VERSION или версия из кода.
    Записывается в kadr/_version.py — её видят окно настроек и установщик."""
    ref = os.environ.get("GITHUB_REF_NAME", "")
    version = os.environ.get("KADR_VERSION") or (ref[1:] if re.fullmatch(r"v\d+(\.\d+)*", ref) else "")
    path = ROOT / "kadr" / "_version.py"
    if version:
        path.write_text(f'__version__ = "{version}"\n', encoding="utf-8")
        return version
    path.unlink(missing_ok=True)
    return DEFAULT_VERSION


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


# Что Kadr не использует, но PyInstaller подтягивает вместе с Qt.
# Каждый пункт проверен: сквозной прогон Kadr.exe в CI (скриншот, WEBP, запись повтора)
# выполняется уже на «очищенной» сборке.
PRUNE = [
    # экранная клавиатура тянет за собой весь Qt Quick/QML (~15 МБ)
    "PySide6/Qt*/plugins/platforminputcontexts/*virtualkeyboard*",
    "PySide6/*Qt6Quick*", "PySide6/*Qt6Qml*", "PySide6/*Qt6VirtualKeyboard*",
    "PySide6/Qt*/lib/*Qt6Quick*", "PySide6/Qt*/lib/*Qt6Qml*", "PySide6/Qt*/lib/*Qt6VirtualKeyboard*",
    # чтение PDF как картинки и редкие форматы изображений
    "PySide6/Qt*/plugins/imageformats/*qpdf*", "PySide6/*Qt6Pdf*", "PySide6/Qt*/lib/*Qt6Pdf*",
    "PySide6/Qt*/plugins/imageformats/*qtiff*", "PySide6/Qt*/plugins/imageformats/*qtga*",
    "PySide6/Qt*/plugins/imageformats/*qwbmp*", "PySide6/Qt*/plugins/imageformats/*qicns*",
    # программный OpenGL (~20 МБ на Windows) — Kadr рисует без OpenGL
    "PySide6/opengl32sw.dll",
]
KEEP_TRANSLATIONS = ("_ru.qm", "_en.qm")


def prune_bundle(internal: Path) -> int:
    """Удаляет из собранной программы неиспользуемые части Qt. Возвращает освобождённые байты."""
    freed = 0
    for pattern in PRUNE:
        for path in internal.glob(pattern):
            if path.is_file():
                freed += path.stat().st_size
                path.unlink()
    for tr in internal.glob("PySide6/Qt*/translations/*.qm"):
        if not tr.name.endswith(KEEP_TRANSLATIONS):
            freed += tr.stat().st_size
            tr.unlink()
    return freed


def main() -> None:
    version = resolve_version()
    print(f"Версия: {version}")
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
        # Pillow нужен только при сборке (иконки); в программе WEBP пишет плагин Qt
        "--exclude-module", "PIL", "--exclude-module", "tkinter", "--exclude-module", "unittest",
        "--exclude-module", "pydoc", "--exclude-module", "lib2to3",
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
    internal = DIST / APP_NAME / "_internal"
    freed = prune_bundle(internal if internal.exists() else DIST / APP_NAME)
    print(f"Убрано неиспользуемых частей Qt: {freed / 1e6:.1f} МБ")

    if sys.platform == "win32":
        portable = shutil.make_archive(str(DIST / f"{APP_NAME}-portable"), "zip", DIST, APP_NAME)
        print(f"Портативная версия: {portable}")
        iscc = find_iscc()
        if iscc:
            make_installer_images()
            subprocess.run([iscc, f"/DAppVersion={version}", str(ROOT / "installer" / "kadr.iss")],
                           check=True, cwd=ROOT)
            print(f"Установщик: {DIST / 'Kadr-Setup.exe'}")
        else:
            print("Inno Setup 6 не найден — установщик не собран (https://jrsoftware.org/isdl.php)")
    for f in sorted(DIST.glob(f"{APP_NAME}-*")):
        print(f"  {f.name}: {f.stat().st_size / 1e6:.1f} МБ")
    print(f"Готово: {DIST}")


if __name__ == "__main__":
    main()
