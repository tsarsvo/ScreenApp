"""Автообновление: версии, разбор ответа GitHub, проверка SHA-256 перед установкой."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtCore import QCoreApplication

from kadr import updater


@pytest.fixture(scope="module")
def app():
    # QApplication, а не QCoreApplication: тест кнопки в настройках создаёт окно
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _release_json(tag="v9.9.9", payload=b"installer"):
    # форма ответа — как у настоящего релиза v1.1.0
    return {
        "tag_name": tag, "html_url": f"https://github.com/tsarsvo/ScreenApp/releases/tag/{tag}", "body": "notes",
        "assets": [
            {"name": "Kadr-portable.zip", "browser_download_url": f"https://github.com/tsarsvo/ScreenApp/releases/download/{tag}/Kadr-portable.zip", "digest": "sha256:00"},
            {"name": "Kadr-Setup.exe", "browser_download_url": f"https://github.com/tsarsvo/ScreenApp/releases/download/{tag}/Kadr-Setup.exe",
             "digest": "sha256:" + hashlib.sha256(payload).hexdigest()},
        ],
    }


@pytest.mark.parametrize("remote,local,newer", [
    ("v1.2.0", "1.1.1", True), ("1.10.0", "1.9.9", True), ("v1.1.1", "1.1.1", False),
    ("1.1", "1.1.0", False), ("v2.0.0-beta", "1.9", True), ("garbage", "1.0", False), ("1.0.9", "1.1", False),
])
def test_version_compare(remote, local, newer):
    assert updater.is_newer(remote, local) is newer


def test_parse_release_picks_installer_and_digest():
    rel = updater.parse_release(_release_json(payload=b"abc"))
    assert rel.version == "9.9.9" and rel.installer_url.endswith("Kadr-Setup.exe")
    assert rel.installer_sha256 == hashlib.sha256(b"abc").hexdigest()


def _wait(pred, timeout=5):
    deadline = time.time() + timeout
    while not pred() and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    QCoreApplication.processEvents()


def test_check_reports_new_version(app, monkeypatch):
    monkeypatch.setattr(updater, "_fetch", lambda url, timeout=15: json.dumps(_release_json()).encode())
    u = updater.Updater()
    got = []
    u.available.connect(got.append)
    u.check()
    _wait(lambda: got)
    assert got and got[0].version == "9.9.9"


@pytest.mark.parametrize("tampered", [False, True])
def test_install_verifies_sha256(app, monkeypatch, tmp_path, tampered):
    payload = b"real installer"
    served = b"evil installer" if tampered else payload
    launched, failed, quit_ = [], [], []
    monkeypatch.setattr(updater, "_fetch", lambda url, timeout=15: served)
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: launched.append(args))
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    u = updater.Updater()
    u.latest = updater.parse_release(_release_json(payload=payload))
    u.failed.connect(failed.append)
    u.ready_to_quit.connect(lambda: quit_.append(1))
    u.install()
    _wait(lambda: failed or quit_)
    if tampered:
        assert failed and "контрольная сумма" in failed[0] and not launched
    else:
        assert quit_ and launched and "/SILENT" in launched[0]
        assert Path(launched[0][0]).read_bytes() == payload


def test_settings_check_updates_button(monkeypatch, tmp_path):
    """Кнопка «Проверить обновления» в настройках: проверка → статус → «Обновить до vX» → установка."""
    from PySide6.QtWidgets import QApplication

    from kadr import config
    from kadr.theme import ThemeManager
    from kadr.ui.settings_window import SettingsWindow

    QApplication.instance() or QApplication([])  # окну настроек нужен QApplication
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    u = updater.Updater()
    calls = []
    monkeypatch.setattr(u, "check", lambda manual=False: calls.append(("check", manual)))
    monkeypatch.setattr(u, "install", lambda: calls.append(("install",)))
    w = SettingsWindow(config.SettingsStore(), ThemeManager("light"), updater=u)

    assert w.update_btn.text() == "Проверить обновления"
    w.update_btn.click()
    assert calls == [("check", True)] and "Проверяю" in w.update_status.text()

    u.up_to_date.emit()
    assert "последняя версия" in w.update_status.text() and w.update_btn.isEnabled()

    rel = updater.parse_release(_release_json(tag="v9.9.9"))
    u.latest = rel
    u.available.emit(rel)
    assert w.update_btn.text() == "Обновить до v9.9.9"
    w.update_btn.click()
    assert calls[-1] == ("install",)
    w.close()


@pytest.mark.parametrize("url, ok", [
    ("https://api.github.com/repos/tsarsvo/ScreenApp/releases/latest", True),
    ("https://github.com/tsarsvo/ScreenApp/releases/download/v1/Kadr-Setup.exe", True),
    ("https://release-assets.githubusercontent.com/x/Kadr-Setup.exe", True),
    ("http://github.com/tsarsvo/ScreenApp/releases/download/v1/Kadr-Setup.exe", False),   # без https
    ("file:///C:/Windows/System32/calc.exe", False),
    ("https://github.com.evil.example/Kadr-Setup.exe", False),
    ("https://evilgithubusercontent.com/x", False),
    ("", False), (None, False),
])
def test_only_https_github_urls_are_trusted(url, ok):
    assert updater.is_trusted_url(url) is ok


def test_release_with_untrusted_urls_or_bad_digest_is_not_installed_silently(app, monkeypatch):
    data = _release_json()
    data["html_url"] = "file:///C:/evil"
    data["assets"][1]["browser_download_url"] = "https://evil.example/Kadr-Setup.exe"
    rel = updater.parse_release(data)
    assert rel.page_url == updater.RELEASES_PAGE and rel.installer_url is None

    data = _release_json()
    data["assets"][1]["digest"] = ""                      # нет контрольной суммы
    rel = updater.parse_release(data)
    assert rel.installer_sha256 is None
    opened, fetched = [], []
    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater, "_fetch", lambda *a, **k: fetched.append(a))
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString())))
    u = updater.Updater()
    u.latest = rel
    u.install()
    assert not fetched and opened == [rel.page_url]       # без проверки — не качаем и не запускаем


def test_fetch_refuses_untrusted_url():
    with pytest.raises(ValueError):
        updater._fetch("file:///etc/passwd")
