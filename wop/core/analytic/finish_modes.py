"""The plunge modes of a finishing pass (ECAM's "Plunge mode", the user's choice 2026-11-23): what the pass does where the contour goes down.

- Free: the tool path follows the whole contour (`nose_compensation.reference_path`), whatever the tool can reach (the checker reports it).
- Tool shape (`within_reach`): the pass keeps to where the tool may stand. The places of the tool reference where the planning tool (the real
  outline, its back edge turned by the block's back clearance) overlaps what must stay (the part, the stock beyond the limits, the bar behind
  the end of the contour) form one region, `forbidden`: what stays, moved by the nose radius, swept by the outline of the tool shrunk by the
  nose radius and turned a half turn (the Minkowski sum; the nose is the corner of the shrunk outline, so the result is exact there). Where the
  tool path dives into that region it runs along its border instead (down the back of the tool on a steep wall); where it ends in it (a face
  down to the centre with the bar behind it), the pass ends where it went in; where it starts in it (behind the stock in front of a Z+ limit),
  it comes down along the border from beyond the material.
- Don't plunge (`no_plunge`): the pass never moves towards the part while it travels towards the chuck: over a neck it runs straight on at the
  height before the neck until the contour comes back up.
The material a mode leaves stays (the block's picture shows it). The pieces made here have no point of the contour, so a compensated pass
(G41 / G42) keeps the free mode (the block refuses the combination).
"""

from __future__ import annotations

from enum import Enum

from ..constants import GEOMETRY_TOLERANCE_MM, PLUNGE_MODE_NOSE_MARGIN_MM, PLUNGE_MODE_ON_BORDER_MM
from ..geometry import ArcSegment, LineSegment, Point, Segment, segments_to_polyline
from ..geometry.chain_index import crossing_value, monotone, split_at
from ..geometry.chains import Loop, reversed_segment
from ..geometry.distance import distance_to_segment
from ..geometry.intersect import fraction_along, intersections, point_of
from ..geometry.region import Region
from ..tooling.tool import Tool
from ..tooling.tool_reference import nose_circle
from .tool_outline import planning_loops

Tagged = list[tuple[int, Segment]]


class PlungeMode(Enum):
    FREE = "free"
    TOOL_SHAPE = "tool shape"
    NO_PLUNGE = "don't plunge"




# --- Don't plunge ------------------------------------------------------------------------------------------------------------------

def no_plunge(pieces: Tagged, outside: bool) -> Tagged:
    """The tool path that never goes towards the part (outside: to a smaller radius; inside: to a larger one) while it travels on: where the
    contour goes down, the path runs on at the height it had until the contour comes back up to it."""
    tol = GEOMETRY_TOLERANCE_MM
    sign = 1 if outside else -1
    found: Tagged = []
    held: float | None = None  # the greatest height (sign * x) so far
    for index, segment in pieces:
        for piece in monotone(segment, 0):
            a, b = sign * piece.start.x, sign * piece.end.x
            if held is None or min(a, b) >= held - tol:  # at or above the height so far: follow the contour
                found.append((index, piece))
                held = max(a, b) if held is None else max(held, a, b)
                continue
            if max(a, b) <= held + tol:  # below it: straight on at the height
                found.append((index, LineSegment(_at(piece.start, held, sign), _at(piece.end, held, sign))))
                continue
            cross = Point(sign * held, crossing_value(piece, sign * held, 0))  # comes up through it: straight on to there, then follow
            parts = split_at(piece, [fraction_along(piece, cross)])
            found.append((index, LineSegment(_at(piece.start, held, sign), cross)))
            found.append((index, parts[-1]))
            held = max(a, b)
    return _joined(found)


def _at(point: Point, height: float, sign: int) -> Point:
    return Point(sign * height, point.z)


def _joined(pieces: Tagged) -> Tagged:
    """Pieces with no length left out; level lines that run on, and arcs that go on round the same circle, become one piece."""
    tol = GEOMETRY_TOLERANCE_MM
    found: Tagged = []
    for index, piece in pieces:
        if isinstance(piece, LineSegment) and piece.start.distance_to(piece.end) <= tol:
            continue
        last = found[-1][1] if found else None
        if isinstance(piece, LineSegment) and isinstance(last, LineSegment):
            if abs(last.start.x - last.end.x) <= tol and abs(piece.start.x - piece.end.x) <= tol and abs(last.end.x - piece.start.x) <= tol:
                found[-1] = (found[-1][0], LineSegment(last.start, piece.end))
                continue
        if isinstance(piece, ArcSegment) and isinstance(last, ArcSegment) and last.direction is piece.direction \
                and last.center.is_close(piece.center, PLUNGE_MODE_ON_BORDER_MM) and abs(last.radius - piece.radius) <= PLUNGE_MODE_ON_BORDER_MM:
            found[-1] = (found[-1][0], ArcSegment(last.start, piece.end, last.center, last.direction))
            continue
        if isinstance(piece, ArcSegment) and piece.start.distance_to(piece.end) <= PLUNGE_MODE_ON_BORDER_MM and found:
            found[-1] = (found[-1][0], _with_end(found[-1][1], piece.end))  # a sliver of an arc: the piece before ends there
            continue
        found.append((index, piece))
    return found


def _with_end(segment: Segment, end: Point) -> Segment:
    if isinstance(segment, LineSegment):
        return LineSegment(segment.start, end)
    return ArcSegment(segment.start, end, segment.center, segment.direction)


# --- Tool shape --------------------------------------------------------------------------------------------------------------------

def forbidden(stays: Region, tool: Tool, outside: bool, clearance_deg: float) -> Region:
    """The places of the tool reference where the planning tool overlaps `stays` (see the top)."""
    radius, _centre = nose_circle(tool)
    radius = max(radius - PLUNGE_MODE_NOSE_MARGIN_MM, 0.0)  # shrunk by the full radius the nose becomes a point, which the offset cannot make
    loops = planning_loops(tool, 1 if outside else -1, clearance_deg)
    outline = Region.from_segments([edge.segment for edge in loops[0]])
    shrunk = outline.offset(-radius) if radius > GEOMETRY_TOLERANCE_MM else outline
    turned = shrunk.mirrored().mirrored_z()  # the half turn about the reference point
    grown = stays.offset(radius) if radius > GEOMETRY_TOLERANCE_MM else stays
    found = Region.empty()
    for loop in turned.loops:
        corners = segments_to_polyline(list(loop))
        for a, b in zip(corners, corners[1:]):
            found = found.union(grown.translated(a.x, a.z).swept(b.x - a.x, b.z - a.z))
    anchor = grown.loops[0][0].start if grown.loops else None
    return found.union(turned.translated(anchor.x, anchor.z)) if anchor is not None else found


def within_reach(pieces: Tagged, region: Region, top: float) -> Tagged:
    """The tool path kept out of the forbidden `region` (see the top); `top`: a radius beyond the material on the free side, where a pass
    that starts in the region comes down from."""
    if not pieces or region.is_empty:
        return pieces
    border = [segment for loop in region.loops for segment in loop]
    first_index, first = pieces[0]
    if _inside(first.start, region, border):  # it starts where the tool cannot stand: down to it from beyond the material
        pieces = [(first_index, LineSegment(Point(top, first.start.z), first.start)), *pieces]
    split = [(index, part) for index, piece in pieces for part in _split_on(piece, border)]
    found: Tagged = []
    run_start: Point | None = None
    run_index = first_index
    for index, piece in split:
        if _inside(point_of(piece, 0.5), region, border):
            if run_start is None:
                run_start, run_index = piece.start, index
            continue
        if run_start is not None:
            if not _inside(run_start, region, border):  # (a pass that starts in the region begins where it comes out)
                found += [(run_index, segment) for segment in _around(region.loops, run_start, piece.start)]
            run_start = None
        found.append((index, piece))
    return _joined(found)  # a run to the end: the pass ends where it went in


def _inside(point: Point, region: Region, border: list[Segment]) -> bool:
    return region.strictly_contains_point(point) and min(distance_to_segment(point, segment) for segment in border) > PLUNGE_MODE_ON_BORDER_MM


def _split_on(piece: Segment, border: list[Segment]) -> list[Segment]:
    marks = [fraction_along(piece, point) for segment in border for point in intersections(piece, segment)]
    return split_at(piece, marks)


def _locate(loops: tuple[Loop, ...], point: Point) -> tuple[int, int, float] | None:
    best = None
    for number, loop in enumerate(loops):
        for position, segment in enumerate(loop):
            distance = distance_to_segment(point, segment)
            if best is None or distance < best[0]:
                best = (distance, number, position)
    if best is None or best[0] > 10 * PLUNGE_MODE_ON_BORDER_MM:
        return None
    _distance, number, position = best
    return number, position, fraction_along(loops[number][position], point)


def _around(loops: tuple[Loop, ...], start: Point, end: Point) -> list[Segment]:
    """The shorter way along the border of the region from `start` to `end` (both on the same loop); a straight line when they are not."""
    a, b = _locate(loops, start), _locate(loops, end)
    if a is None or b is None or a[0] != b[0]:
        return [LineSegment(start, end)]
    loop = list(loops[a[0]])
    forward = _walk(loop, a[1], a[2], b[1], b[2])
    backward = [reversed_segment(segment) for segment in reversed(_walk(loop, b[1], b[2], a[1], a[2]))]
    return min((forward, backward), key=lambda way: sum(_length(segment) for segment in way))


def _walk(loop: list[Segment], i: int, f: float, j: int, g: float) -> list[Segment]:
    """Along the loop in its own direction from the fraction `f` of piece `i` to the fraction `g` of piece `j`."""
    if i == j and g >= f:
        return [part for part in split_at(loop[i], [f, g]) if _between(part, loop[i], f, g)]
    way = [split_at(loop[i], [f])[-1]] if f < 1 else []
    k = (i + 1) % len(loop)
    while k != j:
        way.append(loop[k])
        k = (k + 1) % len(loop)
    if g > 0:
        way.append(split_at(loop[j], [g])[0])
    return [segment for segment in way if segment.start.distance_to(segment.end) > GEOMETRY_TOLERANCE_MM]


def _between(part: Segment, whole: Segment, f: float, g: float) -> bool:
    middle = fraction_along(whole, point_of(part, 0.5))
    return f - GEOMETRY_TOLERANCE_MM <= middle <= g + GEOMETRY_TOLERANCE_MM


def _length(segment: Segment) -> float:
    return segment.start.distance_to(segment.end)  # the chord of an arc is enough to choose the shorter way
