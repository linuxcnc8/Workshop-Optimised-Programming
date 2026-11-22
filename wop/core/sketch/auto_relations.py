"""Relations an imported shape (STEP part, DXF drawing) gets by itself (the user, 2026-11-23: "fix the step file import with automatic constraints"; "add it to dxf too"), as a CAD
program adds them: so a dimension or a drag keeps the shape. An imported sketch had no relation at all: a dimension tipped the diameters and
faces and broke the fillets.

- a line along Z (a diameter) is horizontal, a line across (a face) vertical, within `AUTO_STRAIGHT_MM` over its length;
- a point on the centre line lies on the spindle axis (a line on the axis gets that for both ends instead of horizontal), and a point at Z0
  on it is held at the origin (straight above it), so a dimension does not slide the whole part along Z;
- where a line and an arc, or two arcs, meet with the same direction (within `AUTO_TANGENT_SINE`), they are tangent.
The axis and origin relations only for a turning contour (`turning`). Nothing is dimensioned (the user, 2026-11-23: "leave it as relations only").
"""

from __future__ import annotations

import math

from .constants import AUTO_STRAIGHT_MM, AUTO_TANGENT_SINE, AXIS_LINE, ORIGIN
from .model import Sketch, SketchArc, SketchError, SketchLine


def add_auto_relations(sketch: Sketch, turning: bool = True) -> int:
    """Add the relations (see the top) to the sketch; the number added."""
    added = 0

    def add(kind: str, refs: tuple[int, ...]) -> None:
        nonlocal added
        try:
            sketch.add_constraint(kind, refs)
            added += 1
        except SketchError:
            pass  # already there, or not valid for these (a point that is an end of the line)

    on_axis = {pid for pid, point in sketch.points.items() if abs(point.x) <= AUTO_STRAIGHT_MM} if turning else set()
    lines = [line for line in sketch.lines.values() if not line.construction]
    arcs = [arc for arc in sketch.arcs.values() if not arc.construction and arc.start != arc.end]
    for line in lines:
        a, b = sketch.point(line.start), sketch.point(line.end)
        if line.start in on_axis and line.end in on_axis:
            continue  # on the axis: both ends get the axis relation below
        if abs(a.x - b.x) <= AUTO_STRAIGHT_MM:
            add("horizontal", (line.start, line.end))
        elif abs(a.z - b.z) <= AUTO_STRAIGHT_MM:
            add("vertical", (line.start, line.end))
    for point_id in sorted(on_axis):
        if any(point_id in (line.start, line.end) for line in lines) or any(point_id in (arc.start, arc.end) for arc in arcs):
            add("point_on_line", (point_id, AXIS_LINE))
            if abs(sketch.point(point_id).z) <= AUTO_STRAIGHT_MM:
                add("vertical", (point_id, ORIGIN))  # on the axis and at Z0: the origin
    for arc in arcs:
        for touch in (arc.start, arc.end):
            for line in lines:
                if touch in (line.start, line.end) and _parallel(_line_direction(sketch, line, touch), _arc_direction(sketch, arc, touch)):
                    add("tangent_line_arc", (line.line_id, arc.arc_id, touch))
            for other in arcs:
                if other.arc_id > arc.arc_id and touch in (other.start, other.end) \
                        and _parallel(_arc_direction(sketch, arc, touch), _arc_direction(sketch, other, touch)):
                    add("tangent_arcs", (arc.arc_id, other.arc_id, touch))
    return added


def _line_direction(sketch: Sketch, line: SketchLine, at: int) -> tuple[float, float]:
    other = line.end if at == line.start else line.start
    a, b = sketch.point(at), sketch.point(other)
    return b.x - a.x, b.z - a.z


def _arc_direction(sketch: Sketch, arc: SketchArc, at: int) -> tuple[float, float]:
    """The tangent of the arc at one of its ends (its sign does not matter here)."""
    centre, point = sketch.point(arc.centre), sketch.point(at)
    rx, rz = point.x - centre.x, point.z - centre.z
    return -rz, rx


def _parallel(a: tuple[float, float], b: tuple[float, float]) -> bool:
    length = math.hypot(*a) * math.hypot(*b)
    return length > 0 and abs(a[0] * b[1] - a[1] * b[0]) / length <= AUTO_TANGENT_SINE
