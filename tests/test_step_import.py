"""STEP import of turned parts (requirement C17): the Part 21 reader, B-splines and the turned outline."""

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wop.adapters.step_files import read_step
from wop.adapters.step_part21 import Enum, Part21Error, Ref, Typed, parse_part21
from wop.core.bspline import curve_point, expand_knots
from wop.core.contour import ContourError
from wop.core.dxf_contour import DxfArc, DxfLine
from wop.core.turned_profile import StepFace, StepSolid, StepSurface, contour_from_profile, turned_profile

DATA = Path(__file__).parent / "data" / "step"
HAVE_REAL_QT = False
try:
    import PySide6  # noqa: F401
    HAVE_REAL_QT = not hasattr(sys.modules["PySide6"], "_fake")
except ImportError:
    pass
Z_AXIS = (0.0, 0.0, 1.0)
ORIGIN = (0.0, 0.0, 0.0)


def circle(radius: float, z: float, count: int = 24) -> tuple:
    return tuple((radius * math.cos(a), radius * math.sin(a), z) for a in (math.tau * i / count for i in range(count + 1)))


def cylinder(radius: float, z1: float, z2: float, inward: bool = False) -> StepFace:
    return StepFace(StepSurface("cylinder", ORIGIN, Z_AXIS, radius), not inward, (circle(radius, z1), circle(radius, z2)))


def end_face(z: float, radius: float, outward_up: bool) -> StepFace:
    return StepFace(StepSurface("plane", (0.0, 0.0, z), Z_AXIS), outward_up, (circle(radius, z),))


def outline_points(drawing) -> list[tuple[float, float]]:
    points = []
    for piece in drawing.entities:
        points += [piece.start, piece.end] if isinstance(piece, DxfLine) else []
    return points


class Part21Tests(unittest.TestCase):
    def test_simple_complex_and_typed_records(self):
        text = (
            "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
            "#1 = CARTESIAN_POINT ( 'a;b', ( 1.5, -2.E1, 3 ) ) ;\n"
            "/* a comment; with a semicolon */\n"
            "#2=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));\n"
            "#3=MEASURE('it''s',LENGTH_MEASURE(0.01),#1,$);\nENDSEC;\nEND-ISO-10303-21;\n"
        )
        entities = parse_part21(text)
        self.assertEqual(entities[1].name, "CARTESIAN_POINT")
        self.assertEqual(entities[1].args, ["a;b", [1.5, -20.0, 3]])
        self.assertTrue(entities[2].has("SI_UNIT"))
        self.assertEqual(entities[2].parts["SI_UNIT"], [Enum("MILLI"), Enum("METRE")])
        self.assertEqual(entities[3].args, ["it's", Typed("LENGTH_MEASURE", [0.01]), Ref(1), None])

    def test_a_file_that_is_not_step_is_refused(self):
        with self.assertRaises(Part21Error):
            parse_part21("0\nSECTION\n2\nHEADER\n")


class BSplineTests(unittest.TestCase):
    def test_degree_one_is_the_polyline(self):
        knots = expand_knots([2, 1, 2], [0.0, 0.5, 1.0])
        self.assertEqual(curve_point(1, [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], knots, 0.25), (0.5, 0.5))

    def test_a_rational_quarter_circle_lies_on_the_circle(self):
        knots = expand_knots([3, 3], [0.0, 1.0])
        weights = [1.0, math.sqrt(0.5), 1.0]
        for u in (0.1, 0.37, 0.5, 0.9):
            x, y = curve_point(2, [(1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], knots, u, weights)
            self.assertAlmostEqual(math.hypot(x, y), 1.0, places=12)


class TurnedProfileTests(unittest.TestCase):
    def test_a_stepped_shaft(self):
        solid = StepSolid((
            cylinder(10, 0, 20), cylinder(15, 20, 50), end_face(0, 10, False), end_face(50, 15, True),
            StepFace(StepSurface("plane", (0.0, 0.0, 20.0), Z_AXIS), True, (circle(10, 20), circle(15, 20))),
        ))
        profile = turned_profile(solid, front_at_axis_end=True)
        self.assertAlmostEqual(profile.length, 50)
        self.assertAlmostEqual(profile.max_diameter, 30)
        self.assertEqual(profile.bores, ())
        definition = contour_from_profile(profile).definition
        corners = [(round(definition.start.x, 6), round(definition.start.z, 6))] + [
            (round(step.end.x, 6), round(step.end.z, 6)) for step in definition.steps
        ]
        self.assertEqual(corners, [(0, 0), (15, 0), (15, -30), (10, -30), (10, -50), (0, -50)])

    def test_the_other_end_as_front(self):
        solid = StepSolid((cylinder(10, 0, 20), cylinder(15, 20, 50)))
        definition = contour_from_profile(turned_profile(solid, front_at_axis_end=False)).definition
        self.assertAlmostEqual(definition.steps[0].end.x, 10)  # the small end is now the front

    def test_a_bore_is_found_and_the_outside_starts_at_it(self):
        solid = StepSolid((cylinder(20, 0, 40), cylinder(8, 0, 40, inward=True)))
        profile = turned_profile(solid)
        self.assertEqual(len(profile.bores), 1)
        self.assertAlmostEqual(contour_from_profile(profile).definition.start.x, 8)
        bore = contour_from_profile(profile, 0).definition
        self.assertAlmostEqual(bore.start.x, 8)
        self.assertAlmostEqual(bore.steps[-1].end.z, -40)

    def test_a_blind_bore_ends_on_the_axis(self):
        solid = StepSolid((cylinder(20, 0, 40), cylinder(8, 25, 40, inward=True)))
        bore = contour_from_profile(turned_profile(solid), 0).definition
        self.assertAlmostEqual(bore.steps[-1].end.x, 0)
        self.assertAlmostEqual(bore.steps[-1].end.z, -15)

    def test_a_hex_comes_out_at_its_across_corners_size(self):
        corner = 12.0
        flats = []
        for i in range(6):
            a, b = math.tau * i / 6, math.tau * (i + 1) / 6
            p, q = (corner * math.cos(a), corner * math.sin(a)), (corner * math.cos(b), corner * math.sin(b))
            normal = (math.cos((a + b) / 2), math.sin((a + b) / 2), 0.0)
            edges = ((p + (30.0,), p + (50.0,)), (q + (30.0,), q + (50.0,)))
            flats.append(StepFace(StepSurface("plane", (0.0, 0.0, 30.0), normal), True, edges))
        solid = StepSolid((cylinder(10, 0, 30), *flats))
        profile = turned_profile(solid)
        self.assertAlmostEqual(profile.max_diameter, 24)
        self.assertTrue(any("not round about the axis" in m for m in profile.messages))
        tops = [r for z, r in outline_points(profile.outside) if z < -0.001]
        self.assertAlmostEqual(max(r for z, r in outline_points(profile.outside)), 12)
        self.assertIn(10.0, [round(r, 6) for r in tops])

    def test_a_cross_hole_does_not_change_the_outline(self):
        hole = StepFace(StepSurface("cylinder", (0.0, 0.0, 15.0), (1.0, 0.0, 0.0), 3.0), False, (
            tuple((math.sqrt(100 - (3 * math.sin(t)) ** 2), 3 * math.sin(t), 15 + 3 * math.cos(t)) for t in
                  (math.tau * i / 24 for i in range(25))),
        ))
        solid = StepSolid((cylinder(10, 0, 30), cylinder(10, 0, 30), hole))
        profile = turned_profile(solid)
        self.assertEqual(len(profile.outside.entities), 3)

    def test_a_fillet_is_an_arc(self):
        # a torus of major radius 15 and tube radius 5 makes a concave R5 between the 10 and 15 radius
        fillet_edges = (circle(10, 5), circle(15, 0))
        fillet = StepFace(StepSurface("torus", (0.0, 0.0, 5.0), Z_AXIS, 15.0, 5.0), False, fillet_edges)
        solid = StepSolid((cylinder(15, -20, 0), fillet, cylinder(10, 5, 30)))
        profile = turned_profile(solid)
        arcs = [p for p in profile.outside.entities if isinstance(p, DxfArc)]
        self.assertEqual(len(arcs), 1)
        self.assertAlmostEqual(arcs[0].radius, 5)

    def test_no_round_face_is_refused(self):
        with self.assertRaises(ContourError):
            turned_profile(StepSolid((end_face(0, 10, True),)))


class StepFileTests(unittest.TestCase):
    def test_the_test_cylinder(self):
        solid = read_step(DATA / "cylinder_20x30.step")
        self.assertEqual(len(solid.faces), 3)
        profile = turned_profile(solid)
        self.assertAlmostEqual(profile.length, 30)
        self.assertAlmostEqual(profile.max_diameter, 20)

    def test_inches_are_converted(self):
        text = (DATA / "cylinder_20x30.step").read_text().replace(
            "#41=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
            "#41=(CONVERSION_BASED_UNIT('INCH',#46)LENGTH_UNIT()NAMED_UNIT(#47));"
            "#46=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#48);"
            "#47=DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);"
            "#48=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));",
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inch.step"
            path.write_text(text)
            profile = turned_profile(read_step(path))
        self.assertAlmostEqual(profile.length, 30 * 25.4)
        self.assertAlmostEqual(profile.max_diameter, 20 * 25.4)

    def test_a_dxf_file_is_refused_with_a_message(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "part.step"
            path.write_text("0\nSECTION\n")
            with self.assertRaises(ContourError):
                read_step(path)


class SketchImportTests(unittest.TestCase):
    """The sketch editor of a turning contour takes a STEP part (the session and the window)."""

    def setUp(self):
        from wop.ui.app_model import AppModel

        self.model = AppModel()
        self.contour_id = self.model.new_contour()
        self.solid = StepSolid((cylinder(20, 0, 40), cylinder(8, 0, 30, inward=True), cylinder(12, 30, 40, inward=True)))

    def test_the_session_loads_the_outside_and_the_bore(self):
        from wop.ui.sketch_session import SketchSession

        session = SketchSession(target=self.model.contour_sketch_target(self.contour_id))
        with mock.patch("wop.ui.sketch_modify.read_step", return_value=self.solid):
            front, back = session.read_part(Path("part.step"))
        session.load_profile(front)
        self.assertEqual(session.problems, [])
        self.assertTrue(session.result().is_valid)
        session.load_profile(front, 0)
        self.assertEqual(session.problems, [])
        self.assertAlmostEqual(session.result().segments[0].start.x, 12)  # the counterbore at the front
        self.assertAlmostEqual(contour_from_profile(back, 0).definition.start.x, 8)

    def test_a_part_that_cannot_be_read_gives_a_message(self):
        from wop.ui.sketch_session import SketchSession

        session = SketchSession(target=self.model.contour_sketch_target(self.contour_id))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "part.step"
            path.write_text("not a step file")
            self.assertIsNone(session.read_part(path))
        self.assertIn("not a STEP file", session.message)

    @unittest.skipUnless(HAVE_REAL_QT, "needs the real PySide6")
    def test_the_window_asks_for_the_front_and_the_contour(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from wop.ui.qt.sketch_dialog import SketchDialog

        self.app = QApplication.instance() or QApplication([])
        dialog = SketchDialog(target=self.model.contour_sketch_target(self.contour_id))
        asked: list[str] = []

        def answer(_parent, _title, label, items, *_args):
            asked.append(label)
            return items[1], True  # the other end as front, then the first bore

        with mock.patch("wop.ui.sketch_modify.read_step", return_value=self.solid), mock.patch(
            "wop.ui.qt.sketch_dialog.QInputDialog.getItem", side_effect=answer
        ), mock.patch("wop.ui.qt.sketch_dialog.QMessageBox.information"):
            dialog._import_step(Path("part.step"))
        self.assertEqual(len(asked), 2)
        self.assertEqual(dialog.session.problems, [])
        self.assertAlmostEqual(dialog.session.result().segments[0].start.x, 8)  # the back end has the plain bore
        dialog.hide()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
