"""Запуск дочернего процесса (FFmpeg), который гарантированно умирает вместе с Kadr.

Обычный выход из программы останавливает запись сам. Но если Kadr завершили
принудительно (Диспетчер задач, сбой, выключение ПК), FFmpeg без этой привязки
продолжил бы писать экран «сиротой».

* Windows — Job Object с флагом KILL_ON_JOB_CLOSE: когда процесс Kadr исчезает,
  система закрывает его дескриптор задания и завершает все процессы в нём.
* Linux — prctl(PR_SET_PDEATHSIG, SIGKILL): ядро убивает ребёнка при смерти родителя.
"""
from __future__ import annotations

import subprocess
import sys

_job = None  # дескриптор Job Object живёт до конца процесса Kadr — закрывать его нельзя


def _windows_job():
    global _job
    if _job is not None:
        return _job
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
    info = EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    _job = (kernel32, job)
    return _job


def _linux_die_with_parent() -> None:
    """Выполняется в дочернем процессе перед exec."""
    import ctypes
    import signal

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


def popen_tied(cmd: list[str], **kwargs) -> subprocess.Popen:
    """subprocess.Popen, но ребёнок не переживёт родителя."""
    if sys.platform.startswith("linux"):
        kwargs.setdefault("preexec_fn", _linux_die_with_parent)
    proc = subprocess.Popen(cmd, **kwargs)
    if sys.platform == "win32":
        try:
            kernel32, job = _windows_job()
            kernel32.AssignProcessToJobObject(job, int(proc._handle))
        except OSError:
            pass  # не критично: при обычном выходе запись всё равно останавливается
    return proc
