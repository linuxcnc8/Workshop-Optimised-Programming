"""Plunge mode of the finishing pass of a contour block (B33, `wop/core/analytic/finish_modes.py`) and the stock in front of a Z+ limit
(B30): the user's bolt (the contour of his STEP part, front at the thread) with the TNMG R0.8 in a 91-degree holder, whose back edge leaves
only about 24 degrees (with the back clearance) for a wall going down: the 45-degree chamfer into the neck is too steep, and the face down to
the centre at Z -152.4 has the bar behind it."""

import unittest
from dataclasses import replace
from pathlib import Path

from wop.adapters.project_files import load_project
from wop.core.analytic.finish_modes import PlungeMode, no_plunge
from wop.core.blocks.base import BlockError
from wop.core.geometry import LineSegment, Point
from wop.core.program_model.operations import ArcMove, LinearMove
from wop.core.program_model.program import plan_program
from wop.core.verify import verify_plan

PROJECT = Path(__file__).parent / "data" / "projects" / "bolt_z_minus_limit.wop.json"
TOL = 1e-6


def planned(**changes):
    program = load_project(PROJECT).program
    block = replace(program.blocks[0], **{"z_minus_limit_mm": None, **changes})
    program = replace(program, blocks=(block,))
    plan = plan_program(program)
    return plan, [str(getattr(f, "message", f)) for f in verify_plan(program, plan)]


def finishing(plan):
    """The feed moves after the last rapid in to the part (the finishing pass and its way away)."""
    ops = list(plan.operations)
    rapids = [i for i, op in enumerate(ops) if type(op).__name__ == "Rapid"]
    begin = max(i for i in rapids if i < len(ops) - 4 and ops[i + 1].__class__ in (LinearMove, ArcMove))
    return [op for op in ops[begin:] if isinstance(op, (LinearMove, ArcMove))]


class PlungeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.free = planned()
        cls.shape = planned(plunge_mode=PlungeMode.TOOL_SHAPE)
        cls.straight = planned(plunge_mode=PlungeMode.NO_PLUNGE)

    def test_free_follows_the_contour_and_the_check_reports_the_back_of_the_tool(self):
        self.assertTrue(any("cuts into the finished part" in finding for finding in self.free[1]))

    def test_tool_shape_has_no_collision(self):
        self.assertEqual(self.shape[1], [])

    def test_tool_shape_runs_down_the_back_of_the_tool_into_the_neck(self):
        moves = finishing(self.shape[0])
        neck = [op for op in moves if abs(op.end.x - 4.75) <= TOL]
        self.assertTrue(neck, "the pass still reaches the bottom of the neck")
        self.assertLess(max(op.end.z for op in neck), -11.2, "but later than the 45-degree chamfer would (Z -10)")

    def test_tool_shape_does_not_part_off_into_the_bar(self):
        self.assertGreater(min(op.end.x for op in finishing(self.shape[0]) if op.end.z < -150), 3)

    def test_tool_shape_says_what_it_leaves(self):
        self.assertTrue(any("plunge mode 'tool shape'" in note and "not finished" in note for note in self.shape[0].messages))

    def test_dont_plunge_never_goes_towards_the_part_on_its_way(self):
        moves = [op for op in finishing(self.straight[0]) if -150 < op.end.z < -2.4]
        self.assertGreaterEqual(min(op.end.x for op in moves), 6.3 - TOL)  # straight over the neck at the diameter
        self.assertEqual(self.straight[1], [])

    def test_dont_plunge_roughs_nothing_in_the_neck_either(self):
        # the user, 2026-11-23: "it would be nice to apply it to roughing also"
        moves = [op for op in self.straight[0].operations if isinstance(op, (LinearMove, ArcMove))]
        self.assertFalse([op for op in moves if -24 < op.end.z < -12 and op.end.x < 6.3 - TOL])

    def test_a_plunge_mode_needs_cutter_compensation_off(self):
        block = load_project(PROJECT).program.blocks[0]
        with self.assertRaises(BlockError):
            replace(block, plunge_mode=PlungeMode.TOOL_SHAPE, cutter_compensation=True)


class FinishingOnlyTests(unittest.TestCase):
    """Roughing unticked (B35, the user 2026-11-23: "i don't have a option for a separate finish pass yet")."""

    def test_a_block_after_the_roughing_makes_only_the_finishing_pass(self):
        program = load_project(PROJECT).program
        rough = replace(program.blocks[0], z_minus_limit_mm=None, finish_pass=False, plunge_mode=PlungeMode.TOOL_SHAPE)
        finish = replace(rough, block_id="f", roughing=False, finish_pass=True)
        both = plan_program(replace(program, blocks=(rough, finish)))
        alone = plan_program(replace(program, blocks=(rough,)))
        moves = [op for op in both.blocks[1].operations if isinstance(op, (LinearMove, ArcMove))]
        self.assertLess(len(moves), 40, "one pass along the contour, no roughing lines")
        self.assertLess(both.blocks[1].result.removed.area, alone.blocks[0].result.removed.area / 10)
        self.assertFalse([m for m in both.messages if "more than the finishing allowance" in m])

    def test_on_uncut_stock_it_says_so(self):
        program = load_project(PROJECT).program
        finish = replace(program.blocks[0], z_minus_limit_mm=None, roughing=False, plunge_mode=PlungeMode.TOOL_SHAPE)
        self.assertTrue([m for m in plan_program(replace(program, blocks=(finish,))).messages if "more than the finishing allowance" in m])

    def test_both_off_is_refused(self):
        with self.assertRaises(BlockError):
            replace(load_project(PROJECT).program.blocks[0], roughing=False, finish_pass=False)


class NoPlungeWalkTests(unittest.TestCase):
    def test_a_neck_is_bridged_at_the_height_before_it(self):
        path = [LineSegment(Point(8, 0), Point(8, -10)), LineSegment(Point(8, -10), Point(5, -10)), LineSegment(Point(5, -10), Point(5, -20)),
                LineSegment(Point(5, -20), Point(10, -20)), LineSegment(Point(10, -20), Point(10, -30))]
        walked = no_plunge(list(enumerate(path)), True)
        self.assertEqual([(round(s.start.x, 6), round(s.start.z, 6), round(s.end.x, 6), round(s.end.z, 6)) for _i, s in walked],
                         [(8, 0, 8, -20), (8, -20, 10, -20), (10, -20, 10, -30)])


class ZPlusLimitTests(unittest.TestCase):
    """The user, 2026-11-23: "the idea is that the stock outside the limits is not cut"."""

    @classmethod
    def setUpClass(cls):
        cls.plan, cls.findings = planned(z_plus_limit_mm=-40, z_minus_limit_mm=-110, plunge_mode=PlungeMode.TOOL_SHAPE)

    def test_no_move_cuts_in_front_of_the_limit_below_the_stock(self):
        moves = [op for op in self.plan.operations if isinstance(op, (LinearMove, ArcMove))]
        self.assertFalse([op for op in moves if op.end.z > -40 + TOL and op.end.x < 12.5 - TOL])

    def test_what_the_tool_cannot_reach_behind_the_stock_is_left_with_a_note(self):
        self.assertTrue(any("is not cut: the tool cannot reach it" in note for note in self.plan.messages))
        self.assertEqual(self.findings, [])


if __name__ == "__main__":
    unittest.main()
