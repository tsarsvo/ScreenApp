"""История действий рисования (undo / redo).

Действие — добавление фигуры (возможно, с расширением выделения, если фигура
вышла за его край) или перемещение нумерованного шага. Новое действие очищает
стек redo, как в любом редакторе.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect

from .shapes import Shape


@dataclass
class Action:
    shape: Shape
    kind: str = "add"                  # add | move
    old_pos: QPointF | None = None     # move: откуда и куда
    new_pos: QPointF | None = None
    sel_before: QRect | None = None    # add: выделение до расширения (None — не менялось)
    sel_after: QRect | None = None


class History:
    def __init__(self) -> None:
        self._shapes: list[Shape] = []
        self._done: list[Action] = []
        self._undone: list[Action] = []

    @property
    def shapes(self) -> list[Shape]:
        return self._shapes

    def push(self, shape: Shape, sel_before: QRect | None = None, sel_after: QRect | None = None) -> None:
        self._shapes.append(shape)
        self._record(Action(shape, sel_before=sel_before, sel_after=sel_after))

    def push_move(self, shape: Shape, old_pos: QPointF, new_pos: QPointF) -> None:
        """Фигура уже передвинута — только запоминаем, чтобы можно было отменить."""
        self._record(Action(shape, "move", QPointF(old_pos), QPointF(new_pos)))

    def _record(self, action: Action) -> None:
        self._done.append(action)
        self._undone.clear()

    def undo(self) -> Action | None:
        if not self._done:
            return None
        a = self._done.pop()
        if a.kind == "move":
            a.shape.pos = QPointF(a.old_pos)
        else:
            # по идентичности, а не ==: две одинаковые фигуры (dataclass) равны
            idx = next(i for i in range(len(self._shapes) - 1, -1, -1) if self._shapes[i] is a.shape)
            del self._shapes[idx]
        self._undone.append(a)
        return a

    def redo(self) -> Action | None:
        if not self._undone:
            return None
        a = self._undone.pop()
        if a.kind == "move":
            a.shape.pos = QPointF(a.new_pos)
        else:
            self._shapes.append(a.shape)
        self._done.append(a)
        return a

    def can_undo(self) -> bool:
        return bool(self._done)

    def can_redo(self) -> bool:
        return bool(self._undone)

    def __bool__(self) -> bool:
        return bool(self._shapes)
