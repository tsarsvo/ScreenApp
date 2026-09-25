"""Поиск вложенного FFmpeg, выбор видеокодера и список микрофонов."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

# На Windows не показываем чёрное окно консоли у дочерних процессов
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Порядок предпочтения: аппаратные кодеры (почти не грузят CPU) → программные
WIN_ENCODERS = ["h264_nvenc", "h264_amf", "h264_qsv", "h264_mf"]
LINUX_ENCODERS = ["h264_nvenc", "libx264", "libopenh264", "mpeg4"]


def bundled_dir() -> Path:
    """kadr/bin — рядом с исходниками или внутри сборки PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "kadr" / "bin"


def find_ffmpeg() -> str | None:
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    env = os.environ.get("KADR_FFMPEG")
    for candidate in (env, bundled_dir() / name):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


def run(args: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    # stdin=DEVNULL обязателен: у .exe без консоли (PyInstaller --windowed) нет валидного stdin
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def encoder_args(encoder: str, bitrate_k: int, fps: int, seg: int) -> list[str]:
    """Параметры кодера. Ключевой кадр ровно на границе каждого сегмента — чтобы
    склейка без перекодирования начиналась с чистого кадра."""
    b = f"{bitrate_k}k"
    common = ["-b:v", b, "-maxrate", b, "-bufsize", f"{bitrate_k * 2}k",
              "-g", str(fps * seg), "-force_key_frames", f"expr:gte(t,n_forced*{seg})"]
    per = {
        "h264_nvenc": ["-preset", "p4", "-rc", "cbr", "-forced-idr", "1"],
        "h264_amf": ["-quality", "speed", "-rc", "cbr"],
        "h264_qsv": ["-preset", "veryfast"],
        "h264_mf": ["-rate_control", "cbr", "-scenario", "display_remoting"],
        "libx264": ["-preset", "veryfast", "-tune", "zerolatency"],
        "libopenh264": [],
        "mpeg4": ["-q:v", "5"],
    }
    return ["-c:v", encoder, *per.get(encoder, []), *common]


@lru_cache(maxsize=4)
def working_encoders(ffmpeg: str) -> tuple[str, ...]:
    """Кодеры, которые реально работают на этом ПК (h264_nvenc есть в сборке
    и без видеокарты NVIDIA, поэтому пробуем закодировать пару кадров)."""
    candidates = WIN_ENCODERS if sys.platform == "win32" else LINUX_ENCODERS
    ok = []
    for enc in candidates:
        vf = "format=yuv420p" if enc == "mpeg4" else "format=nv12"
        try:
            r = run([ffmpeg, "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30", "-frames:v", "5",
                     "-vf", vf, *encoder_args(enc, 2000, 30, 5), "-f", "null", "-"], timeout=20)
            if r.returncode == 0:
                ok.append(enc)
        except (OSError, subprocess.SubprocessError):
            pass
    return tuple(ok)


def has_filter(ffmpeg: str, name: str) -> bool:
    try:
        out = run([ffmpeg, "-hide_banner", "-filters"]).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return False
    return re.search(rf"\s{re.escape(name)}\s", out) is not None


def list_microphones(ffmpeg: str | None) -> list[str]:
    """Имена микрофонов в том виде, в котором их принимает FFmpeg."""
    if sys.platform == "win32":
        if not ffmpeg:
            return []
        try:
            r = run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"])
        except (OSError, subprocess.SubprocessError):
            return []
        text = r.stderr.decode("utf-8", errors="replace")
        return re.findall(r'"([^"]+)"\s+\(audio\)', text)
    if sys.platform.startswith("linux"):
        try:
            r = run(["pactl", "list", "short", "sources"])
        except (OSError, subprocess.SubprocessError):
            return []
        names = [line.split("\t")[1] for line in r.stdout.decode(errors="replace").splitlines()
                 if "\t" in line]
        return [n for n in names if not n.endswith(".monitor")]
    return []


def linux_monitor_source() -> str:
    """Источник PulseAudio/PipeWire со звуком, который сейчас играет система."""
    try:
        sink = run(["pactl", "get-default-sink"]).stdout.decode().strip()
        if sink:
            return f"{sink}.monitor"
    except (OSError, subprocess.SubprocessError):
        pass
    return "@DEFAULT_MONITOR@"
