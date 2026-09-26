"""Буфер повтора: экран и звук пишутся постоянно, хранятся только последние N минут.

Как это работает:
  FFmpeg пишет запись короткими сегментами по SEG секунд (.ts) по кругу
  (-segment_wrap). На диске всегда лежит не больше N минут + пара сегментов.
  По горячей клавише последние сегменты склеиваются в .mp4 без перекодирования,
  поэтому сохранение занимает секунду-две даже для 5 минут.

Захват на Windows: ddagrab (Desktop Duplication API, кадры сразу на GPU) →
аппаратный кодер NVENC / AMF / QuickSync, иначе Media Foundation. Если ddagrab
недоступен (старый драйвер, RDP) — gdigrab.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Signal

from .. import APP_NAME
from . import ffmpeg as ff
from .child import popen_tied

SEG = 5                      # длина сегмента, секунд
STARTUP_CHECK_S = 4.0        # сколько ждать, чтобы понять, что FFmpeg стартовал нормально


@dataclass
class ReplayOptions:
    minutes: int = 2
    fps: int = 30
    height: int = 0                   # 0 — исходное разрешение, иначе 1080 / 720
    monitor: int = 0                  # индекс монитора
    screen_rect: QRect = field(default_factory=QRect)   # физические пиксели монитора
    system_audio: bool = True
    mic: bool = False
    mic_device: str = ""


@dataclass
class Attempt:
    """Один вариант запуска: способ захвата + кодер."""
    video: str            # ddagrab_direct | ddagrab_download | gdigrab | x11grab
    encoder: str


def bitrate_for(width: int, height: int, fps: int) -> int:
    """~0.12 бит на пиксель: 1080p30 ≈ 7.5 Мбит/с, 1080p60 ≈ 15 Мбит/с."""
    return max(3000, min(40000, int(width * height * fps * 0.12 / 1000)))


def plan_attempts(encoders: tuple[str, ...], has_ddagrab: bool) -> list[Attempt]:
    if not encoders:
        return []
    if sys.platform != "win32":
        return [Attempt("x11grab", e) for e in encoders]
    plan = []
    if has_ddagrab:
        for enc in encoders:
            if enc == "h264_nvenc":
                plan.append(Attempt("ddagrab_direct", enc))   # кадры не покидают GPU
            plan.append(Attempt("ddagrab_download", enc))
    plan.append(Attempt("gdigrab", encoders[0]))
    return plan


def build_command(ffmpeg: str, attempt: Attempt, opts: ReplayOptions, out_dir: Path,
                  audio_inputs: list[list[str]]) -> list[str]:
    """Собирает командную строку FFmpeg. Чистая функция — покрыта тестами."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    inputs: list[list[str]] = []
    rect = opts.screen_rect
    native_h = rect.height() or 1080
    scale = f"scale=-2:{opts.height}:flags=bicubic," if 0 < opts.height < native_h else ""
    pix = "yuv420p" if attempt.encoder == "mpeg4" else "nv12"

    if attempt.video.startswith("ddagrab"):
        src = f"ddagrab=output_idx={opts.monitor}:framerate={opts.fps}:draw_mouse=1"
        if attempt.video == "ddagrab_direct" and not scale:
            video_graph = f"{src}[vout]"
        else:
            video_graph = f"{src},hwdownload,format=bgra,{scale}format={pix}[vout]"
    elif attempt.video == "gdigrab":
        inputs.append(["-f", "gdigrab", "-framerate", str(opts.fps), "-draw_mouse", "1",
                       "-offset_x", str(rect.x()), "-offset_y", str(rect.y()),
                       "-video_size", f"{rect.width()}x{rect.height()}", "-i", "desktop"])
        video_graph = f"[0:v]{scale}format={pix}[vout]"
    else:  # x11grab
        inputs.append(["-f", "x11grab", "-framerate", str(opts.fps), "-draw_mouse", "1",
                       "-video_size", f"{rect.width()}x{rect.height()}",
                       "-i", f"{_display()}+{rect.x()},{rect.y()}"])
        video_graph = f"[0:v]{scale}format={pix}[vout]"

    first_audio = len(inputs)
    inputs += audio_inputs
    graph = [video_graph]
    labels = []
    for k in range(len(audio_inputs)):
        graph.append(f"[{first_audio + k}:a]aresample=48000:async=1000:first_pts=0[a{k}]")
        labels.append(f"[a{k}]")
    if len(labels) == 2:
        graph.append(f"{labels[0]}{labels[1]}amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]")
    elif len(labels) == 1:
        graph[-1] = graph[-1].replace("[a0]", "[aout]")

    for i in inputs:
        cmd += i
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]"]
    if labels:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k", "-ac", "2"]
    width = round(rect.width() * opts.height / native_h) if scale else rect.width()
    bitrate = bitrate_for(width or 1920, opts.height if scale else native_h, opts.fps)
    cmd += ff.encoder_args(attempt.encoder, bitrate, opts.fps, SEG)
    wrap = math.ceil(opts.minutes * 60 / SEG) + 2
    cmd += ["-f", "segment", "-segment_time", str(SEG), "-segment_wrap", str(wrap),
            "-segment_format", "mpegts", "-reset_timestamps", "1",
            str(out_dir / "seg_%03d.ts")]
    return cmd


def _display() -> str:
    return os.environ.get("DISPLAY", ":0")


def _ordered_segments(folder: Path) -> list[Path]:
    segs = []
    for p in folder.glob("seg_*.ts"):
        try:
            st = p.stat()
        except OSError:
            continue  # файл перезаписывается по кругу прямо сейчас
        if st.st_size > 0:
            segs.append((st.st_mtime_ns, p))
    return [p for _, p in sorted(segs)]


def collect_segments(folder: Path, minutes: int, include_current: bool = False) -> list[Path]:
    """Последние сегменты, покрывающие `minutes` минут (с запасом в один сегмент).
    Самый новый сегмент FFmpeg ещё дописывает — его последний кадр оборван, поэтому
    по умолчанию он не берётся (см. wait_for_rollover)."""
    segs = _ordered_segments(folder)
    if not include_current:
        segs = segs[:-1]
    need = math.ceil(minutes * 60 / SEG) + 1
    return segs[-need:]


def wait_for_rollover(folder: Path, timeout: float, poll: float = 0.1) -> bool:
    """Ждём, пока FFmpeg закончит текущий сегмент и начнёт следующий. Тогда отрезок,
    в который пользователь нажал «Сохранить», уже целиком на диске."""
    segs = _ordered_segments(folder)
    if not segs:
        return False
    writing = segs[-1]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        segs = _ordered_segments(folder)
        if segs and segs[-1] != writing:
            return True
        time.sleep(poll)
    return False


def concat_segments(ffmpeg: str, segments: list[Path], out: Path) -> None:
    """Склейка без перекодирования. Последний сегмент ещё пишется — если он
    оборвался на полуслове и мешает, повторяем без него."""
    for attempt in (segments, segments[:-1]):
        if not attempt:
            break
        listing = out.with_suffix(".txt")
        # Формат concat: file '<путь>', апостроф внутри пути экранируется как '\''
        listing.write_text("".join("file '" + p.as_posix().replace("'", "'\\''") + "'\n" for p in attempt),
                           encoding="utf-8")
        r = ff.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)], timeout=120)
        listing.unlink(missing_ok=True)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return
    raise RuntimeError("FFmpeg не смог склеить запись")


class ReplayRecorder(QObject):
    running_changed = Signal(bool)
    error = Signal(str)
    saved = Signal(object)          # Path
    save_failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.dir = Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}-replay"
        self._proc: subprocess.Popen | None = None
        self._pump = None
        self._opts: ReplayOptions | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._life = threading.Lock()     # старт/стоп выполняются строго по очереди
        self._generation = 0              # номер последнего запроса: устаревшие запросы пропускаются
        self.encoder: str | None = None
        self.running = False
        self.cache_dir: Path | None = None  # где хранить результат проверки кодеров

    # ------------------------------------------------------------ lifecycle
    # start()/stop() не блокируют интерфейс: остановка FFmpeg и ожидание потока
    # (до нескольких секунд) выполняются в фоне, строго по очереди.
    def start(self, opts: ReplayOptions) -> None:
        self._opts = opts
        self._generation += 1
        gen = self._generation
        self._stop.set()
        threading.Thread(target=self._restart, args=(opts, gen), daemon=True).start()

    def _restart(self, opts: ReplayOptions, gen: int) -> None:
        with self._life:
            if gen != self._generation:
                return  # пока ждали очереди, пришёл более новый запрос
            self._stop_blocking()
            stop = threading.Event()
            self._stop = stop
            self._thread = threading.Thread(target=self._run, args=(opts, stop), daemon=True)
            self._thread.start()

    def stop(self, wait: bool = False) -> None:
        """wait=True — дождаться полной остановки (при выходе из программы)."""
        self._generation += 1
        gen = self._generation
        self._stop.set()
        if wait:
            with self._life:
                self._stop_blocking(join_timeout=3)  # при выходе долго не ждём: потоки фоновые
            return

        def work() -> None:
            with self._life:
                if gen == self._generation:
                    self._stop_blocking()

        threading.Thread(target=work, daemon=True).start()

    def _stop_blocking(self, join_timeout: float = 20) -> None:
        self._stop.set()
        self._kill()
        if self._thread and self._thread is not threading.current_thread():
            # ждём в фоне, поэтому можно не торопиться: поток может проверять кодеры
            self._thread.join(timeout=join_timeout)
        self._thread = None
        if self.running:
            self.running = False
            self.running_changed.emit(False)
        shutil.rmtree(self.dir, ignore_errors=True)

    def _kill(self) -> None:
        with self._lock:
            proc, pump = self._proc, self._pump
            self._proc = self._pump = None
        if pump:
            pump.stop()
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _run(self, opts: ReplayOptions, stop: threading.Event) -> None:
        exe = ff.find_ffmpeg()
        if not exe:
            self.error.emit("FFmpeg не найден. Запустите scripts/fetch_ffmpeg.py или установите FFmpeg.")
            return
        encoders, has_dda = ff.probe(exe, self.cache_dir)
        attempts = plan_attempts(encoders, sys.platform == "win32" and has_dda)
        if not attempts:
            self.error.emit("Не найден ни один рабочий видеокодер H.264")
            return

        restarts = 0
        idx = 0
        last_err = ""
        reprobed = False
        while not stop.is_set() and idx < len(attempts):
            ok, last_err = self._launch(exe, attempts[idx], opts, stop)
            if not ok:
                idx += 1          # этот кодер/способ не завёлся — пробуем следующий
                if idx == len(attempts) and not reprobed and not stop.is_set():
                    # Всё отказало — возможно, сменился драйвер видеокарты и кэш устарел
                    reprobed = True
                    encoders, has_dda = ff.probe(exe, self.cache_dir, refresh=True)
                    attempts, idx = plan_attempts(encoders, sys.platform == "win32" and has_dda), 0
                continue
            self.encoder = attempts[idx].encoder
            if not self.running:
                self.running = True
                self.running_changed.emit(True)
            # Следим за процессом; если упал посреди работы — перезапускаем
            while not stop.is_set():
                with self._lock:
                    proc = self._proc
                if proc is None or proc.poll() is not None:
                    break
                stop.wait(1.0)
            if stop.is_set():
                return
            last_err = self._log_tail()
            self._kill()
            restarts += 1
            if restarts > 3:
                break
            stop.wait(2.0)
        if not stop.is_set():
            self.running = False
            self.running_changed.emit(False)
            self.error.emit(f"Запись повтора остановлена: {last_err or 'FFmpeg завершился с ошибкой'}")

    def _launch(self, exe: str, attempt: Attempt, opts: ReplayOptions, stop) -> tuple[bool, str]:
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        audio_inputs, pump = self._audio_inputs(exe, opts)
        cmd = build_command(exe, attempt, opts, self.dir, audio_inputs)
        log = open(self.dir / "ffmpeg.log", "wb")  # noqa: SIM115 — открыт, пока пишет FFmpeg
        try:
            # popen_tied: FFmpeg умрёт вместе с Kadr, даже если Kadr завершат принудительно
            proc = popen_tied(cmd, stdin=subprocess.PIPE if pump else subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=log, creationflags=ff.NO_WINDOW)
        except OSError as exc:
            log.close()
            if pump:
                pump.stop()
            return False, str(exc)
        with self._lock:
            if stop.is_set():
                # Пока запускались, нас уже остановили — не оставляем «сиротский» FFmpeg
                orphan = True
            else:
                orphan = False
                self._proc, self._pump = proc, pump
        if orphan:
            if pump:
                pump.stop()
            proc.kill()
            log.close()
            return False, ""
        if pump:
            pump.start(proc.stdin)
        deadline = time.monotonic() + STARTUP_CHECK_S
        while time.monotonic() < deadline and not stop.is_set():
            if proc.poll() is not None:
                log.close()
                err = self._log_tail()
                self._kill()
                return False, err
            time.sleep(0.2)
        log.close()
        return True, ""

    def _audio_inputs(self, exe: str, opts: ReplayOptions):
        inputs: list[list[str]] = []
        pump = None
        if sys.platform == "win32":
            if opts.system_audio:
                try:
                    from .audio_win import LoopbackPump

                    pump = LoopbackPump()
                    pump.open()  # открываем до запуска FFmpeg: если не выйдет — пишем без звука системы
                    inputs.append(pump.ffmpeg_input_args())
                except Exception as exc:
                    if pump:
                        pump.stop()
                    pump = None
                    self.error.emit(f"Звук системы недоступен: {exc}")
            if opts.mic:
                name = opts.mic_device or next(iter(ff.list_microphones(exe)), "")
                if name:
                    inputs.append(["-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50",
                                   "-i", f"audio={name}"])
        else:
            if opts.system_audio:
                inputs.append(["-f", "pulse", "-thread_queue_size", "1024", "-i", ff.linux_monitor_source()])
            if opts.mic:
                inputs.append(["-f", "pulse", "-thread_queue_size", "1024", "-i", opts.mic_device or "default"])
        return inputs, pump

    def _log_tail(self) -> str:
        try:
            lines = (self.dir / "ffmpeg.log").read_text("utf-8", errors="replace").strip().splitlines()
            return lines[-1] if lines else ""
        except OSError:
            return ""

    # ----------------------------------------------------------------- save
    def save(self, save_dir: str) -> None:
        """Сохраняет последние N минут в .mp4 (в фоновом потоке)."""
        if not self.running or not self._opts:
            self.save_failed.emit("Запись повтора не запущена")
            return
        minutes = self._opts.minutes
        threading.Thread(target=self._save, args=(save_dir, minutes), daemon=True).start()

    def _save(self, save_dir: str, minutes: int) -> None:
        try:
            exe = ff.find_ffmpeg()
            # Дожидаемся конца текущего сегмента (≤ SEG секунд): иначе в ролик попал бы
            # недописанный кусок с оборванным последним кадром
            wait_for_rollover(self.dir, SEG + 3)
            segs = collect_segments(self.dir, minutes)
            if not segs:
                raise RuntimeError("Буфер ещё пуст — подождите несколько секунд")
            folder = Path(save_dir).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            out = folder / f"{APP_NAME}_Replay_{stamp}.mp4"
            n = 2
            while out.exists():
                out = folder / f"{APP_NAME}_Replay_{stamp}_{n}.mp4"
                n += 1
            concat_segments(exe, segs, out)
            self.saved.emit(out)
        except Exception as exc:
            self.save_failed.emit(str(exc))
