"""The turned outline of a solid part (from a STEP file) as lines and arcs (requirement C17).

The adapter `wop/adapters/step_files.py` reads the faces; this module knows nothing about files. Method:

- the spindle axis is the line that most round faces (cylinders, cones, tori, surfaces of revolution) share;
- every face round about that axis gives an exact piece of the profile in the (z, radius) half plane: a cylinder a
  line at its radius, a cone a sloping line, a torus or sphere an arc; faces square to the axis are the steps between;
- the outside is the TURNED ENVELOPE: the largest radius of the part at every z. Faces that are not round about the
  axis (flats, hexes, keyways, cross holes, splines) count only where they stick out beyond the round faces, so a hex
  comes out at its across-corners diameter and flats, keyways and cross holes drop out by themselves;
- a bore is the smallest radius of the faces that face the axis (their outward normal points inward).

The result is a drawing in the plane (drawing X = Z, drawing Y = radius) that `dxf_contour.contour_from_drawing`
joins into a contour, as for a DXF section. Z0 is the front face; the part lies at negative Z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .constants import (
    STEP_AXIS_ANGLE_TOLERANCE,
    STEP_AXIS_TOLERANCE_MM,
    STEP_ENVELOPE_TOLERANCE_MM,
    STEP_SIMPLIFY_TOLERANCE_MM,
)
from .contour import ContourError
from .dxf_contour import DxfArc, DxfDrawing, DxfImport, DxfLine, contour_from_chain

Vec3 = tuple[float, float, float]
ZR = tuple[float, float]
ROUND_KINDS = ("cylinder", "cone", "torus", "revolution")
SAMPLES_PER_INTERVAL = 9  # an interval between end points is checked at this many z values
TINY_Z = 1e-9


@dataclass(frozen=True)
class StepSurface:
    kind: str  # plane, cylinder, cone, torus, sphere, revolution, other
    origin: Vec3
    axis: Vec3  # unit; the normal of a plane
    radius: float = 0.0  # cylinder, cone (at the origin), sphere; major radius of a torus
    minor_radius: float = 0.0  # torus
    semi_angle: float = 0.0  # cone, radians
    step_type: str = ""


@dataclass(frozen=True)
class StepFace:
    surface: StepSurface
    same_sense: bool  # False: the outward normal of the face is opposite to the surface normal
    edges: tuple[tuple[Vec3, ...], ...]  # sampled boundary edges, mm


@dataclass(frozen=True)
class StepSolid:
    faces: tuple[StepFace, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnedProfile:
    outside: DxfDrawing
    bores: tuple[DxfDrawing, ...]
    length: float
    max_diameter: float
    messages: tuple[str, ...]


@dataclass(frozen=True)
class _Span:
    """A piece of the profile that is a function r(z) on [z1, z2]: a line, or the upper or lower half of an arc."""

    z1: float
    z2: float
    r1: float = 0.0  # line
    r2: float = 0.0
    arc: bool = False
    zc: float = 0.0
    rc: float = 0.0
    radius: float = 0.0
    upper: bool = True
    inward: bool = False  # the face looks at the axis (a bore)
    exact: bool = True  # from a round face (False: from the edges of another face)

    def at(self, z: float) -> float:
        if not self.arc:
            if self.z2 - self.z1 <= TINY_Z:
                return max(self.r1, self.r2)
            return self.r1 + (self.r2 - self.r1) * (z - self.z1) / (self.z2 - self.z1)
        root = math.sqrt(max(self.radius ** 2 - (z - self.zc) ** 2, 0.0))
        return self.rc + root if self.upper else self.rc - root


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross_length(a: Vec3, b: Vec3) -> float:
    return math.dist((0.0, 0.0, 0.0), (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]))


class _Axis:
    def __init__(self, origin: Vec3, direction: Vec3) -> None:
        self.origin, self.direction = origin, direction

    def zr(self, p: Vec3) -> ZR:
        d = (p[0] - self.origin[0], p[1] - self.origin[1], p[2] - self.origin[2])
        z = _dot(d, self.direction)
        radial = (d[0] - z * self.direction[0], d[1] - z * self.direction[1], d[2] - z * self.direction[2])
        return z, math.sqrt(_dot(radial, radial))

    def holds(self, origin: Vec3, direction: Vec3) -> bool:
        """The line through `origin` along `direction` is this axis."""
        return _cross_length(direction, self.direction) <= STEP_AXIS_ANGLE_TOLERANCE and self.zr(origin)[1] <= STEP_AXIS_TOLERANCE_MM

    def parallel(self, direction: Vec3) -> bool:
        return _cross_length(direction, self.direction) <= STEP_AXIS_ANGLE_TOLERANCE


def find_axis(solid: StepSolid) -> tuple[_Axis, int, int]:
    """The axis most round faces share, the number of faces round about it, and the number round about other axes."""
    groups: list[tuple[_Axis, int]] = []
    for face in solid.faces:
        surface = face.surface
        if surface.kind not in ROUND_KINDS:
            continue
        for index, (axis, count) in enumerate(groups):
            if axis.holds(surface.origin, surface.axis):
                groups[index] = (axis, count + 1)
                break
        else:
            groups.append((_Axis(surface.origin, surface.axis), 1))
    if not groups:
        raise ContourError("the part has no round faces (cylinders, cones, ...): it is not a turned part")
    groups.sort(key=lambda g: -g[1])
    return groups[0][0], groups[0][1], sum(count for _axis, count in groups[1:])


# --- pieces of the profile ------------------------------------------------------------------------------------------


def _arc_spans(zc: float, rc: float, radius: float, points: list[ZR], same_sense: bool) -> list[_Span]:
    """The part of the circle (zc, rc, radius) that the face covers, split where it turns in z."""
    angles = sorted(math.atan2(r - rc, z - zc) % math.tau for z, r in points)
    if not angles:
        return []
    gaps = [(angles[(i + 1) % len(angles)] - angles[i]) % math.tau for i in range(len(angles))]
    widest = max(range(len(gaps)), key=gaps.__getitem__)
    start = angles[(widest + 1) % len(angles)]
    sweep = math.tau - gaps[widest] if len(angles) > 1 else 0.0
    cuts = [start] + [k * math.pi for k in range(-2, 5) if start < k * math.pi < start + sweep] + [start + sweep]
    spans = []
    sense = 1.0 if same_sense else -1.0
    for a, b in zip(cuts, cuts[1:]):
        if b - a <= TINY_Z:
            continue
        middle = (a + b) / 2
        z_a, z_b = zc + radius * math.cos(a), zc + radius * math.cos(b)
        upper = math.sin(middle) > 0
        spans.append(
            _Span(min(z_a, z_b), max(z_a, z_b), arc=True, zc=zc, rc=rc, radius=radius, upper=upper,
                  inward=math.sin(middle) * sense < 0)
        )
    return [s for s in spans if s.z2 - s.z1 > TINY_Z]


def _round_face_spans(face: StepFace, axis: _Axis) -> list[_Span]:
    surface = face.surface
    points = [axis.zr(p) for edge in face.edges for p in edge]
    if not points:
        return []
    z1, z2 = min(z for z, _r in points), max(z for z, _r in points)
    inward = not face.same_sense
    if surface.kind == "cylinder":
        return [_Span(z1, z2, surface.radius, surface.radius, inward=inward)] if z2 - z1 > TINY_Z else []
    if surface.kind == "cone":
        z0 = axis.zr(surface.origin)[0]
        slope = math.tan(surface.semi_angle) * (1.0 if _dot(surface.axis, axis.direction) > 0 else -1.0)
        r_at = lambda z: surface.radius + (z - z0) * slope  # noqa: E731
        return [_Span(z1, z2, r_at(z1), r_at(z2), inward=inward)] if z2 - z1 > TINY_Z else []
    if surface.kind in ("torus", "sphere"):
        zc = axis.zr(surface.origin)[0]
        rc = surface.radius if surface.kind == "torus" else 0.0
        radius = surface.minor_radius if surface.kind == "torus" else surface.radius
        return _arc_spans(zc, rc, radius, points, face.same_sense)
    return []


def _simplify(points: list[ZR]) -> list[ZR]:
    """Drop the points that lie on the line between their neighbours (Douglas-Peucker)."""
    if len(points) < 3:
        return points
    (za, ra), (zb, rb) = points[0], points[-1]
    length = math.hypot(zb - za, rb - ra)
    worst, index = 0.0, 0
    for i in range(1, len(points) - 1):
        z, r = points[i]
        if length <= TINY_Z:
            distance = math.hypot(z - za, r - ra)
        else:
            distance = abs((zb - za) * (ra - r) - (za - z) * (rb - ra)) / length
        if distance > worst:
            worst, index = distance, i
    if worst <= STEP_SIMPLIFY_TOLERANCE_MM:
        return [points[0], points[-1]]
    return _simplify(points[: index + 1])[:-1] + _simplify(points[index:])


def _feature_spans(polylines: list[list[ZR]], round_spans: list[_Span]) -> list[_Span]:
    """Line spans of the edges of non-round faces, only where they stick out beyond the round faces."""

    def round_top(z: float) -> float:
        values = [s.at(z) for s in round_spans if s.z1 - TINY_Z <= z <= s.z2 + TINY_Z]
        return max(values) if values else -math.inf

    spans: list[_Span] = []
    for line in polylines:
        outside = [r > round_top(z) + STEP_ENVELOPE_TOLERANCE_MM for z, r in line]
        index = 0
        while index < len(line):
            if not outside[index]:
                index += 1
                continue
            end = index
            while end + 1 < len(line) and outside[end + 1]:
                end += 1
            run = _simplify(line[max(index - 1, 0): min(end + 2, len(line))])
            for (za, ra), (zb, rb) in zip(run, run[1:]):
                if abs(zb - za) > TINY_Z:
                    spans.append(_Span(za, zb, ra, rb, exact=False) if za < zb else _Span(zb, za, rb, ra, exact=False))
            index = end + 1
    return spans


# --- envelopes ------------------------------------------------------------------------------------------------------


def _envelope(spans: list[_Span], upper: bool) -> list[tuple[_Span | None, float, float]]:
    """The largest (upper) or smallest r of the spans along z, as runs (span, z_from, z_to); span None: nothing there."""
    zs = sorted({round(v, 9) for s in spans for v in (s.z1, s.z2)})
    runs: list[tuple[_Span | None, float, float]] = []

    def best(z: float, candidates: list[_Span]) -> _Span:
        if upper:
            return max(candidates, key=lambda s: (round(s.at(z), 7), s.exact))
        return min(candidates, key=lambda s: (round(s.at(z), 7), not s.exact))

    def solve(za: float, zb: float, candidates: list[_Span]) -> None:
        width = zb - za
        picks = [best(za + width * (i + 0.5) / SAMPLES_PER_INTERVAL, candidates) for i in range(SAMPLES_PER_INTERVAL)]
        if all(p is picks[0] for p in picks) or width <= TINY_Z * 10:
            add(picks[len(picks) // 2], za, zb)
            return
        middle = (za + zb) / 2
        solve(za, middle, candidates)
        solve(middle, zb, candidates)

    def add(span: _Span | None, za: float, zb: float) -> None:
        if runs and runs[-1][0] is span and abs(runs[-1][2] - za) <= TINY_Z * 10:
            runs[-1] = (span, runs[-1][1], zb)
        else:
            runs.append((span, za, zb))

    for za, zb in zip(zs, zs[1:]):
        candidates = [s for s in spans if s.z1 <= za + TINY_Z * 10 and s.z2 >= zb - TINY_Z * 10]
        if not candidates:
            add(None, za, zb)
        else:
            solve(za, zb, candidates)
    return runs


def _piece(span: _Span, za: float, zb: float) -> DxfLine | DxfArc:
    """The part of a span between za and zb, in drawing coordinates (X = z, Y = r)."""
    a, b = (za, span.at(za)), (zb, span.at(zb))
    if not span.arc:
        return DxfLine(a, b)
    angle_a = math.degrees(math.atan2(a[1] - span.rc, a[0] - span.zc))
    angle_b = math.degrees(math.atan2(b[1] - span.rc, b[0] - span.zc))
    start, end = (angle_b, angle_a) if span.upper else (angle_a, angle_b)
    return DxfArc((span.zc, span.rc), span.radius, start % 360.0, end % 360.0)


def _chain(runs: list[tuple[_Span, float, float]]) -> list[DxfLine | DxfArc]:
    """The pieces of consecutive runs, joined by steps square to the axis where the radius jumps."""
    pieces: list[DxfLine | DxfArc] = []
    for index, (span, za, zb) in enumerate(runs):
        if index:
            previous, _pa, pb = runs[index - 1]
            r_before, r_after = previous.at(pb), span.at(za)
            if abs(r_before - r_after) > STEP_ENVELOPE_TOLERANCE_MM / 5:
                pieces.append(DxfLine((za, r_before), (za, r_after)))
        if zb - za > TINY_Z * 10:
            pieces.append(_piece(span, za, zb))
    return pieces


def _shift(pieces: list[DxfLine | DxfArc], front: float) -> tuple[DxfLine | DxfArc, ...]:
    """Move z so that the front face is at Z0."""
    moved: list[DxfLine | DxfArc] = []
    for piece in pieces:
        if isinstance(piece, DxfLine):
            moved.append(DxfLine((piece.start[0] - front, piece.start[1]), (piece.end[0] - front, piece.end[1])))
        else:
            moved.append(DxfArc((piece.center[0] - front, piece.center[1]), piece.radius, piece.start_deg, piece.end_deg))
    return tuple(moved)


def turned_profile(solid: StepSolid, front_at_axis_end: bool = True) -> TurnedProfile:
    """The outside and the bores of a turned part. `front_at_axis_end`: the front (Z0) is the end the found axis
    points to; False takes the other end. Raises ContourError."""
    axis, round_count, other_round = find_axis(solid)
    if not front_at_axis_end:
        axis = _Axis(axis.origin, (-axis.direction[0], -axis.direction[1], -axis.direction[2]))
    messages = list(solid.notes)
    round_spans: list[_Span] = []
    polylines: list[list[ZR]] = []
    others = 0
    for face in solid.faces:
        surface = face.surface
        on_axis = (surface.kind in ROUND_KINDS[:3] and axis.holds(surface.origin, surface.axis)) or (
            surface.kind == "sphere" and axis.zr(surface.origin)[1] <= STEP_AXIS_TOLERANCE_MM
        )
        if on_axis:
            round_spans += _round_face_spans(face, axis)
        elif surface.kind == "plane" and axis.parallel(surface.axis):
            continue  # a face square to the axis: a step between the pieces
        else:
            others += 1
            polylines += [[axis.zr(p) for p in edge] for edge in face.edges if len(edge) > 1]
    if not round_spans:
        raise ContourError("no face of the part is round about its axis")
    features = _feature_spans(polylines, round_spans)
    if others:
        messages.append(
            f"{others} face(s) are not round about the axis (flats, hexes, keyways, cross holes, splines, holes on "
            f"other axes): the outline goes round them (turned envelope)"
        )
    if features:
        messages.append(f"the outline follows {len(features)} straight piece(s) of non-round faces (for example hex corners)")

    outside_runs = _envelope(round_spans + features, upper=True)
    if any(span is None for span, _a, _b in outside_runs):
        messages.append("the part has a gap along its axis: only the longest piece is used")
    bore_runs = _envelope([s for s in round_spans if s.inward], upper=False)
    z_min = min(a for _s, a, _b in outside_runs)
    z_max = max(b for _s, _a, b in outside_runs)

    def bore_at(z: float) -> float:
        for span, a, b in bore_runs:
            if span is not None and a - TINY_Z * 10 <= z <= b + TINY_Z * 10:
                return span.at(z)
        return 0.0

    solid_runs = [(s, a, b) for s, a, b in outside_runs if s is not None]
    pieces = _chain(solid_runs)  # type: ignore[arg-type]
    r_front, r_back = solid_runs[-1][0].at(z_max), solid_runs[0][0].at(z_min)
    pieces = [DxfLine((z_min, bore_at(z_min)), (z_min, r_back))] + pieces + [DxfLine((z_max, r_front), (z_max, bore_at(z_max)))]
    pieces = [p for p in pieces if not (isinstance(p, DxfLine) and math.dist(p.start, p.end) <= TINY_Z * 10)]

    bores: list[DxfDrawing] = []
    group: list[tuple[_Span, float, float]] = []
    for span, a, b in bore_runs + [(None, z_max, z_max)]:
        if span is not None:
            group.append((span, a, b))
            continue
        if group:
            bore = _chain(group)
            low, high = group[0], group[-1]
            if low[1] > z_min + STEP_ENVELOPE_TOLERANCE_MM:  # a blind bore: its bottom goes to the axis
                bore.insert(0, DxfLine((low[1], 0.0), (low[1], low[0].at(low[1]))))
            if high[2] < z_max - STEP_ENVELOPE_TOLERANCE_MM:
                bore.append(DxfLine((high[2], high[0].at(high[2])), (high[2], 0.0)))
            bores.append(DxfDrawing(_shift(bore, z_max)))
            group = []
    if other_round:
        messages.append(f"{other_round} round face(s) turn about other axes (cross holes, ...) and are not part of the outline")
    max_radius = max(
        max(s.at(a), s.at(b), s.at(s.zc) if s.arc and a < s.zc < b else 0.0) for s, a, b in solid_runs  # type: ignore[union-attr]
    )
    return TurnedProfile(
        DxfDrawing(_shift(pieces, z_max)), tuple(bores), z_max - z_min, 2 * max_radius, tuple(messages)
    )


def contour_from_profile(profile: TurnedProfile, bore: int | None = None) -> DxfImport:
    """The outside (bore None) or a bore of a turned profile as a contour definition, with the messages."""
    drawing = profile.outside if bore is None else profile.bores[bore]
    return contour_from_chain(DxfDrawing(drawing.entities, profile.messages))
