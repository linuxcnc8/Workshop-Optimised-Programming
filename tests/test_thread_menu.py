"""The menu of standard threads beside the designation of the threading block (the user's wish, 2026-11-18)."""

from __future__ import annotations

import os
import sys
import unittest

from tests.test_pipe_threads import thread
from wop.core.blocks.turning_common import TurningSide
from wop.core.thread_designation import parse_designation, standard_designations
from wop.ui.block_forms import form_for

try:
    import PySide6  # noqa: F401
    HAVE_REAL_QT = not hasattr(sys.modules["PySide6"], "_fake")
except ImportError:
    HAVE_REAL_QT = False

if HAVE_REAL_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLineEdit, QMenu

    APP = QApplication.instance() or QApplication([])


class StandardDesignationTests(unittest.TestCase):
    def test_every_entry_of_the_menu_is_read_as_written(self):
        for outside in (True, False):
            for heading, values in standard_designations(outside):
                self.assertTrue(values, heading)
                for text in values:
                    with self.subTest(text=text):
                        self.assertEqual(parse_designation(text).designation, text)

    def test_bspt_follows_the_side_and_npt_is_on_both(self):
        def pipe(outside: bool) -> tuple[str, ...]:
            return next(values for heading, values in standard_designations(outside) if heading.startswith("BSPT"))

        self.assertIn("R 1/2", pipe(True))
        self.assertIn("Rc 1/2", pipe(False))
        self.assertNotIn("R 1/2", pipe(False))
        for outside in (True, False):
            npt = next(values for heading, values in standard_designations(outside) if heading.startswith("NPT"))
            self.assertIn("1/2-14 NPT", npt)


class FormMenuTests(unittest.TestCase):
    def test_the_designation_field_carries_the_menu_and_stays_a_text_field(self):
        for side in TurningSide:
            spec = next(s for s in form_for(thread(side=side)) if s.path == ("designation",))
            self.assertEqual(spec.suggestions, standard_designations(side is TurningSide.OUTSIDE))
            self.assertEqual(spec.choices, ())

    def test_other_fields_have_no_menu(self):
        self.assertFalse([s for s in form_for(thread()) if s.suggestions and s.path != ("designation",)])


@unittest.skipUnless(HAVE_REAL_QT, "needs the real PySide6")
class QtMenuTests(unittest.TestCase):
    def test_a_picked_thread_is_put_in_the_field_and_reported(self):
        from wop.core.program_model.units import XInputMode
        from wop.ui.qt.form_panel import FormPanel

        panel = FormPanel()
        block = thread()
        panel.set_form(block, form_for(block), XInputMode.DIAMETER)
        line = panel._widgets[("designation",)]
        self.assertIsInstance(line, QLineEdit)
        self.assertTrue(line.actions(), "the drop-down arrow")
        menu = line.findChild(QMenu)
        npt = next(action.menu() for action in menu.actions() if action.text().startswith("NPT"))
        edited = []
        panel.edited.connect(lambda spec, value: edited.append((spec.path, value)))
        next(a for a in npt.actions() if a.text() == "1/2-14 NPT").trigger()
        self.assertEqual(line.text(), "1/2-14 NPT")
        self.assertEqual(edited, [(("designation",), "1/2-14 NPT")])
        panel.hide()
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
