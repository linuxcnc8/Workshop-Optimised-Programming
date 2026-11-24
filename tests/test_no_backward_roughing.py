"""The roughing never feeds back up a slope towards the front (the user, 2026-11-25, on the big blue lathe: "the tool paths are a mess. i even
found some backwards cutting"). The crowned roller (one arc of 15 m radius, 492 mm long) had two: the pass over the crown stopped on its top
(its ride began four thousandths below its level, so the line behind the crown at the same radius counted as higher), and the passes down the
far side climbed back up the crown, as there is no wall behind it. The pawn had one too (down an arc, back up 3 mm)."""

import unittest
from pathlib import Path

from wop.adapters.project_files import load_project
from wop.core.program_model.operations import ArcMove, LinearMove
from wop.core.program_model.program import plan_program

PROJECTS = Path(__file__).parent / "data" / "projects"


def _feed_moves(path: Path, block: int):
    """(start, end) of every feed move of a block, in order."""
    plan = plan_program(load_project(path).program)
    here, moves = None, []
    for operation in plan.blocks[block].operations:
        end = getattr(operation, "end", None)
        if isinstance(operation, (LinearMove, ArcMove)) and here is not None:
            moves.append((here, end))
        if end is not None:
            here = end
    return moves


class NoBackwardRoughingTests(unittest.TestCase):
    def test_the_crowned_roller_cuts_only_towards_the_chuck(self):
        moves = _feed_moves(PROJECTS / "crowned_roller.wop.json", 0)
        backwards = [(a, b) for a, b in moves if b.z - a.z > 1.0]
        self.assertEqual(backwards, [])

    def test_the_pass_goes_over_the_crown_in_one_cut(self):
        moves = _feed_moves(PROJECTS / "crowned_roller.wop.json", 0)
        over = [b for a, b in moves if a.z > -246.0 > b.z and b.z < -400]  # from the front half over the top to far down the other side
        self.assertTrue(over, "no cut runs over the top of the crown")


if __name__ == "__main__":
    unittest.main()
