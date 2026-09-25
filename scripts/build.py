"""Сборка автономного приложения через PyInstaller.

    pip install pyinstaller
    python scripts/build.py

Результат: dist/Kadr(.exe | .app). Иконки генерируются из векторного логотипа.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from kadr import APP_NAME  # noqa: E402
from kadr.icons import LOGO_SVG, logo_image  # noqa: E402


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


def main() -> None:
    res = make_icons()
    icon = res / ("logo.icns" if sys.platform == "darwin" else "logo.ico")
    cmd = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "main.py"),
        "--name", APP_NAME, "--windowed", "--noconfirm", "--clean",
        "--icon", str(icon),
        "--hidden-import", "pynput.keyboard._xorg",
        "--hidden-import", "pynput.keyboard._darwin",
        "--hidden-import", "pynput.keyboard._win32",
    ]
    if sys.platform == "darwin":
        # Иконка в Dock скрывается в рантайме (см. app._hide_dock_icon)
        cmd += ["--osx-bundle-identifier", "app.kadr.screenshot"]
    else:
        cmd += ["--onefile"]
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"Готово: {ROOT / 'dist'}")


if __name__ == "__main__":
    main()
