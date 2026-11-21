"""Toolpath limits of a block (B30, B31): the block cuts only between two Z values and not beyond one radius, the contour itself stays as
it is. The contour block plans from the contour clipped to the limits (`limited_path`) and from the material clipped to them (`limit_box`);
the ways in and out and the collision check still see all the material.

- Z+ limit: the block cuts only behind it (towards the chuck); Z- limit: only in front of it. Minus is always towards the chuck.
- The X limit lies on the side of the part (outside: the smallest radius the block cuts to; inside: the largest): where the contour goes
  beyond it, the block runs straight along the limit and joins the contour again where the contour comes back.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import GEOMETRY_TOLERANCE_MM
from ..geometry import LineSegment, Point, Segment
from ..geometry.chain_index import coordinates, crossing_value, monotone, split_at
from ..geometry.intersect import fraction_along, point_of
from ..geometry.region import Region
from .base import BlockError


@dataclass(frozen=True)
class ToolpathLimits:
    """The limits of one block; None: that limit is off."""

    z_plus: float | None = None  # the block cuts only at this Z and behind it
    z_minus: float | None = None  # the block cuts only at this Z and in front of it
    x_radius: float | None = None  # the block does not cut beyond this radius into the part (outside: below it; inside: above it)

    @property
    def active(self) -> bool:
        return self.z_plus is not None or self.z_minus is not None or self.x_radius is not None

    def check(self) -> None:
        """A BlockError for limits that leave nothing between them."""
        if self.z_plus is not None and self.z_minus is not None and self.z_minus >= self.z_plus - GEOMETRY_TOLERANCE_MM:
            raise BlockError(f"the Z- limit ({self.z_minus:g}) must lie in front of the chuck side of the Z+ limit ({self.z_plus:g}): Z- < Z+")
        if self.x_radius is not None and self.x_radius < 0:
            raise BlockError("the X limit must not be negative")

    def lines(self, bounds, margin: float) -> tuple[Segment, ...]:
        """The limits as lines across the material (`bounds`), a `margin` beyond it, for the picture."""
        return _lines(self, bounds, margin)

    def note(self, name: str) -> str:
        """The note of a limited block: it says the stop is on purpose."""
        parts = []
        if self.z_plus is not None:
            parts.append(f"Z+ {self.z_plus:g}")
        if self.z_minus is not None:
            parts.append(f"Z- {self.z_minus:g}")
        if self.x_radius is not None:
            parts.append(f"X {2 * self.x_radius:g} (diameter)")
        return f"{name}: limited to {', '.join(parts)}; the material beyond the limits stays for another block"


def _lines(limits: ToolpathLimits, bounds, margin: float) -> tuple[Segment, ...]:
    """See `ToolpathLimits.lines`."""
    low_x, high_x = min(bounds.min_x, 0.0), bounds.max_x + margin
    low_z = limits.z_minus if limits.z_minus is not None else bounds.min_z
    high_z = limits.z_plus if limits.z_plus is not None else bounds.max_z
    found: list[Segment] = []
    for z in (limits.z_plus, limits.z_minus):
        if z is not None:
            found.append(LineSegment(Point(high_x, z), Point(low_x, z)))
    if limits.x_radius is not None:
        found.append(LineSegment(Point(limits.x_radius, high_z + margin), Point(limits.x_radius, low_z - margin)))
    return tuple(found)


def _split_at_level(path: list[Segment], level: float, axis: int) -> list[Segment]:
    """The path with every piece cut where it crosses the line at `level` (axis 0: a radius, axis 1: a Z)."""
    tol = GEOMETRY_TOLERANCE_MM
    found: list[Segment] = []
    for segment in path:
        for piece in monotone(segment, axis):
            a = coordinates(piece.start, axis)[0]
            b = coordinates(piece.end, axis)[0]
            if (a - level) * (b - level) < 0 and abs(a - level) > tol and abs(b - level) > tol:
                value = crossing_value(piece, level, axis)
                point = Point(level, value) if axis == 0 else Point(value, level)
                found += split_at(piece, [fraction_along(piece, point)])
            else:
                found.append(piece)
    return found


def _middle(piece: Segment) -> Point:
    return point_of(piece, 0.5)


def _joined(pieces: list[Segment]) -> list[Segment]:
    """Lines that run on in the same direction become one; pieces with no length are left out."""
    tol = GEOMETRY_TOLERANCE_MM
    found: list[Segment] = []
    for piece in pieces:
        if piece.start.distance_to(piece.end) <= tol:
            continue
        last = found[-1] if found else None
        if isinstance(piece, LineSegment) and isinstance(last, LineSegment):
            same_x = abs(last.start.x - last.end.x) <= tol and abs(piece.start.x - piece.end.x) <= tol and abs(last.end.x - piece.start.x) <= tol
            same_z = abs(last.start.z - last.end.z) <= tol and abs(piece.start.z - piece.end.z) <= tol and abs(last.end.z - piece.start.z) <= tol
            if same_x or same_z:
                found[-1] = LineSegment(last.start, piece.end)
                continue
        found.append(piece)
    return found


def limited_path(path: list[Segment], limits: ToolpathLimits, outside: bool) -> list[Segment]:
    """The contour as the limited block cuts it: beyond the X limit straight along it, and only the stretch between the Z limits (where
    the contour leaves that stretch and comes back, it runs along the limit). Empty when no piece of the contour lies between the Z limits."""
    tol = GEOMETRY_TOLERANCE_MM
    pieces = list(path)
    if limits.x_radius is not None:
        r = limits.x_radius
        beyond = (lambda p: p.x < r - tol) if outside else (lambda p: p.x > r + tol)
        pieces = [
            LineSegment(Point(r, piece.start.z), Point(r, piece.end.z)) if beyond(_middle(piece)) else piece
            for piece in _split_at_level(pieces, r, 0)
        ]
    for level, ahead in ((limits.z_plus, True), (limits.z_minus, False)):
        if level is None:
            continue
        kept: list[Segment] = []
        for piece in _split_at_level(pieces, level, 1):
            z = _middle(piece).z
            off = z > level + tol if ahead else z < level - tol
            kept.append(LineSegment(Point(piece.start.x, level), Point(piece.end.x, level)) if off else piece)
        first = next((i for i, p in enumerate(kept) if not _on_level(p, level)), None)
        if first is None:
            return []
        last = max(i for i, p in enumerate(kept) if not _on_level(p, level))
        pieces = kept[first:last + 1]  # the path starts and ends on the contour; runs along the limit only between two stretches of it
    return _joined(pieces)


def _on_level(piece: Segment, level: float) -> bool:
    tol = GEOMETRY_TOLERANCE_MM
    return abs(piece.start.z - level) <= tol and abs(piece.end.z - level) <= tol


def limit_box(limits: ToolpathLimits, outside: bool, both_sides: bool, reach: float) -> Region:
    """The area the block may cut in: between the Z limits and on the free side of the X limit; `reach` is a radius beyond all the
    material and the tool. `both_sides`: the area also turned over the axis (an inside block plans the far side of the bore too)."""
    z_high = limits.z_plus if limits.z_plus is not None else reach
    z_low = limits.z_minus if limits.z_minus is not None else -reach
    if outside:
        low = limits.x_radius if limits.x_radius is not None else -reach
        return Region.rectangle(low, z_low, reach, z_high)
    high = limits.x_radius if limits.x_radius is not None else reach
    return Region.rectangle(-high if both_sides else -reach, z_low, high, z_high)
