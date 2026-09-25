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
