"""История действий рисования (undo / redo).

Действие — добавление или удаление фигуры, перемещение нумерованного шага или изменение
геометрии (перенос / размер) прямоугольника, овала, стрелки, линии. Новое действие
очищает стек redo, как в любом редакторе.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF

from .shapes import Shape, set_geometry


@dataclass
class Action:
    shape: Shape
    kind: str = "add"                  # add | del | move | geom
    old_pos: QPointF | None = None     # move: откуда и куда
    new_pos: QPointF | None = None
    old_geom: tuple | None = None      # geom: положение и размер до и после (см. shapes.geometry)
    new_geom: tuple | None = None
    index: int = -1                    # del: где фигура стояла (порядок рисования)
    renumber: list | None = None       # del шага: [(шаг, номер до, номер после)] — номера после него


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

    def remove(self, shape: Shape, renumber: list | None = None) -> None:
        """Удалить фигуру (Del); Ctrl+Z вернёт её на прежнее место в порядке рисования.
        renumber — шаги, которым уже сдвинули номер: отмена вернёт им прежние."""
        idx = self._index(shape)
        del self._shapes[idx]
        self._record(Action(shape, "del", index=idx, renumber=renumber or []))

    def _index(self, shape: Shape) -> int:
        # по идентичности, а не ==: две одинаковые фигуры (dataclass) равны
        return next(i for i in range(len(self._shapes) - 1, -1, -1) if self._shapes[i] is shape)

    def push_geom(self, shape: Shape, old: tuple, new: tuple) -> None:
        """Фигура уже передвинута / растянута — запоминаем для отмены (кортежи из shapes.geometry)."""
        self._record(Action(shape, "geom", old_geom=old, new_geom=new))

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
            set_geometry(a.shape, a.old_geom)
        elif a.kind == "del":
            self._shapes.insert(a.index, a.shape)
            for step, old, _new in a.renumber:
                step.number = old
        else:
            del self._shapes[self._index(a.shape)]
        self._undone.append(a)
        return a

    def redo(self) -> Action | None:
        if not self._undone:
            return None
        a = self._undone.pop()
        if a.kind == "move":
            a.shape.pos = QPointF(a.new_pos)
        elif a.kind == "geom":
            set_geometry(a.shape, a.new_geom)
        elif a.kind == "del":
            del self._shapes[self._index(a.shape)]
            for step, _old, new in a.renumber:
                step.number = new
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
