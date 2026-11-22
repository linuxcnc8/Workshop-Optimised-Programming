"""Finishing allowance with its own value in X and in Z on a contour block (B34, `wop/core/analytic/allowance_xz.py`): X is typed as a
diameter in diameter mode (the user: "i want X in dia"), an empty Z is the same as X per side."""

import unittest
from dataclasses import replace
from pathlib import Path

from wop.adapters.project_files import load_project
from wop.core.analytic.allowance_xz import pushed
from wop.core.geometry import LineSegment, Point
from wop.core.program_model.operations import LinearMove
from wop.core.program_model.program import plan_program
from wop.core.program_model.units import XInputMode
from wop.ui.block_forms import form_for, from_display, to_display

PROJECT = Path(__file__).parent / "data" / "projects" / "bolt_z_minus_limit.wop.json"
STEP = [LineSegment(Point(0, 0), Point(8, 0)), LineSegment(Point(8, 0), Point(8, -10)), LineSegment(Point(8, -10), Point(10, -10)),
        LineSegment(Point(10, -10), Point(10, -20)), LineSegment(Point(10, -20), Point(6, -24)), LineSegment(Point(6, -24), Point(6, -30))]


def ends(path):
    return [(round(s.start.x, 6), round(s.start.z, 6), round(s.end.x, 6), round(s.end.z, 6)) for s in path]


class PushTests(unittest.TestCase):
    def test_equal_allowances_push_nothing(self):
        self.assertEqual(ends(pushed(STEP, 0.3, 0.3, True)), ends(STEP))

    def test_more_in_x_lifts_the_diameters_and_the_slopes_and_stretches_the_faces(self):
        self.assertEqual(ends(pushed(STEP, 0.5, 0.2, True)), [
            (0, 0, 8, 0), (8, 0, 8.3, 0), (8.3, 0, 8.3, -10), (8.3, -10, 10, -10), (10, -10, 10.3, -10), (10.3, -10, 10.3, -20),
            (10.3, -20, 6.3, -24), (6.3, -24, 6.3, -30)])

    def test_more_in_z_moves_the_faces_and_the_slopes(self):
        self.assertEqual(ends(pushed(STEP, 0.2, 0.5, True)), [
            (0, 0.3, 8, 0.3), (8, 0.3, 8, 0), (8, 0, 8, -9.7), (8, -9.7, 10, -9.7), (10, -9.7, 10, -10), (10, -10, 10, -20),
            (10, -20, 10, -20.3), (10, -20.3, 6, -24.3), (6, -24.3, 6, -30)])


class BlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        program = load_project(PROJECT).program
        cls.program = program
        cls.block = replace(program.blocks[0], z_minus_limit_mm=None)

    def plan(self, **changes):
        return plan_program(replace(self.program, blocks=(replace(self.block, **changes),)))

    def roughing_moves(self, plan):
        moves = [op for op in plan.operations if isinstance(op, LinearMove)]
        return moves

    def test_an_empty_z_is_the_x_allowance(self):
        empty = self.plan(finish_allowance_mm=0.3, finish_allowance_z_mm=None)
        same = self.plan(finish_allowance_mm=0.3, finish_allowance_z_mm=0.3)
        self.assertEqual([op.end for op in empty.operations if hasattr(op, "end")], [op.end for op in same.operations if hasattr(op, "end")])

    def test_the_roughing_leaves_x_on_the_diameter_and_z_on_the_shoulder(self):
        plan = self.plan(finish_allowance_mm=0.1, finish_allowance_z_mm=0.5)
        moves = self.roughing_moves(plan)
        self.assertTrue(any(abs(op.end.x - 6.4) <= 1e-6 for op in moves), "Ø12.6 + 2 x 0.1 on the long diameter")
        self.assertTrue(any(abs(op.end.z + 123.5) <= 1e-6 for op in moves), "the shoulder at Z -124 plus 0.5")
        self.assertFalse(any(6.3 < op.end.x < 6.4 - 1e-6 and -120 < op.end.z < -30 for op in moves))

    def test_x_is_typed_as_a_diameter_in_diameter_mode_and_z_shows_the_x_value_when_empty(self):
        specs = {spec.path[0]: spec for spec in form_for(self.block) if len(spec.path) == 1}
        x = specs["finish_allowance_mm"]
        self.assertTrue(x.is_radius)
        self.assertEqual(to_display(x, 0.2, XInputMode.DIAMETER), 0.4)
        self.assertEqual(from_display(x, 0.4, XInputMode.DIAMETER), 0.2)
        self.assertIn("diameter", x.display_label(XInputMode.DIAMETER))
        self.assertIn("same as X", specs["finish_allowance_z_mm"].placeholder)


if __name__ == "__main__":
    unittest.main()
