"""The thread depth for a partial-profile insert (the user's decision, 2026-11-18: from the tool data).

The reference depths were printed by the big-blue Turning panel's `thread_data.thread_depth(pitch, form, internal,
insert_r)`, whose arithmetic was checked on the machine against gauges (insert_r 0 = full form there)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_blocks_threading import block, program
from wop.core.blocks.turning_common import TurningSide
from wop.core.program_model.operations import ThreadOperation
from wop.core.program_model.program import plan_program
from wop.core.program_model.units import XInputMode
from wop.core.thread_form import ThreadForm, full_profile_depth, tip_correction
from wop.core.tool_types import definition_of, make_tool
from wop.core.tool_types.thread import ThreadDefinition, ThreadProfile
from wop.post.base import PostSettings
from wop.post.generate import generate_gcode
from wop.ui.block_forms import form_for
from tests.post_helpers import shipped_post

NPT_PITCH = 25.4 / 14


def depth(form: ThreadForm, pitch: float, outside: bool, tip: float | None) -> float:
    base = full_profile_depth(form, pitch, outside)
    return base if tip is None else base + tip_correction(form, pitch, outside, tip)


def thread_tool(profile: ThreadProfile, tip: float, number: int = 1):
    return make_tool("thread", number, ThreadDefinition(name="thread", profile=profile, nose_radius_mm=tip))


class PanelArithmeticTests(unittest.TestCase):
    def test_the_depths_of_the_turning_panel(self):
        cases = (  # (form, pitch, outside, tip radius or None for full profile, depth of the Turning panel)
            (ThreadForm.ISO, 3, True, 0.2, 2.073317),  # its worked example: M24 x 3 with a 0.2 partial-profile insert
            (ThreadForm.ISO, 3, True, None, 1.840304),
            (ThreadForm.ISO, 1, True, 0.2, 0.557772),  # below about 1.4 mm pitch a 0.2 tip is blunter: shallower
            (ThreadForm.ISO, 1.5, False, 0.1, 0.874279),
            (ThreadForm.ISO, 2, True, 0.05, 1.465544),
            (ThreadForm.WHITWORTH, NPT_PITCH, True, 0.2, 1.219035),
            (ThreadForm.NPT, NPT_PITCH, True, 0.1, 1.411300),
            (ThreadForm.NPT, NPT_PITCH, False, 0.1, 1.411300),
        )
        for form, pitch, outside, tip, expected in cases:
            with self.subTest(form=form, pitch=pitch, outside=outside, tip=tip):
                self.assertAlmostEqual(depth(form, pitch, outside, tip), expected, places=6)

    def test_a_trapezoidal_thread_has_no_tip_correction(self):
        self.assertIsNone(tip_correction(ThreadForm.TRAPEZOIDAL, 4, True, 0.2))


class ToolProfileTests(unittest.TestCase):
    def test_a_tool_saved_before_the_profile_existed_is_full_profile(self):
        tool = thread_tool(ThreadProfile.PARTIAL, 0.2)
        old = replace(tool, definition={k: v for k, v in tool.definition.items() if k != "profile"})
        self.assertIs(definition_of(old).profile, ThreadProfile.FULL)

    def test_the_tool_form_shows_the_profile_before_the_tip_radius(self):
        names = [spec.path[0] for spec in form_for(ThreadDefinition())]
        self.assertEqual(names.index("profile") + 1, names.index("nose_radius_mm"))
        self.assertIs(ThreadDefinition().profile, ThreadProfile.FULL)


class BlockDepthTests(unittest.TestCase):
    def test_a_full_profile_tool_cuts_the_standard_depth(self):
        thread = block(pitch_mm=3)
        self.assertAlmostEqual(thread.depth(thread_tool(ThreadProfile.FULL, 0.2)), 1.840304, places=6)

    def test_a_partial_profile_tool_cuts_deeper_by_its_tip(self):
        thread = block(pitch_mm=3)
        self.assertAlmostEqual(thread.depth(thread_tool(ThreadProfile.PARTIAL, 0.2)), 2.073317, places=6)

    def test_unticked_the_depth_is_cut_as_written(self):
        thread = block(pitch_mm=3, thread_depth_mm=1.9, tip_correction=False)
        self.assertEqual(thread.depth(thread_tool(ThreadProfile.PARTIAL, 0.2)), 1.9)

    def test_a_typed_full_profile_depth_gets_the_correction_while_ticked(self):
        thread = block(pitch_mm=3, thread_depth_mm=1.9)
        self.assertAlmostEqual(thread.depth(thread_tool(ThreadProfile.PARTIAL, 0.2)), 1.9 + 2.073317 - 1.840304, places=6)

    def test_a_tool_without_a_definition_is_taken_as_full_profile(self):
        from wop.core.tooling.tool_presets import thread_tool as shape_only

        thread = block(pitch_mm=3)
        self.assertAlmostEqual(thread.depth(shape_only(1, "thread")), 1.840304, places=6)

    def test_the_designation_sets_the_form_and_a_hand_change_of_the_form_clears_it(self):
        blank = block(side=TurningSide.OUTSIDE)
        npt = replace(blank, designation="1/2 NPT").with_derived_fields(blank)
        self.assertIs(npt.thread_form, ThreadForm.NPT)
        self.assertAlmostEqual(npt.depth(thread_tool(ThreadProfile.PARTIAL, 0.1)), 1.411300, places=6)
        bsp = replace(blank, designation="R 1/2").with_derived_fields(blank)
        self.assertIs(bsp.thread_form, ThreadForm.WHITWORTH)
        changed = replace(npt, thread_form=ThreadForm.ISO).with_derived_fields(npt)
        self.assertEqual(changed.designation, "")

    def test_the_plan_cuts_the_corrected_depth_and_says_so(self):
        tool = thread_tool(ThreadProfile.PARTIAL, 0.2)
        prog = program(block(pitch_mm=3, crest_radius_mm=12), tool)
        result = plan_program(prog).blocks[0].result
        thread_op = next(op for op in result.operations if isinstance(op, ThreadOperation))
        self.assertAlmostEqual(thread_op.depth_mm, 2.073317, places=6)
        note = next(m for m in result.messages if "partial-profile" in m)
        self.assertIn("T1", note)
        self.assertIn("2.0733 = full profile 1.8403 + 0.2330", note)
        text = generate_gcode(plan_program(prog), shipped_post(), PostSettings(XInputMode.RADIUS)).text
        self.assertIn(" K2.073 ", text)  # the shipped post writes K to 3 decimals

    def test_a_trapezoidal_thread_with_a_partial_profile_tool_is_cut_as_full_profile_with_a_note(self):
        thread = block(pitch_mm=3, thread_form=ThreadForm.TRAPEZOIDAL)
        tool = thread_tool(ThreadProfile.PARTIAL, 0.2)
        self.assertEqual(thread.depth(tool), thread.full_profile_depth())
        self.assertIn("no tip correction", thread._depth_messages(tool)[0])


if __name__ == "__main__":
    unittest.main()
