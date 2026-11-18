"""X2: the crest diameter at the end Z of a thread, worked out from the taper and typed to set it (the user's wish, 2026-11-18)."""

from __future__ import annotations

import os
import sys
import unittest

from tests.test_pipe_threads import designated, thread
from wop.core.blocks.turning_common import TurningSide
from wop.core.program_model.units import XInputMode
from wop.ui.block_forms import form_for, get_value, set_value, to_display

try:
    import PySide6  # noqa: F401
    HAVE_REAL_QT = not hasattr(sys.modules["PySide6"], "_fake")
except ImportError:
    HAVE_REAL_QT = False

if HAVE_REAL_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    APP = QApplication.instance() or QApplication([])


class X2Tests(unittest.TestCase):
    def test_x2_of_half_inch_npt_is_the_back_diameter_of_the_cone(self):
        block = designated("1/2 NPT")
        self.assertAlmostEqual(2 * block.end_crest_radius_mm, 21.563, places=3)
        self.assertAlmostEqual(block.end_crest_radius_mm, block.crest_at(block.end_z_mm))

    def test_x2_of_a_straight_thread_is_its_crest(self):
        block = thread(crest_radius_mm=10)
        self.assertEqual(block.end_crest_radius_mm, 10)

    def test_typing_x2_sets_the_taper_per_100_mm(self):
        block = thread(crest_radius_mm=10, start_z_mm=0, end_z_mm=-16)  # diameter 20 at the front
        changed = block.with_end_crest_radius_mm(11)  # diameter 22 at the back: 2 mm on the diameter over 16 mm
        self.assertAlmostEqual(changed.taper_per_100_mm, 12.5)
        self.assertAlmostEqual(changed.end_crest_radius_mm, 11)
        self.assertEqual(changed.crest_radius_mm, 10)

    def test_an_inside_thread_gets_a_negative_taper_when_x2_is_smaller(self):
        block = thread(side=TurningSide.INSIDE, crest_radius_mm=10, start_z_mm=0, end_z_mm=-10)
        self.assertAlmostEqual(block.with_end_crest_radius_mm(9.6875).taper_per_100_mm, -6.25)

    def test_typing_x2_clears_a_designation_like_any_hand_edit(self):
        block = designated("1/2 NPT")
        edited = block.with_end_crest_radius_mm(block.end_crest_radius_mm + 0.5).with_derived_fields(block)
        self.assertEqual(edited.designation, "")


class X2FormTests(unittest.TestCase):
    def spec(self, block):
        return next(s for s in form_for(block) if s.path == ("end_crest_radius_mm",))

    def test_the_form_shows_x2_after_the_taper_as_a_diameter(self):
        block = designated("1/2 NPT")
        names = [s.path[0] for s in form_for(block)]
        self.assertEqual(names.index("end_crest_radius_mm"), names.index("taper_per_100_mm") + 1)
        spec = self.spec(block)
        self.assertTrue(spec.computed)
        self.assertTrue(spec.is_radius)
        self.assertEqual(spec.display_label(XInputMode.DIAMETER), "X2 crest diameter at End Z")
        self.assertAlmostEqual(to_display(spec, get_value(block, spec.path), XInputMode.DIAMETER), 21.563, places=3)

    def test_setting_x2_through_the_form_changes_the_taper(self):
        block = thread(crest_radius_mm=10, start_z_mm=0, end_z_mm=-16)
        changed = set_value(block, ("end_crest_radius_mm",), 11)
        self.assertAlmostEqual(changed.taper_per_100_mm, 12.5)

    def test_stored_fields_are_still_set_as_before(self):
        self.assertEqual(set_value(thread(), ("pitch_mm",), 2).pitch_mm, 2)



@unittest.skipUnless(HAVE_REAL_QT, "needs the real PySide6")
class X2PanelTests(unittest.TestCase):
    def test_the_panel_shows_x2_as_a_diameter_never_dimmed_and_reports_a_typed_value(self):
        from wop.ui.qt.form_panel import FormPanel

        panel = FormPanel()
        block = designated("1/2 NPT")
        panel.set_form(block, form_for(block), XInputMode.DIAMETER, is_touched=lambda path: False)
        box = panel._widgets[("end_crest_radius_mm",)]
        self.assertAlmostEqual(box.value(), 21.563, places=3)
        self.assertNotEqual(box.contextMenuPolicy(), Qt.CustomContextMenu)  # no "Reset to default"
        self.assertEqual(panel._widgets[("taper_per_100_mm",)].contextMenuPolicy(), Qt.CustomContextMenu)
        edited = []
        panel.edited.connect(lambda spec, value: edited.append((spec.path, value)))
        box.setValue(22)
        self.assertEqual(edited[-1][0], ("end_crest_radius_mm",))
        self.assertAlmostEqual(edited[-1][1], 11)  # the model gets the radius
        panel.hide()
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
