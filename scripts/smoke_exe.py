"""Сквозная проверка собранной программы на Windows (запускается в CI после сборки).

    python scripts/smoke_exe.py dist/Kadr/Kadr.exe

Что проверяется на настоящей Windows:
  1. Kadr.exe запускается и не падает;
  2. `Kadr.exe --full` (вторая копия передаёт команду первой) → PNG в папке сохранения;
  3. запись повтора стартует (FFmpeg пишет сегменты), `--save-replay` → корректный MP4;
  4. после принудительного завершения Kadr (как «Снять задачу») не остаётся FFmpeg.
Настройки и файлы — во временной папке, чтобы не зависеть от окружения.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def wait_for(what: str, check, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            print(f"  ✓ {what}")
            return result
        time.sleep(0.5)
    raise SystemExit(f"  ✗ {what}: не дождались за {timeout:.0f} с")


def running(image: str) -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return sum(1 for line in out.splitlines() if line.lower().startswith(f'"{image.lower()}"'))


def main() -> None:
    exe = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp(prefix="kadr-smoke-"))
    appdata, shots = work / "appdata", work / "shots"
    (appdata / "Kadr").mkdir(parents=True)
    (appdata / "Kadr" / "settings.json").write_text(json.dumps({
        "save_dir": str(shots), "notify_on_save": False,
        "replay_enabled": True, "replay_minutes": 1, "replay_fps": 15, "replay_height": 720,
        "replay_system_audio": True,   # на сервере может не быть звука — проверяем, что это не ломает запись
    }), encoding="utf-8")
    env = dict(os.environ, APPDATA=str(appdata))
    replay_dir = Path(tempfile.gettempdir()) / "kadr-replay"

    print(f"Запуск {exe}")
    app = subprocess.Popen([str(exe)], env=env)
    try:
        time.sleep(4)
        if app.poll() is not None:
            raise SystemExit(f"  ✗ Kadr.exe завершился сразу, код {app.returncode}")
        print("  ✓ Kadr.exe работает")

        subprocess.run([str(exe), "--full"], env=env, timeout=30)
        png = wait_for("скриншот всего экрана сохранён (--full)",
                       lambda: next((p for p in shots.glob("Kadr_*.png") if p.stat().st_size > 1000), None), 30)
        print(f"    {png.name}: {png.stat().st_size // 1024} КБ")

        wait_for("запись повтора пишет сегменты",
                 lambda: len([p for p in replay_dir.glob("seg_*.ts") if p.stat().st_size > 0]) >= 2, 120)
        probe = appdata / "Kadr" / "ffmpeg-probe.json"
        if probe.exists():
            print(f"    кодеры: {probe.read_text(encoding='utf-8')}")
        log = replay_dir / "ffmpeg.log"
        if log.exists() and log.read_text(encoding="utf-8", errors="replace").strip():
            print(f"    ffmpeg.log: {log.read_text(encoding='utf-8', errors='replace')[-500:]}")

        subprocess.run([str(exe), "--save-replay"], env=env, timeout=30)
        mp4 = wait_for("повтор сохранён (--save-replay)",
                       lambda: next((p for p in shots.glob("Kadr_Replay_*.mp4") if p.stat().st_size > 1000), None),
                       60)
        ffmpeg = exe.parent / "_internal" / "kadr" / "bin" / "ffmpeg.exe"
        check = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(mp4), "-f", "null", "-"],
                               capture_output=True, text=True, timeout=120)
        if check.returncode != 0 or check.stderr.strip():
            raise SystemExit(f"  ✗ MP4 повреждён: {check.stderr[-500:]}")
        print(f"  ✓ MP4 читается без ошибок ({mp4.stat().st_size // 1024} КБ)")

        before = running("ffmpeg.exe")
        print(f"    FFmpeg запущено: {before}")
        subprocess.run(["taskkill", "/F", "/PID", str(app.pid)], capture_output=True)  # «Снять задачу»
        app.wait(timeout=10)
        wait_for("после принудительного завершения Kadr не осталось FFmpeg",
                 lambda: running("ffmpeg.exe") == 0, 15)
    finally:
        if app.poll() is None:
            app.kill()
        subprocess.run(["taskkill", "/F", "/IM", "ffmpeg.exe"], capture_output=True)
    print("Сквозная проверка пройдена")


if __name__ == "__main__":
    main()
