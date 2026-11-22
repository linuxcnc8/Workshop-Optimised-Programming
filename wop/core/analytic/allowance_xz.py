"""A finishing allowance with its own value in X and in Z (B34): the contour moved away from the part by the X allowance on a diameter, by
the Z allowance on a face, and by an amount between them on a slope or an arc.

The area the allowance covers is the part grown by a disc of the smaller allowance and then by a straight line, along the axis of the larger
one, as long as the difference to each side (a Minkowski sum: the order does not matter). Equal values give exactly the old offset. The disc
is the offset the planner already makes (`offset_segments`); here the contour is pushed along that axis first: every piece moves to its free
side along the axis by the difference (a piece that faces the axis the other way moves the other way; a piece across the axis stays and is
stretched), arcs are cut where they turn across the axis, and the pieces are joined again (cut back where they cross, a straight line along
the axis where they part).
"""

from __future__ import annotations

from ..constants import GEOMETRY_TOLERANCE_MM
from ..geometry import ArcSegment, LineSegment, Point, Segment
from ..geometry.chain_index import monotone
from ..geometry.intersect import fraction_along, intersections, point_of
from ..geometry.offset import tangent_at_start


def uniform_part(x_mm: float, z_mm: float) -> float:
    """The allowance the planner offsets the contour by (the smaller one); the rest is the push of `pushed`."""
    return min(x_mm, z_mm)


def pushed(path: list[Segment], x_mm: float, z_mm: float, outside: bool) -> list[Segment]:
    """The contour (from the front to the chuck) pushed along the axis of the larger allowance by the difference (see the top)."""
    extra = abs(x_mm - z_mm)
    if extra <= GEOMETRY_TOLERANCE_MM or not path:
        return list(path)
    along_x = x_mm > z_mm
    moved: list[tuple[Segment, Point]] = []
    for segment in path:
        for piece in monotone(segment, 1 if along_x else 0):  # the free side's component along the axis keeps its sign on each part
            side = _free_side(piece, outside, along_x)
            shift = Point(side * extra, 0.0) if along_x else Point(0.0, side * extra)
            moved.append((_shifted(piece, shift), shift))
    joined: list[Segment] = [moved[0][0]]
    for piece, _shift in moved[1:]:
        last = joined[-1]
        if last.end.is_close(piece.start):
            joined.append(piece)
            continue
        cross = _crossing(last, piece)
        if cross is not None:
            joined[-1] = _with_end(last, cross)
            joined.append(_with_start(piece, cross))
        else:
            joined += [LineSegment(last.end, piece.start), piece]
    return [segment for segment in joined if segment.start.distance_to(segment.end) > GEOMETRY_TOLERANCE_MM or isinstance(segment, ArcSegment)]


def _free_side(piece: Segment, outside: bool, along_x: bool) -> int:
    """+1, -1 or 0: which way along the axis the free side of the piece lies (in its middle). Outside the free side is to the right of the
    travel towards the chuck (larger X on a diameter), inside to the left."""
    middle = point_of(piece, 0.5)
    tx, tz = tangent_at_start(_from(piece, middle))
    nx, nz = (-tz, tx) if outside else (tz, -tx)
    value = nx if along_x else nz
    return 0 if abs(value) <= GEOMETRY_TOLERANCE_MM else (1 if value > 0 else -1)


def _from(piece: Segment, at: Point) -> Segment:
    if isinstance(piece, LineSegment):
        return piece
    return ArcSegment(at, piece.end, piece.center, piece.direction)


def _shifted(piece: Segment, by: Point) -> Segment:
    def moved(point: Point) -> Point:
        return Point(point.x + by.x, point.z + by.z)

    if isinstance(piece, LineSegment):
        return LineSegment(moved(piece.start), moved(piece.end))
    return ArcSegment(moved(piece.start), moved(piece.end), moved(piece.center), piece.direction)


def _crossing(a: Segment, b: Segment) -> Point | None:
    """Where two moved pieces that no longer meet cross (an inner corner): the crossing nearest the end of `a`; None: they part (an outer
    corner, joined by a line)."""
    found = [p for p in intersections(a, b) if fraction_along(a, p) > GEOMETRY_TOLERANCE_MM and fraction_along(b, p) < 1 - GEOMETRY_TOLERANCE_MM]
    return min(found, key=lambda p: p.distance_to(a.end)) if found else None


def _with_end(segment: Segment, end: Point) -> Segment:
    if isinstance(segment, LineSegment):
        return LineSegment(segment.start, end)
    return ArcSegment(segment.start, end, segment.center, segment.direction)


def _with_start(segment: Segment, start: Point) -> Segment:
    if isinstance(segment, LineSegment):
        return LineSegment(start, segment.end)
    return ArcSegment(start, segment.end, segment.center, segment.direction)
