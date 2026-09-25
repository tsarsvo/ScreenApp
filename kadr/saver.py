"""Сохранение изображения в выбранном формате и копирование в буфер обмена."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QImageWriter

from . import APP_NAME
from .config import Settings

_EXT = {"png": "png", "jpg": "jpg", "webp": "webp"}


def unique_path(folder: Path, ext: str, prefix: str = APP_NAME) -> Path:
    """Свободное имя файла. Файл сразу создаётся (эксклюзивно), поэтому два сохранения,
    идущие параллельно в фоне, никогда не получат одно и то же имя."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    n = 1
    while True:
        path = folder / (f"{prefix}_{stamp}.{ext}" if n == 1 else f"{prefix}_{stamp}_{n}.{ext}")
        try:
            with open(path, "xb"):
                return path
        except FileExistsError:
            n += 1


def save_image(image: QImage, settings: Settings) -> Path:
    """Сохраняет картинку в папку из настроек. Возвращает путь или бросает OSError."""
    folder = Path(settings.save_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    fmt = settings.image_format
    path = unique_path(folder, _EXT[fmt])

    try:
        if fmt == "png":
            ok = image.save(str(path), "PNG")
        elif fmt == "jpg":
            # JPEG не поддерживает прозрачность — сводим к RGB
            ok = image.convertToFormat(QImage.Format.Format_RGB888).save(str(path), "JPG", settings.quality)
        else:
            ok = _save_webp(image, path, settings.quality)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if not ok:
        path.unlink(missing_ok=True)  # не оставляем пустой зарезервированный файл
        raise OSError(f"Не удалось записать файл {path}")
    return path


def _save_webp(image: QImage, path: Path, quality: int) -> bool:
    if b"webp" in [bytes(f) for f in QImageWriter.supportedImageFormats()]:
        return image.save(str(path), "WEBP", quality)
    # Фолбэк через Pillow, если в сборке Qt нет плагина qwebp
    from io import BytesIO

    from PIL import Image

    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    Image.open(BytesIO(bytes(data))).save(path, "WEBP", quality=quality, method=4)
    return True


def copy_to_clipboard(image: QImage) -> None:
    QGuiApplication.clipboard().setImage(image)
