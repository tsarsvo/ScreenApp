"""История действий рисования (undo / redo).

Каждое действие — это добавление готовой фигуры. Новая фигура очищает стек redo,
как в любом редакторе.
"""
from __future__ import annotations

from .shapes import Shape


class History:
    def __init__(self) -> None:
        self._done: list[Shape] = []
        self._undone: list[Shape] = []

    @property
    def shapes(self) -> list[Shape]:
        return self._done

    def push(self, shape: Shape) -> None:
        self._done.append(shape)
        self._undone.clear()

    def undo(self) -> bool:
        if not self._done:
            return False
        self._undone.append(self._done.pop())
        return True

    def redo(self) -> bool:
        if not self._undone:
            return False
        self._done.append(self._undone.pop())
        return True

    def can_undo(self) -> bool:
        return bool(self._done)

    def can_redo(self) -> bool:
        return bool(self._undone)

    def __bool__(self) -> bool:
        return bool(self._done)
