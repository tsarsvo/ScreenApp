"""Точка входа: python main.py [--region | --full | --settings | --save-replay]"""
import os
import sys

# Диагностика зависаний (используется сквозной проверкой в CI): если процесс ещё жив
# через 15 с, в файл KADR_HANG_DUMP.<pid> пишутся стеки всех потоков.
if os.environ.get("KADR_HANG_DUMP"):
    import faulthandler

    _hang_dump = open(f"{os.environ['KADR_HANG_DUMP']}.{os.getpid()}", "w", encoding="utf-8")  # noqa: SIM115
    _hang_dump.write(f"argv: {sys.argv}\n")
    _hang_dump.flush()
    faulthandler.dump_traceback_later(15, file=_hang_dump)

from kadr.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
