"""The check follows an arc of a large radius as straight chords (the user's crowned roller, 2026-11-23: an arc of a 30 m radius over
492 mm took minutes for every change; the user: "any arc above 200mm to a few chords")."""

import time
import unittest
from pathlib import Path

from wop.adapters.project_files import load_project
from wop.core.geometry import ArcDirection, Point
from wop.core.program_model.operations import ArcMove, LinearMove
from wop.core.program_model.program import plan_program
from wop.core.verify import _with_flat_arcs_as_chords, verify_plan

PROJECT = Path(__file__).parent / "data" / "projects" / "crowned_roller.wop.json"


class FlatArcTests(unittest.TestCase):
    def test_an_arc_of_200_mm_or_more_becomes_chords_of_one_move_and_a_fillet_stays(self):
        big = ArcMove(Point(17, -100), Point(-183, -50), ArcDirection.CW, 0.1)  # radius 200 (start at (17, 0))
        small = ArcMove(Point(18, -1), Point(17, -1), ArcDirection.CCW, 0.1)
        moves = _with_flat_arcs_as_chords([(0, big)], Point(17, 0))
        self.assertGreater(len(moves), 2)
        self.assertTrue(all(isinstance(move, LinearMove) for _i, move, _same in moves))
        self.assertEqual([same for _i, _m, same in moves][:2], [False, True])
        self.assertAlmostEqual(moves[-1][1].end.distance_to(big.end), 0, places=9)
        self.assertEqual(_with_flat_arcs_as_chords([(0, small)], Point(17, 0)), [(0, small, False)])

    def test_the_roller_is_checked_in_seconds(self):
        program = load_project(PROJECT).program
        plan = plan_program(program)
        start = time.perf_counter()
        verify_plan(program, plan)
        self.assertLess(time.perf_counter() - start, 20)


if __name__ == "__main__":
    unittest.main()
