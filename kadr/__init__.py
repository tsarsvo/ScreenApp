"""Kadr — минималистичное приложение для скриншотов."""

APP_NAME = "Kadr"
APP_ID = "app.kadr.screenshot"
DEFAULT_VERSION = "1.0.0"

try:
    # Файл создаёт scripts/build.py из git-тега релиза (v1.2.3 → "1.2.3")
    from ._version import __version__
except ImportError:
    __version__ = DEFAULT_VERSION
