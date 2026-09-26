"""Служебные скрипты сборки."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest

import bump_readme


def test_readme_has_versioned_badges_and_bump_updates_both():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    bumped = bump_readme.bump(text, "7.8.9")
    assert bumped.count("-v7.8.9-3F6BFF") == 2          # кнопка «Скачать» и бейдж версии
    assert bump_readme.bump(bumped, "7.8.10").count("-v7.8.10-3F6BFF") == 2


def test_bump_fails_loudly_without_markers():
    with pytest.raises(SystemExit):
        bump_readme.bump("no badges here", "1.0.0")


import release_notes


def test_release_notes_take_the_version_section_from_changelog():
    text = "# История\n\n## 2.0.0 — сегодня\n### Новое\n- Раз\n\n## 1.9.0 — вчера\n- Старое\n"
    out = release_notes.notes(text, "2.0.0")
    assert "Kadr-Setup.exe" in out and "- Раз" in out and "Старое" not in out
    assert release_notes.section(text, "1.9.0") == "- Старое"
    with pytest.raises(SystemExit):
        release_notes.section(text, "1.9")          # 1.9 ≠ 1.9.0: нужен точный номер
    with pytest.raises(SystemExit):
        release_notes.section(text, "3.0.0")


def test_changelog_has_current_version():
    from kadr import DEFAULT_VERSION

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.section(text, DEFAULT_VERSION)     # версия в коде описана в CHANGELOG
