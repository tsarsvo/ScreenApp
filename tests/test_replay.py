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
    got = collect_segments(tmp_path, minutes=1)  # 60/SEG + 1 сегментов
    assert [p.name for p in got] == names[-(60 // rec.SEG + 1):]


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
    segs = collect_segments(tmp_path, minutes=1)
    out = tmp_path / "out.mp4"
    rec.concat_segments(ffmpeg, segs, out)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(out)], capture_output=True, text=True)
    assert abs(float(probe.stdout) - 12) < 1.0
