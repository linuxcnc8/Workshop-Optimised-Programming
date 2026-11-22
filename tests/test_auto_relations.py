"""Relations an imported STEP part gets by itself (the user, 2026-11-23: "fix the step file import with automatic constraints"):
horizontal, vertical, tangent and on the axis, so a dimension keeps the shape (`wop/core/sketch/auto_relations.py`)."""

import unittest
from pathlib import Path

from wop.core.contour import ContourDefinition, LineStep
from wop.core.contour_solver import build_contour
from wop.core.geometry import Point
from wop.core.sketch.auto_relations import add_auto_relations
from wop.core.sketch.modes import sketch_from_contour
from wop.core.sketch.solver import analyse, solve
from wop.ui.sketch_session import SketchSession

STEP = Path(__file__).parent / "data" / "step" / "cylinder_20x30.step"


def shaft():
    """A shaft with a 1 mm fillet at a shoulder, from the front at the axis to the chuck."""
    from wop.core.contour import Corner, CornerKind
    steps = (LineStep(Point(8, 0)), LineStep(Point(8, -10), Corner(CornerKind.FILLET, 1)), LineStep(Point(12, -10)), LineStep(Point(12, -30)))
    return sketch_from_contour(build_contour("c", "c", ContourDefinition(Point(0, 0), steps)))


class AutoRelationTests(unittest.TestCase):
    def test_a_shaft_gets_horizontal_vertical_tangent_and_axis_relations(self):
        sketch = shaft()
        add_auto_relations(sketch)
        kinds = sorted(c.kind for c in sketch.constraints.values())
        self.assertEqual(kinds.count("horizontal"), 2)
        self.assertEqual(kinds.count("vertical"), 3)  # the front face, the shoulder, the origin
        self.assertEqual(kinds.count("tangent_line_arc"), 2)
        self.assertEqual(kinds.count("point_on_line"), 1)
        self.assertTrue(solve(sketch).converged)
        self.assertFalse(analyse(sketch).dependent, "no relation repeats another")

    def test_a_dimension_keeps_the_shoulder_square(self):
        sketch = shaft()
        add_auto_relations(sketch)
        line = next(l for l in sketch.lines.values() if abs(sketch.point(l.start).x - 12) < 1e-6 and abs(sketch.point(l.end).x - 12) < 1e-6)
        sketch.add_constraint("distance_x", (0, line.start), (14,))
        self.assertTrue(solve(sketch).converged)
        a, b = sketch.point(line.start), sketch.point(line.end)
        self.assertAlmostEqual(a.x, 14, places=6)
        self.assertAlmostEqual(b.x, 14, places=6, msg="the diameter stays horizontal")

    def test_the_step_import_of_the_sketch_editor_adds_them(self):
        session = SketchSession()
        profiles = session.read_part(STEP)
        messages = session.load_profile(profiles[0])
        self.assertTrue(session.sketch.constraints)
        self.assertTrue(any("relations were added" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
