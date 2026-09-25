"""Windows: звук системы через WASAPI loopback (pyaudiowpatch) → stdin FFmpeg.

FFmpeg не умеет захватывать WASAPI loopback сам, поэтому звук читаем здесь и
передаём сырым PCM. Когда ничего не играет, WASAPI loopback вообще не отдаёт
данные — тогда досылаем тишину по часам, иначе звук «съедется» с видео.
"""
from __future__ import annotations

import queue
import threading
import time


class LoopbackPump:
    CHUNK_MS = 20

    def __init__(self) -> None:
        import pyaudiowpatch as pyaudio

        self._pa_mod = pyaudio
        self._pa = pyaudio.PyAudio()
        self._device = self._default_loopback()
        self.rate = int(self._device["defaultSampleRate"])
        self.channels = int(self._device["maxInputChannels"]) or 2
        self._q: queue.Queue[bytes] = queue.Queue()
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _default_loopback(self) -> dict:
        wasapi = self._pa.get_host_api_info_by_type(self._pa_mod.paWASAPI)
        speakers = self._pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if speakers.get("isLoopbackDevice"):
            return speakers
        for lb in self._pa.get_loopback_device_info_generator():
            if speakers["name"] in lb["name"]:
                return lb
        raise RuntimeError("Не найдено loopback-устройство для колонок по умолчанию")

    def ffmpeg_input_args(self) -> list[str]:
        return ["-f", "s16le", "-ar", str(self.rate), "-ac", str(self.channels),
                "-thread_queue_size", "4096", "-i", "pipe:0"]

    def _callback(self, data, _frames, _time, _status):
        self._q.put(data)
        return (None, self._pa_mod.paContinue)

    def open(self) -> None:
        """Открывает WASAPI-поток. Бросает исключение, если устройство недоступно."""
        self._stream = self._pa.open(
            format=self._pa_mod.paInt16, channels=self.channels, rate=self.rate, input=True,
            input_device_index=self._device["index"],
            frames_per_buffer=self.rate * self.CHUNK_MS // 1000, stream_callback=self._callback)

    def start(self, sink) -> None:
        """sink — бинарный поток (stdin процесса FFmpeg)."""
        while not self._q.empty():  # отбрасываем звук, накопленный до старта FFmpeg
            self._q.get_nowait()
        self._thread = threading.Thread(target=self._pump, args=(sink,), daemon=True)
        self._thread.start()

    def _pump(self, sink) -> None:
        frame_bytes = 2 * self.channels
        written = 0
        t0 = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    data = self._q.get(timeout=self.CHUNK_MS / 1000)
                    sink.write(data)
                    written += len(data) // frame_bytes
                except queue.Empty:
                    pass
                # Досылаем тишину, если отстали от реального времени больше чем на 60 мс
                expected = int((time.monotonic() - t0) * self.rate)
                lag = expected - written
                if lag > self.rate * 0.06 and self._q.empty():
                    sink.write(b"\x00" * (lag * frame_bytes))
                    written += lag
                sink.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass  # FFmpeg остановлен

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1)
        self._pa.terminate()
