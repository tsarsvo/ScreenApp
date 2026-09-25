"""Прописывает номер версии в кнопку «Скачать» и бейдж версии в README.

    python scripts/bump_readme.py 1.2.1

Вызывается сборкой при публикации релиза. Номер стоит прямо в адресе картинки:
GitHub кэширует картинки по адресу, поэтому новый адрес = мгновенно новая кнопка.
"""
import re
import sys
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"
# Строки с этими бейджами помечены «kadr-version» в alt-тексте
PATTERN = re.compile(r"(-)v\d+(?:\.\d+)*(-3F6BFF[^\"]*\"[^>]*kadr-version)")


def bump(text: str, version: str) -> str:
    new, n = PATTERN.subn(rf"\g<1>v{version}\g<2>", text)
    if n == 0:
        raise SystemExit("В README не найдены бейджи версии (метка kadr-version)")
    return new


def main() -> None:
    version = sys.argv[1].lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        raise SystemExit(f"Неверная версия: {version}")
    text = README.read_text(encoding="utf-8")
    new = bump(text, version)
    if new != text:
        README.write_text(new, encoding="utf-8")
        print(f"README: версия {version}")
    else:
        print("README уже актуален")


if __name__ == "__main__":
    main()
