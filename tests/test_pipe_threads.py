"""Tapered threads (requirement B3): the pipe thread designations (BSPT R / Rc, NPT), the cone of the threading block and
its passes. The numbers of the designations are those of the big-blue lathe's Turning panel (thread_data.py), which were
checked there against ISO 7-1 and ASME B1.20.1."""

from __future__ import annotations

import unittest
from dataclasses import replace

from tests.post_helpers import shipped_post
from wop.core.blocks.base import Safety
from wop.core.blocks.threading import ThreadingBlock
from wop.core.blocks.turning_common import TurningSide
from wop.core.program_model.operations import Rapid, SpindleMode, SpindleSetting, ThreadFeed, ThreadOperation
from wop.core.program_model.program import Program, plan_program
from wop.core.program_model.raw_part import RawPart
from wop.core.program_model.units import XInputMode
from wop.core.thread_designation import BSPT, NPT, ThreadDesignationError, parse_designation
from wop.core.tooling.tool_presets import thread_tool
from wop.core.verify import verify_plan
from wop.post.base import PostError, PostSettings
from wop.post.generate import generate_gcode

SPINDLE = SpindleSetting(SpindleMode.CONSTANT_RPM, 300)


def thread(**overrides) -> ThreadingBlock:
    values = dict(block_id="t1", tool_number=1, spindle=SPINDLE, side=TurningSide.OUTSIDE, crest_radius_mm=10, pitch_mm=1,
                  start_z_mm=0, end_z_mm=-10)
    values.update(overrides)
    return ThreadingBlock(**values)


def designated(text: str, side: TurningSide = TurningSide.OUTSIDE) -> ThreadingBlock:
    blank = thread(side=side)
    return replace(blank, designation=text).with_derived_fields(blank)


class PipeDesignationTests(unittest.TestCase):
    def test_bspt_r_half_inch_as_the_turning_panel(self):
        spec = parse_designation("R 1/2")
        self.assertEqual((spec.designation, spec.family), ("R 1/2", BSPT))
        outside, inside = spec.values_for(True), spec.values_for(False)
        self.assertAlmostEqual(2 * outside.crest_radius_mm, 20.955 - 8.2 / 16)  # gauge diameter less the gauge length at 1:16
        self.assertAlmostEqual(outside.depth_mm, 0.640327 * 25.4 / 14, places=5)
        self.assertEqual((outside.taper_per_100_mm, outside.length_mm), (6.25, 13.2))
        self.assertAlmostEqual(2 * inside.crest_radius_mm, 18.6882, places=4)  # the bore at the face, gauge plane half a pitch behind
        self.assertEqual((inside.taper_per_100_mm, inside.length_mm), (-6.25, 15.0))
        self.assertEqual((outside.flank_half_angle_deg, outside.compound_angle_deg), (27.5, 27.0))

    def test_rc_and_bspt_name_the_same_table(self):
        self.assertEqual(parse_designation("Rc1/2").designation, "Rc 1/2")
        self.assertEqual(parse_designation("bspt 1 1/4").designation, "R 1 1/4")
        self.assertEqual(parse_designation("R 1 1/4").pitch_mm, 25.4 / 11)

    def test_npt_half_inch_from_the_formulas_of_b1_20_1(self):
        for text in ("1/2 NPT", "1/2-14 NPT", "NPT 1/2"):
            spec = parse_designation(text)
            self.assertEqual((spec.designation, spec.family), ("1/2-14 NPT", NPT))
        outside, inside = parse_designation("1/2 NPT").values_for(True), parse_designation("1/2 NPT").values_for(False)
        self.assertAlmostEqual(2 * outside.crest_radius_mm, 20.7155, places=4)  # E0 + 0.8 P at the pipe end
        self.assertAlmostEqual(2 * inside.crest_radius_mm, 18.3207, places=4)  # E1 - 0.8 P at the face (the gauge plane)
        self.assertAlmostEqual(outside.depth_mm, 0.8 * 25.4 / 14)
        self.assertAlmostEqual(outside.length_mm, (0.8 * 0.84 + 6.8) / 14 * 25.4)  # L2
        self.assertEqual(outside.compound_angle_deg, 29.5)

    def test_unknown_sizes_and_wrong_threads_per_inch_are_refused(self):
        with self.assertRaises(ThreadDesignationError):
            parse_designation("R 7/8")
        with self.assertRaises(ThreadDesignationError):
            parse_designation("1/2-18 NPT")

    def test_a_pipe_designation_fills_the_taper_and_the_end_z(self):
        block = designated("R 1/2")
        self.assertEqual((block.taper_per_100_mm, block.end_z_mm), (6.25, -13.2))
        inside = designated("Rc 1/2", TurningSide.INSIDE)
        self.assertEqual((inside.taper_per_100_mm, inside.end_z_mm), (-6.25, -15.0))

    def test_editing_the_taper_by_hand_clears_the_designation(self):
        block = designated("R 1/2")
        self.assertEqual(replace(block, taper_per_100_mm=5).with_derived_fields(block).designation, "")


class TaperedPassTests(unittest.TestCase):
    def test_the_passes_follow_the_cone_and_the_lead_keeps_the_axial_pitch(self):
        operation = ThreadOperation(start_x=11, start_z=3, end_z=-15, pitch_mm=1.5, peak_offset_mm=-1, first_cut_mm=0.3, depth_mm=0.9,
                                    degression=2, compound_angle_deg=0, spring_passes=0, crest_slope=1 / 32)
        feeds = [move for move in operation.pass_moves() if isinstance(move, ThreadFeed)]
        last = feeds[-1].end
        self.assertAlmostEqual(last.x, operation.crest_at(-15) - 0.9)
        self.assertAlmostEqual(feeds[-1].lead_mm, 1.5 * (1 + (1 / 32) ** 2) ** 0.5)

    def test_the_retract_clears_the_larger_end_and_the_tool_comes_back_to_the_start(self):
        operation = ThreadOperation(start_x=11, start_z=3, end_z=-15, pitch_mm=1.5, peak_offset_mm=-1, first_cut_mm=0.3, depth_mm=0.9,
                                    degression=2, compound_angle_deg=0, spring_passes=0, crest_slope=1 / 32)
        moves = operation.pass_moves()
        standing = operation.crest_at(-15)  # the cone is largest at the end
        self.assertAlmostEqual(moves[-3].end.x, standing + 1)  # the last retract keeps the start clearance from it
        self.assertEqual(moves[-1], Rapid(operation.end))


class TaperedBlockTests(unittest.TestCase):
    def program(self, block, raw=None, tool=None):
        return Program(raw_part=raw or RawPart("steel", 20.4, 60), tools=(tool or thread_tool(1, "thread"),),
                       safety=Safety(safe_radius_mm=20, safe_z_mm=10, clearance_mm=1), blocks=(block,))

    def test_an_r_half_inch_thread_plans_and_writes_g33_passes_that_follow_the_cone(self):
        prog = self.program(designated("R 1/2"))
        plan = plan_program(prog)
        self.assertTrue([op for op in plan.blocks[0].operations if isinstance(op, ThreadOperation)])  # planned, not refused
        self.assertEqual(verify_plan(prog, plan), [])
        engine = shipped_post()
        post = type(engine)(replace(engine.definition, settings=replace(engine.definition.settings, threading_style="synced_passes")))
        text = generate_gcode(plan, post, PostSettings(XInputMode.DIAMETER)).text
        self.assertIn("Z-13.2 K1.815171", text)  # the full depth ends on the end Z of the standard, the lead along the cone

    def test_a_g76_post_refuses_a_tapered_thread(self):
        plan = plan_program(self.program(designated("R 1/2")))
        with self.assertRaises(PostError) as caught:
            generate_gcode(plan, shipped_post(), PostSettings(XInputMode.DIAMETER))
        self.assertIn("synced_passes", str(caught.exception))

    def test_material_beyond_the_cone_is_a_warning_with_both_diameters_and_the_thread_is_written(self):
        plan = plan_program(self.program(designated("R 1/2"), raw=RawPart("steel", 22, 60)))
        result = plan.blocks[0].result
        message = result.messages[0]
        self.assertIn("WARNING", message)
        self.assertIn("turn or bore the cone first", message)
        self.assertIn("20.442", message)
        self.assertTrue([op for op in result.operations if isinstance(op, ThreadOperation)])


if __name__ == "__main__":
    unittest.main()
