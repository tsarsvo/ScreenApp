"""История действий рисования (undo / redo).

Действие — добавление фигуры, перемещение нумерованного шага или изменение рамки
(перенос / размер) прямоугольника и овала. Новое действие
очищает стек redo, как в любом редакторе.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .shapes import Shape


def _copy(geom: tuple[QPointF, QPointF]) -> tuple[QPointF, QPointF]:
    return QPointF(geom[0]), QPointF(geom[1])


@dataclass
class Action:
    shape: Shape
    kind: str = "add"                  # add | move | geom
    old_pos: QPointF | None = None     # move: откуда и куда
    new_pos: QPointF | None = None
    old_geom: tuple[QPointF, QPointF] | None = None   # geom: (start, end) до и после
    new_geom: tuple[QPointF, QPointF] | None = None


class History:
    def __init__(self) -> None:
        self._shapes: list[Shape] = []
        self._done: list[Action] = []
        self._undone: list[Action] = []

    @property
    def shapes(self) -> list[Shape]:
        return self._shapes

    def push(self, shape: Shape) -> None:
        self._shapes.append(shape)
        self._record(Action(shape))

    def push_move(self, shape: Shape, old_pos: QPointF, new_pos: QPointF) -> None:
        """Фигура уже передвинута — только запоминаем, чтобы можно было отменить."""
        self._record(Action(shape, "move", QPointF(old_pos), QPointF(new_pos)))

    def push_geom(self, shape: Shape, old: tuple[QPointF, QPointF], new: tuple[QPointF, QPointF]) -> None:
        """Прямоугольник или овал уже передвинут / растянут — запоминаем для отмены."""
        self._record(Action(shape, "geom", old_geom=_copy(old), new_geom=_copy(new)))

    def _record(self, action: Action) -> None:
        self._done.append(action)
        self._undone.clear()

    def undo(self) -> Action | None:
        if not self._done:
            return None
        a = self._done.pop()
        if a.kind == "move":
            a.shape.pos = QPointF(a.old_pos)
        elif a.kind == "geom":
            a.shape.start, a.shape.end = _copy(a.old_geom)
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
        elif a.kind == "geom":
            a.shape.start, a.shape.end = _copy(a.new_geom)
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
