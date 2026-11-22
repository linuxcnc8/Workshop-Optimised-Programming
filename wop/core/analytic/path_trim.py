"""The tool path of a finishing pass cut back at a Z limit (B30): no part of the tool goes beyond the limit.

The path of the tool reference (`nose_compensation.reference_path`) is cut where the tool would first reach past the limit: at the end of
the travel for a Z- limit (the tool travels towards it), at the start for a pass planned mirrored (a left-hand tool travels away from it).
The level for the reference is the limit moved by how far the outline of the tool reaches beyond its reference point in Z.
"""

from __future__ import annotations

import math

from ..constants import GEOMETRY_TOLERANCE_MM
from ..geometry import ArcSegment, LineSegment, Point, Segment
from ..geometry.chain_index import crossing_value, monotone, split_at
from ..geometry.chains import box_of
from ..geometry.intersect import fraction_along
from ..tooling.tool import Tool

Tagged = list[tuple[int, Segment]]


def tool_z_reach(tool: Tool) -> tuple[float, float]:
    """The smallest and the largest Z of the outline of the tool (its reference point at the origin)."""
    boxes = [box_of(piece.segment) for piece in tool.shape.pieces]
    return min(box[1] for box in boxes), max(box[3] for box in boxes)


def _cut(piece: Segment, level: float) -> list[Segment]:
    point = Point(crossing_value(piece, level, 1), level)
    return split_at(piece, [fraction_along(piece, point)])


def _rejoined(parts: list[Segment]) -> Segment:
    """Parts of one piece, one after the other, as one piece again (an arc keeps its circle)."""
    first, last = parts[0], parts[-1]
    if isinstance(first, ArcSegment):
        return ArcSegment(first.start, last.end, first.center, first.direction)
    return LineSegment(first.start, last.end)


def cut_at_end(tagged: Tagged, floor: float) -> tuple[Tagged, bool]:
    """The path up to where it first goes below `floor` (Z); True when it was cut."""
    tol = GEOMETRY_TOLERANCE_MM
    kept: Tagged = []
    for index, segment in tagged:
        if box_of(segment)[1] >= floor - tol:
            kept.append((index, segment))
            continue
        parts: list[Segment] = []
        for part in monotone(segment, 1):
            if min(part.start.z, part.end.z) >= floor - tol:
                parts.append(part)
                continue
            if part.start.z > floor + tol:
                parts.append(_cut(part, floor)[0])
            break
        if parts:
            kept.append((index, _rejoined(parts)))
        return kept, True
    return kept, False


def cut_at_start(tagged: Tagged, ceiling: float) -> tuple[Tagged, bool]:
    """The path from where it last comes down to `ceiling` (Z) out of the region above it; True when it was cut."""
    tol = GEOMETRY_TOLERANCE_MM
    last_above = max((number for number, (_index, segment) in enumerate(tagged) if box_of(segment)[3] > ceiling + tol), default=None)
    if last_above is None:
        return tagged, False
    index, segment = tagged[last_above]
    parts: list[Segment] = []
    for part in reversed(monotone(segment, 1)):
        if max(part.start.z, part.end.z) <= ceiling + tol:
            parts.insert(0, part)
            continue
        if part.end.z < ceiling - tol:
            parts.insert(0, _cut(part, ceiling)[-1])
        break
    rest = tagged[last_above + 1:]
    return ([(index, _rejoined(parts))] if parts else []) + rest, True


def nominal_point(reference: Point, centre: Point, nominal: Segment) -> Point:
    """The point of the contour piece `nominal` that the nose touches when the tool reference stands at `reference` (`centre`: the nose
    centre from the reference point)."""
    cx, cz = reference.x + centre.x, reference.z + centre.z
    if isinstance(nominal, ArcSegment):
        dx, dz = cx - nominal.center.x, cz - nominal.center.z
        length = math.hypot(dx, dz) or 1.0
        return Point(nominal.center.x + dx * nominal.radius / length, nominal.center.z + dz * nominal.radius / length)
    ax, az = nominal.start.x, nominal.start.z
    ux, uz = nominal.end.x - ax, nominal.end.z - az
    square = ux * ux + uz * uz or 1.0
    t = ((cx - ax) * ux + (cz - az) * uz) / square
    return Point(ax + ux * t, az + uz * t)
