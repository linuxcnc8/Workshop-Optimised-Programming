"""A contour typed as points (requirement C12): the rows, the sketch they make, reading a sketch back into rows, the Turning panel's text,
the model actions and the points dialog."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from wop.core.contour import CornerKind
from wop.core.geometry import ArcSegment, LineSegment, Point
from wop.core.sketch.corners import fillet_corner
from wop.core.sketch.model import Sketch
from wop.core.sketch.modes import TURNING, contour_from_sketch
from wop.core.sketch.points_profile import (
    ProfileError,
    ProfileRow,
    parse_profile_text,
    profile_text,
    rows_from_sketch,
    sketch_from_rows,
)

ROOT = Path(__file__).parent.parent
SHAFT_TEXT = "# a shaft, X diameters as the Turning panel\n0 0\n36 0 C1\n36 -20 R2\n50 -20 C0.5\n50, -60 ; the end\n"
SHAFT = [ProfileRow(0, 0), ProfileRow(18, 0, CornerKind.CHAMFER, 1), ProfileRow(18, -20, CornerKind.FILLET, 2),
         ProfileRow(25, -20, CornerKind.CHAMFER, 0.5), ProfileRow(25, -60)]


class RowsTests(unittest.TestCase):
    def test_the_turning_panel_text_gives_the_rows_with_radius_x(self):
        self.assertEqual(parse_profile_text(SHAFT_TEXT), SHAFT)

    def test_the_rows_make_the_contour_with_its_chamfers_and_radius(self):
        contour = contour_from_sketch(sketch_from_rows(SHAFT), TURNING, "c", "Shaft")
        kinds = [type(segment) for segment in contour.segments]
        self.assertEqual(kinds, [LineSegment, LineSegment, LineSegment, ArcSegment, LineSegment, LineSegment, LineSegment])
        self.assertEqual(contour.segments[1].end, Point(18, -1))  # the chamfer of 1 at the corner of the face
        self.assertEqual(contour.segments[3].end, Point(20, -20))  # the radius of 2 in the shoulder

    def test_a_sketch_made_from_rows_reads_back_as_the_same_rows(self):
        back = rows_from_sketch(sketch_from_rows(SHAFT))
        self.assertEqual(len(back), len(SHAFT))
        for got, want in zip(back, SHAFT):
            self.assertAlmostEqual(got.x, want.x)
            self.assertAlmostEqual(got.z, want.z)
            self.assertEqual(got.corner, want.corner)
            self.assertAlmostEqual(got.size_mm, want.size_mm)

    def test_the_text_round_trip(self):
        self.assertEqual(parse_profile_text(profile_text(SHAFT)), SHAFT)

    def test_rows_that_cannot_be_drawn_name_the_row(self):
        for rows, index in (
            ([ProfileRow(0, 0, CornerKind.FILLET, 1), ProfileRow(10, 0)], 0),  # the first point has no corner
            ([ProfileRow(0, 0), ProfileRow(10, 0, CornerKind.FILLET, 0), ProfileRow(10, -5)], 1),  # no size
            ([ProfileRow(0, 0), ProfileRow(0, 0)], 1),  # the same point twice
            ([ProfileRow(0, 0), ProfileRow(10, 0, CornerKind.FILLET, 50), ProfileRow(10, -5)], 1),  # the radius does not fit
        ):
            with self.subTest(rows=rows), self.assertRaises(ProfileError) as caught:
                sketch_from_rows(rows)
            self.assertEqual(caught.exception.index, index)

    def test_bad_text_names_the_line(self):
        with self.assertRaises(ProfileError) as caught:
            parse_profile_text("0 0\n36 0 X1\n")
        self.assertIn("line 2", str(caught.exception))

    def test_an_arc_that_is_not_a_corner_cannot_be_rows(self):
        sketch = Sketch()
        a, b, c, centre = sketch.add_point(0, 0), sketch.add_point(10, 0), sketch.add_point(10, -10), sketch.add_point(0, -10)
        sketch.add_line(a, b)
        sketch.add_arc(centre, b, c)
        with self.assertRaises(ProfileError):
            rows_from_sketch(sketch)

    def test_a_fillet_drawn_in_the_sketch_editor_reads_back_as_r(self):
        sketch = Sketch()
        ids = [sketch.add_point(x, z) for x, z in ((0, 0), (10, 0), (10, -10))]
        sketch.add_line(ids[0], ids[1])
        sketch.add_line(ids[1], ids[2])
        fillet_corner(sketch, ids[1], 1.5)
        rows = rows_from_sketch(sketch)
        self.assertEqual((rows[1].x, rows[1].z, rows[1].corner), (10, 0, CornerKind.FILLET))
        self.assertAlmostEqual(rows[1].size_mm, 1.5)


class ModelTests(unittest.TestCase):
    def setUp(self):
        from wop.ui.app_model import AppModel

        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.model = AppModel(settings_path=Path(self.folder.name) / "settings.json")

    def test_a_new_contour_from_points_is_added_chosen_and_can_be_undone(self):
        before = len(self.model.program.contours)
        contour_id = self.model.contour_from_rows(SHAFT)
        self.assertEqual(self.model.selected_contour, contour_id)
        self.assertTrue(self.model.chosen_contour().is_valid)
        self.model.undo()
        self.assertEqual(len(self.model.program.contours), before)

    def test_editing_as_points_keeps_the_name_and_the_id(self):
        contour_id = self.model.contour_from_rows(SHAFT)
        self.model.rename_contour(contour_id, "Shaft")
        rows = self.model.contour_rows(contour_id)
        rows[-1] = ProfileRow(25, -70)
        self.assertEqual(self.model.contour_from_rows(rows, contour_id), contour_id)
        self.assertEqual(self.model.chosen_contour().name, "Shaft")
        self.assertEqual(self.model.chosen_contour().segments[-1].end, Point(25, -70))

    def test_rows_that_make_no_contour_are_a_model_error(self):
        from wop.ui.app_model import ModelError

        with self.assertRaises(ModelError):
            self.model.contour_from_rows([ProfileRow(0, 0)])


try:
    import PySide6  # noqa: F401
    HAVE_REAL_QT = not hasattr(sys.modules["PySide6"], "_fake")
except ImportError:
    HAVE_REAL_QT = False


@unittest.skipUnless(HAVE_REAL_QT, "needs the real PySide6")
class DialogTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])

    def tidy(self, widget) -> None:
        """Hide the widget when the test ends and let Qt delete it, so no window is left for the next test of this process (hidden, not
        closed: closing the main window asks whether to save the changes, and nobody answers offscreen)."""
        def close() -> None:
            widget.hide()
            widget.deleteLater()
            self.app.processEvents()

        self.addCleanup(close)

    def test_the_table_shows_diameters_and_gives_back_radius_rows(self):
        from PySide6.QtWidgets import QDialogButtonBox

        from wop.ui.qt.points_dialog import PointsDialog

        dialog = PointsDialog(None, "Points", SHAFT, x_diameter=True)
        self.tidy(dialog)
        self.assertEqual(dialog.table.item(1, 0).text(), "36")
        self.assertTrue(dialog.box.button(QDialogButtonBox.Ok).isEnabled())
        self.assertEqual(dialog.status.text(), "The contour is fine.")
        self.assertEqual(len(dialog.preview.segments), 7)
        dialog.table.item(4, 1).setText("-70")
        dialog._accept()
        self.assertEqual(dialog.rows()[-1], ProfileRow(25, -70))

    def test_an_empty_row_turns_ok_off_and_says_why(self):
        from PySide6.QtWidgets import QDialogButtonBox

        from wop.ui.qt.points_dialog import PointsDialog

        dialog = PointsDialog(None, "Points", [], x_diameter=True)
        self.tidy(dialog)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertFalse(dialog.box.button(QDialogButtonBox.Ok).isEnabled())
        self.assertIn("empty", dialog.status.text())

    def test_the_window_adds_a_contour_from_points(self):
        from unittest import mock

        from wop.ui.app_model import AppModel
        from wop.ui.qt.main_window import MainWindow

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        model = AppModel(settings_path=Path(folder.name) / "settings.json")
        model.open(ROOT / "examples" / "reference.wop.json")
        window = MainWindow(model)
        self.tidy(window)

        class FakeDialog:
            def __init__(self, parent, title, rows, x_diameter):
                self.given = rows

            def exec(self):
                return 1

            def rows(self):
                return SHAFT

        with mock.patch("wop.ui.qt.window_parts.actions.PointsDialog", FakeDialog):
            window._new_contour_from_points()
            window._points_for_contour()
        self.assertEqual(model.chosen_contour().segments[-1].end, Point(25, -60))


if __name__ == "__main__":
    unittest.main()
