"""Тесты буфера повтора. Работают без экрана; склейка — если в системе есть FFmpeg."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest
from PySide6.QtCore import QRect

from kadr.replay import recorder as rec
from kadr.replay.recorder import Attempt, ReplayOptions, build_command, collect_segments, plan_attempts

OUT = Path("/tmp/seg")


def _opts(**kw):
    base = dict(minutes=2, fps=30, screen_rect=QRect(0, 0, 1920, 1080))
    base.update(kw)
    return ReplayOptions(**base)


def _graph(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_plan_windows_prefers_gpu_and_falls_back(monkeypatch):
    monkeypatch.setattr(rec.sys, "platform", "win32")
    plan = plan_attempts(("h264_nvenc", "h264_mf"), has_ddagrab=True)
    assert [(a.video, a.encoder) for a in plan] == [
        ("ddagrab_direct", "h264_nvenc"), ("ddagrab_download", "h264_nvenc"),
        ("ddagrab_download", "h264_mf"), ("gdigrab", "h264_nvenc")]
    assert [a.video for a in plan_attempts(("h264_mf",), has_ddagrab=False)] == ["gdigrab"]
    assert plan_attempts((), has_ddagrab=True) == []


def test_command_ddagrab_direct_no_audio():
    cmd = build_command("ffmpeg", Attempt("ddagrab_direct", "h264_nvenc"), _opts(monitor=1), OUT, [])
    assert _graph(cmd) == "ddagrab=output_idx=1:framerate=30:draw_mouse=1[vout]"
    assert "-an" not in cmd and "[aout]" not in cmd
    assert cmd[cmd.index("-segment_wrap") + 1] == str(2 * 60 // rec.SEG + 2)
    assert cmd[-1].endswith("seg_%03d.ts")


def test_command_downscale_and_two_audio_sources():
    sys_audio = ["-f", "s16le", "-ar", "48000", "-ac", "2", "-i", "pipe:0"]
    mic = ["-f", "dshow", "-i", "audio=Микрофон (Realtek)"]
    cmd = build_command("ffmpeg", Attempt("ddagrab_direct", "h264_amf"),
                        _opts(height=720, fps=60, screen_rect=QRect(0, 0, 2560, 1440)), OUT, [sys_audio, mic])
    g = _graph(cmd)
    # масштабирование требует выгрузки кадров с GPU
    assert "hwdownload,format=bgra,scale=-2:720:flags=bicubic,format=nv12[vout]" in g
    assert "[0:a]aresample" in g and "[1:a]aresample" in g and "amix=inputs=2" in g
    assert cmd.count("-i") == 2 and "audio=Микрофон (Realtek)" in cmd
    assert cmd[cmd.index("-g") + 1] == str(60 * rec.SEG)


def test_command_gdigrab_single_audio_offsets():
    cmd = build_command("ffmpeg", Attempt("gdigrab", "h264_mf"),
                        _opts(screen_rect=QRect(1920, 0, 1280, 1024)), OUT, [["-f", "lavfi", "-i", "sine"]])
    assert cmd[cmd.index("-offset_x") + 1] == "1920"
    assert "[1:a]aresample=48000:async=1000:first_pts=0[aout]" in _graph(cmd)
    assert "amix" not in _graph(cmd)


def test_collect_segments_takes_newest_by_mtime(tmp_path):
    # Кольцо перезаписывает файлы по кругу: порядок определяется временем, а не именем
    names = ["seg_003.ts", "seg_004.ts", "seg_000.ts", "seg_001.ts", "seg_002.ts"]
    now = time.time()
    for i, n in enumerate(names):
        p = tmp_path / n
        p.write_bytes(b"x")
        os.utime(p, (now + i, now + i))
    got = collect_segments(tmp_path, minutes=1, include_current=True)  # 60/SEG + 1 сегментов
    assert [p.name for p in got] == names[-(60 // rec.SEG + 1):]
    # по умолчанию самый новый (ещё дописываемый) сегмент не берётся
    assert collect_segments(tmp_path, minutes=1)[-1].name == names[-2]


def test_bitrate_is_sane():
    assert 7000 <= rec.bitrate_for(1920, 1080, 30) <= 8000
    assert rec.bitrate_for(320, 240, 30) == 3000


def test_fetch_ffmpeg_picks_latest_stable():
    from fetch_ffmpeg import pick_asset

    sums = ("aa  ffmpeg-master-latest-win64-lgpl.zip\n"
            "bb  ffmpeg-n7.1-latest-win64-lgpl-7.1.zip\n"
            "cc  ffmpeg-n8.0-latest-win64-lgpl-8.0.zip\n"
            "dd  ffmpeg-n8.0-latest-win64-gpl-8.0.zip\n")
    assert pick_asset(sums) == ("ffmpeg-n8.0-latest-win64-lgpl-8.0.zip", "cc")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нужен ffmpeg")
def test_segments_concat_into_mp4(tmp_path):
    """Настоящая цепочка: кольцо сегментов → склейка без перекодирования."""
    ffmpeg = shutil.which("ffmpeg")
    encoders = rec.ff.working_encoders(ffmpeg)
    if not encoders:
        pytest.skip("нет рабочего H.264 кодера")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=s=320x240:r=15", "-f", "lavfi", "-i", "sine", "-t", "12",
                    "-vf", "format=yuv420p" if encoders[0] == "mpeg4" else "format=nv12",
                    *rec.ff.encoder_args(encoders[0], 500, 15, rec.SEG), "-c:a", "aac",
                    "-f", "segment", "-segment_time", str(rec.SEG), "-segment_format", "mpegts",
                    "-reset_timestamps", "1", str(tmp_path / "seg_%03d.ts")], check=True, timeout=60)
    segs = collect_segments(tmp_path, minutes=1, include_current=True)   # запись окончена — все целые
    out = tmp_path / "out.mp4"
    rec.concat_segments(ffmpeg, segs, out)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(out)], capture_output=True, text=True)
    assert abs(float(probe.stdout) - 12) < 1.0


def test_restart_is_nonblocking_and_leaves_no_orphans(monkeypatch, tmp_path):
    """start()/stop() возвращаются сразу; быстрая смена настроек не плодит процессы FFmpeg."""
    import threading

    r = rec.ReplayRecorder()
    r.dir = tmp_path
    launched, killed = [], []

    class FakeProc:
        stdin = None

        def __init__(self):
            self.alive = True
            launched.append(self)

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False
            killed.append(self)

        kill = terminate

        def wait(self, timeout=None):
            return 0

    def slow_probe(*_a, **_k):
        time.sleep(0.3)                       # «долгая» проверка кодеров
        return ("libx264",), False

    monkeypatch.setattr(rec.ff, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(rec.ff, "probe", slow_probe)
    monkeypatch.setattr(rec, "popen_tied", lambda *a, **k: FakeProc())
    monkeypatch.setattr(rec, "STARTUP_CHECK_S", 0.1)
    monkeypatch.setattr(r, "_audio_inputs", lambda exe, opts: ([], None))

    t = time.perf_counter()
    for m in (1, 2, 3, 4, 5):                 # пользователь быстро щёлкает длительность
        r.start(_opts(minutes=m))
    assert time.perf_counter() - t < 0.1      # интерфейс не ждал
    deadline = time.time() + 5
    while not r.running and time.time() < deadline:
        time.sleep(0.05)
    assert r.running and r._opts.minutes == 5
    alive = [p for p in launched if p.alive]
    assert len(alive) == 1                    # ровно один живой FFmpeg
    r.stop(wait=True)
    assert not [p for p in launched if p.alive] and not r.running
    assert threading.active_count() < 20


@pytest.mark.skipif(sys.platform == "darwin", reason="на macOS повтор экрана не поддерживается")
@pytest.mark.parametrize("attempt", range(3))  # гонка при запуске ловится не с первого раза
def test_ffmpeg_child_dies_with_kadr(tmp_path, attempt):
    """Если Kadr убит принудительно, дочерний процесс (FFmpeg) не должен остаться «сиротой».
    Ребёнок пишет «пульс» в файл; после убийства родителя пульс должен прекратиться."""
    beat = tmp_path / "beat.txt"
    child = (f"import time, pathlib\np = pathlib.Path({str(beat)!r})\n"
             "for i in range(600):\n    p.write_text(str(i)); time.sleep(0.1)\n")
    parent = (f"import sys, time; sys.path.insert(0, {str(ROOT)!r})\n"
              "from kadr.replay.child import popen_tied\n"
              f"popen_tied([sys.executable, '-c', {child!r}])\n"
              "time.sleep(60)\n")
    proc = subprocess.Popen([sys.executable, "-c", parent])
    deadline = time.time() + 20
    while not beat.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert beat.exists(), "дочерний процесс не запустился"
    proc.kill()                        # как «Снять задачу» в Диспетчере задач
    proc.wait()
    time.sleep(1.0)
    before = beat.read_text()
    time.sleep(1.0)
    assert beat.read_text() == before, "дочерний процесс пережил родителя"


def test_save_waits_for_current_segment_to_finish(tmp_path):
    """Нажали «Сохранить» посреди сегмента: ждём, пока он допишется, и берём его целым,
    а только что начатый (оборванный) — нет."""
    import threading

    for i, name in enumerate(("seg_000.ts", "seg_001.ts")):
        p = tmp_path / name
        p.write_bytes(b"x")
        os.utime(p, ns=(time.time_ns() + i * 10**6, time.time_ns() + i * 10**6))
    writing = tmp_path / "seg_001.ts"             # «дописывается» в момент нажатия

    def ffmpeg_rolls_over():
        time.sleep(0.4)
        writing.write_bytes(b"xx")                # дописали
        nxt = tmp_path / "seg_002.ts"
        nxt.write_bytes(b"y")                     # и начали следующий
        t = time.time_ns() + 10**9
        os.utime(nxt, ns=(t, t))

    threading.Thread(target=ffmpeg_rolls_over).start()
    t0 = time.monotonic()
    assert rec.wait_for_rollover(tmp_path, timeout=5)
    assert 0.3 < time.monotonic() - t0 < 3
    names = [p.name for p in collect_segments(tmp_path, minutes=1)]
    assert names[-1] == "seg_001.ts" and "seg_002.ts" not in names


def test_capture_that_worked_is_retried_not_replaced_by_gdigrab(monkeypatch, tmp_path):
    """ddagrab упал посреди записи (игра ушла в монопольный полноэкранный режим) и какое-то
    время не запускается — Kadr ждёт и пробует его же, а не переходит на gdigrab:
    с gdigrab курсор в игре начинал мигать."""
    r = rec.ReplayRecorder()
    r.dir = tmp_path
    tried = []
    script = iter([(True, False), (False, None), (False, None), (True, True)])   # (запустился, живёт)

    class Proc:
        stdin = None

        def __init__(self, alive):
            self.alive = alive

        def poll(self):
            return None if self.alive else 1

        def terminate(self):
            self.alive = False

        kill = terminate

        def wait(self, timeout=None):
            return 0

    def launch(exe, attempt, opts, stop):
        tried.append(attempt.video)
        ok, alive = next(script)
        if ok:
            r._proc = Proc(alive)
        return ok, "" if ok else "DXGI_ERROR_ACCESS_LOST"

    monkeypatch.setattr(rec.ff, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(rec.ff, "probe", lambda *a, **k: (("h264_nvenc",), True))
    monkeypatch.setattr(rec, "plan_attempts", lambda enc, dda: [Attempt("ddagrab_download", "h264_nvenc"),
                                                              Attempt("gdigrab", "h264_nvenc")])
    monkeypatch.setattr(rec, "RETRY_MIN_S", 0.01)
    monkeypatch.setattr(r, "_launch", launch)
    r.start(_opts())
    deadline = time.time() + 5
    while len(tried) < 4 and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)
    r.stop(wait=True)
    assert tried == ["ddagrab_download"] * 4


def _scripted_recorder(monkeypatch, tmp_path, outcomes, attempts=None, probe_results=None):
    """Рекордер, у которого запуск FFmpeg заменён сценарием: outcomes(attempt, opts) → (ok, живёт)."""
    r = rec.ReplayRecorder()
    r.dir = tmp_path / "kadr-replay-test"
    tried, errors, probes = [], [], []
    r.error.connect(errors.append)

    class Proc:
        stdin = None

        def __init__(self, alive):
            self.alive = alive

        def poll(self):
            return None if self.alive else 1

        def terminate(self):
            self.alive = False

        kill = terminate

        def wait(self, timeout=None):
            return 0

    def launch(exe, attempt, opts, stop):
        tried.append((attempt.video, opts.mic))
        ok, alive = outcomes(attempt, opts, len(tried))
        if ok:
            r._proc = Proc(alive)
        return ok, "" if ok else "boom"

    def probe(exe, cache_dir=None, refresh=False):
        probes.append(refresh)
        return (probe_results or {}).get(refresh, (("h264_nvenc",), True))

    monkeypatch.setattr(rec.ff, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(rec.ff, "probe", probe)
    monkeypatch.setattr(rec, "plan_attempts", lambda enc, dda: list(attempts or [
        Attempt("ddagrab_download", "h264_nvenc"), Attempt("gdigrab", "h264_nvenc")]) if enc else [])
    for name in ("RETRY_MIN_S", "GIVE_UP_MIN_S", "GIVE_UP_MAX_S"):
        monkeypatch.setattr(rec, name, 0.01)
    monkeypatch.setattr(r, "_launch", launch)
    return r, tried, errors, probes


def _wait(cond, timeout=5):
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        time.sleep(0.02)
    for _ in range(5):            # сигналы из фонового потока приходят через очередь событий
        app.processEvents()
        time.sleep(0.02)
    return cond()


def test_replay_keeps_trying_after_everything_failed(monkeypatch, tmp_path):
    """Сразу после входа в Windows ничего не завелось — Kadr сообщает один раз, через паузу
    проверяет кодеры заново и запускает запись, а не сдаётся до перезапуска."""
    r, tried, errors, probes = _scripted_recorder(
        monkeypatch, tmp_path, lambda a, o, n: (n > 8, True),
        probe_results={False: ((), False), True: (("h264_nvenc",), True)})   # сначала кодеров «нет»
    r.start(_opts())
    assert _wait(lambda: r.running)
    r.stop(wait=True)
    _wait(lambda: True)
    assert len(errors) == 1 and "снова" in errors[0]
    assert probes[0] is False and True in probes          # кодеры проверены заново


def test_replay_drops_missing_microphone_instead_of_failing(monkeypatch, tmp_path):
    r, tried, errors, _ = _scripted_recorder(monkeypatch, tmp_path, lambda a, o, n: (not o.mic, True))
    r.start(_opts(mic=True))
    assert _wait(lambda: r.running)
    r.stop(wait=True)
    _wait(lambda: True)
    assert tried[:2] == [("ddagrab_download", True), ("ddagrab_download", False)]
    assert any("Микрофон" in e for e in errors)


def test_replay_gives_ddagrab_time_before_gdigrab(monkeypatch, tmp_path):
    r, tried, _, _ = _scripted_recorder(monkeypatch, tmp_path, lambda a, o, n: (n == 3, True))
    r.start(_opts())
    assert _wait(lambda: r.running)
    r.stop(wait=True)
    assert [v for v, _ in tried] == ["ddagrab_download"] * 3   # не ушли на gdigrab


def test_launch_reports_unusable_folder(tmp_path):
    r = rec.ReplayRecorder()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    r.dir = blocker / "sub"                                # папку не создать
    ok, err = r._launch("ffmpeg", Attempt("gdigrab", "libx264"), _opts(), __import__("threading").Event())
    assert not ok and "папка" in err


def test_empty_probe_is_not_cached(monkeypatch, tmp_path):
    from kadr.replay import ffmpeg as ff

    exe = tmp_path / "ffmpeg"
    exe.write_text("")
    monkeypatch.setattr(ff, "working_encoders", lambda e: ())
    monkeypatch.setattr(ff, "has_filter", lambda e, n: False)
    assert ff.probe(str(exe), tmp_path) == ((), False)
    assert not (tmp_path / "ffmpeg-probe.json").exists()


def test_replay_saved_as_numbered_video(monkeypatch, tmp_path):
    r = rec.ReplayRecorder()
    saved, failed = [], []
    r.saved.connect(saved.append)
    r.save_failed.connect(failed.append)
    monkeypatch.setattr(rec.ff, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(rec, "wait_for_rollover", lambda *a: True)
    monkeypatch.setattr(rec, "collect_segments", lambda *a: [tmp_path / "seg_000.ts"])
    monkeypatch.setattr(rec, "concat_segments", lambda exe, segs, out: out.write_bytes(b"mp4"))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "Video_4.mp4").write_bytes(b"old")
    r._save(str(out_dir), 1)

    def boom(*_a):
        raise RuntimeError("concat")

    monkeypatch.setattr(rec, "concat_segments", boom)
    r._save(str(out_dir), 1)
    _wait(lambda: True)
    assert [p.name for p in saved] == ["Video_5.mp4"] and failed == ["concat"]
    assert sorted(p.name for p in out_dir.iterdir()) == ["Video_4.mp4", "Video_5.mp4"]   # пустой не остался
