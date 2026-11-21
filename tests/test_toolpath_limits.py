"""Toolpath limits (B30, B31, B32): a contour block cuts only between its Z limits and not beyond its X limit, a facing block stops at its
X limit; the contour stays as drawn and the material beyond the limits stays for another block."""

import unittest

from tests.helpers import simple_tool
from wop.core.blocks.base import BlockContext, BlockError, Safety
from wop.core.blocks.facing import FacingBlock, FacingDirection
from wop.core.blocks.toolpath_limits import ToolpathLimits, limited_path
from wop.core.blocks.turning_common import TurningSide
from wop.core.blocks.turning_contour import ContourTurningBlock
from wop.core.contour import ContourDefinition, LineStep
from wop.core.contour_solver import build_contour
from wop.core.geometry import LineSegment, Point
from wop.core.program_model.operations import LinearMove, SpindleMode, SpindleSetting
from wop.core.program_model.raw_part import RawPart
from wop.core.program_model.stock import stock_region
from wop.ui.svg_preview import render_svg

SPINDLE = SpindleSetting(SpindleMode.CONSTANT_RPM, 1000)
TOL = 1e-6
ALLOWANCE = 0.2

# a shaft with a neck (radius 5) between two diameters, on a bar of radius 15
SHAFT = ((0, 0), (8, 0), (8, -20), (5, -20), (5, -35), (10, -35), (10, -50))


def contour_of(points):
    steps = tuple(LineStep(Point(x, z)) for x, z in points[1:])
    return build_contour("c", "shaft", ContourDefinition(Point(*points[0]), steps))


def context(shape=None):
    raw = RawPart("steel", 30, 60)
    safety = Safety(safe_radius_mm=25, safe_z_mm=10, clearance_mm=1)
    return BlockContext(raw, simple_tool(1), stock_region(raw), safety, contours=(shape,) if shape else ())


def contour_block(shape, **limits):
    return ContourTurningBlock(
        block_id="c1", tool_number=1, spindle=SPINDLE, contour_id=shape.contour_id, side=TurningSide.OUTSIDE,
        feed_mm_per_rev=0.25, depth_of_cut_mm=2, finish_allowance_mm=ALLOWANCE, **limits,
    )


def cuts(result):
    return [op for op in result.operations if isinstance(op, LinearMove)]


class LimitedPathTests(unittest.TestCase):
    def setUp(self):
        self.path = list(contour_of(SHAFT).segments)

    def ends(self, limits):
        return [(round(s.start.x, 6), round(s.start.z, 6), round(s.end.x, 6), round(s.end.z, 6)) for s in limited_path(self.path, limits, True)]

    def test_no_limits_keeps_the_contour(self):
        self.assertEqual(len(self.ends(ToolpathLimits())), len(self.path))

    def test_a_z_minus_limit_ends_the_path_on_the_contour(self):
        self.assertEqual(self.ends(ToolpathLimits(z_minus=-10)), [(0, 0, 8, 0), (8, 0, 8, -10)])

    def test_a_z_plus_limit_starts_the_path_on_the_contour(self):
        self.assertEqual(self.ends(ToolpathLimits(z_plus=-40)), [(10, -40, 10, -50)])

    def test_the_x_limit_runs_straight_over_the_neck(self):
        self.assertEqual(self.ends(ToolpathLimits(x_radius=6)), [(6, 0, 8, 0), (8, 0, 8, -20), (8, -20, 6, -20), (6, -20, 6, -35), (6, -35, 10, -35), (10, -35, 10, -50)])

    def test_nothing_between_the_limits_gives_no_path(self):
        self.assertEqual(self.ends(ToolpathLimits(z_plus=-60)), [])

    def test_limits_that_cross_are_refused(self):
        with self.assertRaises(BlockError):
            contour_block(contour_of(SHAFT), z_plus_limit_mm=-30, z_minus_limit_mm=-20)


class ContourBlockLimitTests(unittest.TestCase):
    def setUp(self):
        self.shape = contour_of(SHAFT)
        self.whole = contour_block(self.shape).generate(context(self.shape))

    def test_a_z_minus_limit_cuts_only_in_front_of_it(self):
        result = contour_block(self.shape, z_minus_limit_mm=-15).generate(context(self.shape))
        self.assertGreaterEqual(min(op.end.z for op in cuts(result)), -15 - TOL)
        self.assertGreaterEqual(result.removed.bounds.min_z, -15 - TOL)
        self.assertLess(result.removed.area, self.whole.removed.area)
        self.assertTrue(any("limited to Z- -15" in note for note in result.messages))

    def test_the_finishing_pass_does_not_cut_up_a_z_minus_limit(self):
        result = contour_block(self.shape, z_minus_limit_mm=-15).generate(context(self.shape))
        climbs = [op for op in cuts(result) if abs(op.end.z + 15) <= TOL and op.end.x > 8 + TOL]
        self.assertEqual(climbs, [])
        self.assertTrue(any(op.end.is_close(Point(9, -14)) for op in cuts(result)), "away at 45 degrees by the clearance")

    def test_a_z_plus_limit_cuts_only_behind_it(self):
        result = contour_block(self.shape, z_plus_limit_mm=-38).generate(context(self.shape))
        self.assertLessEqual(max(op.end.z for op in cuts(result)), -38 + TOL)
        self.assertLess(result.removed.area, self.whole.removed.area)

    def test_the_x_limit_leaves_the_neck_and_finishes_straight_over_it(self):
        result = contour_block(self.shape, x_limit_radius_mm=6).generate(context(self.shape))
        self.assertGreaterEqual(result.removed.bounds.min_x, 6 - TOL)
        neck = [op for op in cuts(result) if abs(op.end.z + 35) <= TOL and abs(op.end.x - 6) <= TOL]
        self.assertTrue(neck, "the finishing pass runs along the X limit over the neck")

    def test_the_part_as_drawn_stays_protected(self):
        result = contour_block(self.shape, z_minus_limit_mm=-15).generate(context(self.shape))
        self.assertAlmostEqual(result.protected.area, self.whole.protected.area, delta=0.05)

    def test_the_picture_lines_of_the_limits(self):
        block = contour_block(self.shape, z_plus_limit_mm=-10, z_minus_limit_mm=-40, x_limit_radius_mm=6)
        lines = block.limit_lines(context(self.shape))
        self.assertEqual(len(lines), 3)
        self.assertEqual({round(line.start.z, 6) for line in lines[:2]}, {-10, -40})
        self.assertEqual(contour_block(self.shape).limit_lines(context(self.shape)), ())


class FacingLimitTests(unittest.TestCase):
    def test_facing_stops_at_the_x_limit_both_ways(self):
        for direction in FacingDirection:
            for finish in (False, True):
                with self.subTest(direction=direction, finish=finish):
                    block = FacingBlock(
                        block_id="f", tool_number=1, spindle=SPINDLE, target_z_mm=-2, feed_mm_per_rev=0.2, depth_of_cut_mm=1,
                        overtravel_mm=0.8, direction=direction, x_limit_radius_mm=5, finish_pass=finish, finish_allowance_mm=0.2 if finish else 0,
                    )
                    result = block.generate(context())
                    self.assertGreaterEqual(min(op.end.x for op in cuts(result)), 5 - TOL)
                    self.assertGreaterEqual(result.removed.bounds.min_x, 5 - TOL)
                    self.assertTrue(any("limited to X 10" in note for note in result.messages))

    def test_the_overtravel_is_greyed_with_a_limit(self):
        block = FacingBlock(block_id="f", tool_number=1, spindle=SPINDLE, target_z_mm=-2, feed_mm_per_rev=0.2, depth_of_cut_mm=1, x_limit_radius_mm=5)
        self.assertIn("overtravel_mm", block.form_disabled())


class PictureTests(unittest.TestCase):
    def test_the_limits_are_drawn_dashed_only_when_given(self):
        from tests import svg_demo
        from wop.core.program_model.program import plan_program

        plan = plan_program(svg_demo.outside_program())
        svg = render_svg(plan, limits=(LineSegment(Point(16, -10), Point(0, -10)),))
        self.assertIn('class="toolpath-limit"', svg)
        self.assertNotIn('class="toolpath-limit"', render_svg(plan))


if __name__ == "__main__":
    unittest.main()
