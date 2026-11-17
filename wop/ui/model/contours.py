"""Contours in the program: the chosen one, new, copy, delete."""

from __future__ import annotations

from dataclasses import replace
from ...core.blocks.base import BlockError, NO_CONTOUR
from ...core.contour import Contour
from ...core.sketch.model import SketchError
from ...core.sketch.modes import TURNING, contour_from_sketch, sketch_from_contour
from ...core.sketch.points_profile import ProfileError, ProfileRow, rows_from_sketch, sketch_from_rows
from .helpers import ModelError

NEW_CONTOUR_NOTE = "the contour is not drawn yet: use Sketch editor..."


class ContoursMixin:
    """Contours in the program: the chosen one, new, copy, delete. (A part of AppModel: it uses the attributes that AppModel.__init__ sets.)"""

    def select_contour(self, contour_id: str | None) -> None:
        """Choose a contour (None: none). The blocks are deselected."""
        self.selected = None
        self.tools_view = False
        self.workholding_view = False
        self.selected_contour = contour_id
        if contour_id is not None and not any(c.contour_id == contour_id for c in self.program.contours):
            self.selected_contour = None
        self._notify()

    def _drop_missing_contour(self) -> None:
        """After any change (Undo, delete ...): no contour is chosen when the chosen one is gone."""
        if self.selected_contour is not None and not any(c.contour_id == self.selected_contour for c in self.program.contours):
            self.selected_contour = None

    def new_contour(self) -> str:
        """Add an empty contour (it is not valid until it is drawn in the sketch editor) and choose it."""
        contour_id = self.next_contour_id()
        self.set_contour(Contour(contour_id, f"Contour {len(self.program.contours) + 1}", (), None, NEW_CONTOUR_NOTE))
        self.select_contour(contour_id)
        return contour_id

    def chosen_contour(self) -> Contour | None:
        return next((c for c in self.program.contours if c.contour_id == self.selected_contour), None)

    def rename_contour(self, contour_id: str, name: str) -> None:
        found = next((c for c in self.program.contours if c.contour_id == contour_id), None)
        if found is None:
            raise ModelError(f"there is no contour {contour_id!r}")
        self.set_contour(replace(found, name=name))

    def set_contour(self, contour: Contour) -> None:
        self.project = replace(self.project, program=self.program.with_contour(contour))
        self._changed()

    def contour_users(self, contour_id: str) -> tuple[int, ...]:
        """Positions of the blocks that use a contour."""
        return tuple(i for i, block in enumerate(self.blocks) if contour_id in block.contour_ids)

    def delete_contour(self, contour_id: str, with_blocks: bool) -> None:
        """Delete a contour that blocks may use (C9).

        with_blocks: the blocks that use it are deleted too; otherwise they stay without a contour.
        """
        users = self.contour_users(contour_id)
        if with_blocks:
            for index in reversed(users):
                self.delete_block(index)
        else:
            blocks = tuple(
                replace(block, contour_id=NO_CONTOUR) if contour_id in block.contour_ids else block
                for block in self.blocks
            )
            self.project = replace(self.project, program=replace(self.program, blocks=blocks))
        self.project = replace(self.project, program=self.program.without_contour(contour_id))
        self._changed()

    def copy_contour(self, contour_id: str) -> str:
        """Put a copy of a contour right after it (new id, name with " copy") and choose it. Blocks keep the original."""
        contours = self.program.contours
        known = [c.contour_id for c in contours]
        if contour_id not in known:
            raise ModelError(f"there is no contour {contour_id!r}")
        position = known.index(contour_id) + 1
        source = contours[position - 1]
        copy = replace(source, contour_id=self.next_contour_id(), name=f"{source.name} copy")
        program = replace(self.program, contours=contours[:position] + (copy,) + contours[position:])
        self.project = replace(self.project, program=program)
        self._changed()
        self.select_contour(copy.contour_id)
        return copy.contour_id

    def contour_from_rows(self, rows: list[ProfileRow], contour_id: str | None = None) -> str:
        """A contour typed as points (C12): a new one (None) or the contour `contour_id` drawn again from the rows; it is chosen.
        Raises ModelError with the reason when the rows make no contour."""
        stored = next((c for c in self.program.contours if c.contour_id == contour_id), None)
        if contour_id is not None and stored is None:
            raise ModelError(f"there is no contour {contour_id!r}")
        try:
            sketch = sketch_from_rows(rows)
            new_id = contour_id or self.next_contour_id()
            name = stored.name if stored is not None else f"Contour {len(self.program.contours) + 1}"
            contour = contour_from_sketch(sketch, TURNING, new_id, name)
        except (ProfileError, SketchError) as error:
            raise ModelError(str(error)) from None
        self.set_contour(contour)
        self.select_contour(new_id)
        return new_id

    def contour_rows(self, contour_id: str) -> list[ProfileRow]:
        """The contour as points (C12), front first. Raises ModelError when it cannot be written as points (an arc that is not a corner)."""
        stored = next((c for c in self.program.contours if c.contour_id == contour_id), None)
        if stored is None:
            raise ModelError(f"there is no contour {contour_id!r}")
        if not stored.segments:
            return []
        try:
            return rows_from_sketch(sketch_from_contour(stored))
        except (ProfileError, SketchError) as error:
            raise ModelError(str(error)) from None

    def block_note(self, index: int) -> str:
        """A short note for the flow list, for example "no contour set" (C10); empty if all is well."""
        self._check_index(index)
        return self.program.contour_problem(self.blocks[index]) or self.function_problem(self.blocks[index])

    def remove_contour(self, contour_id: str) -> None:
        try:
            program = self.program.without_contour(contour_id)
        except BlockError as error:
            raise ModelError(str(error)) from error
        self.project = replace(self.project, program=program)
        self._changed()

    def next_contour_id(self) -> str:
        used = {c.contour_id for c in self.program.contours}
        number = len(used) + 1
        while f"contour{number}" in used:
            number += 1
        return f"contour{number}"
