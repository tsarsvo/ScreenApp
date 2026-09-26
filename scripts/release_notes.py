"""Описание релиза на GitHub: как установить + раздел версии из CHANGELOG.md.

    python scripts/release_notes.py 1.2.2 release_notes.md

Вызывается сборкой при публикации релиза. Если в CHANGELOG.md нет раздела этой версии,
сборка останавливается: релиз без описания изменений не выходит.
"""
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

INSTALL = """**Скачайте `Kadr-Setup.exe`** и запустите — программа установится с ярлыками на рабочем столе и в «Пуске».
`Kadr-portable.zip` — версия без установки: распакуйте и запустите `Kadr.exe`.
Уже установленный Kadr предложит обновиться сам (меню значка в трее → «Обновить до vX»).
Если Windows SmartScreen предупредит о неизвестном издателе: «Подробнее» → «Выполнить в любом случае».
"""


def section(text: str, version: str) -> str:
    """Текст раздела «## <версия> …» до следующего раздела того же уровня."""
    head = re.compile(rf"^## v?{re.escape(version)}(?:\s|$).*$", re.MULTILINE)
    m = head.search(text)
    if not m:
        raise SystemExit(f"В CHANGELOG.md нет раздела «## {version}» — допишите, что изменилось")
    nxt = re.compile(r"^## ", re.MULTILINE).search(text, m.end())
    body = text[m.end():nxt.start() if nxt else len(text)].strip()
    if not body:
        raise SystemExit(f"Раздел {version} в CHANGELOG.md пустой")
    return body


def notes(text: str, version: str) -> str:
    return f"{INSTALL}\n## Что нового в {version}\n\n{section(text, version)}\n"


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    version = sys.argv[1].lstrip("v")
    text = notes(CHANGELOG.read_text(encoding="utf-8"), version)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding="utf-8")   # файл пишем сами: без перекодировки оболочкой
        print(f"Описание релиза {version}: {sys.argv[2]}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
