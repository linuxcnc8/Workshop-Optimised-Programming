"""Read the solid of a STEP file into faces for the turned-profile import (requirement C17), without a CAD library.

The text is split by `step_part21.py`; here the B-rep is followed: MANIFOLD_SOLID_BREP -> CLOSED_SHELL ->
ADVANCED_FACE (its surface and its edges). Every surface type that a turned part uses (plane, cylinder, cone, torus,
sphere, surface of revolution) is read with its axis; other surfaces are kept as "other" (their edges still count for
the outline). Edges (lines, circles, ellipses, B-splines) are sampled into points. Lengths are converted to mm from
the units of the solid. Making a profile out of the faces is done in `wop/core/turned_profile.py`.
"""

from __future__ import annotations

import math
from pathlib import Path

from ..core.bspline import expand_knots, sample_curve
from ..core.constants import STEP_ARC_SAMPLE_DEG, STEP_LINE_SAMPLE_MM, STEP_SPLINE_SAMPLES_PER_POINT
from ..core.contour import ContourError
from ..core.turned_profile import StepFace, StepSolid, StepSurface, Vec3
from .step_part21 import Entity, Enum, Part21Error, Ref, Typed, parse_part21

INCH_MM = 25.4
SI_PREFIX_TO_MM = {None: 1000.0, "MILLI": 1.0, "CENTI": 10.0, "DECI": 100.0, "KILO": 1e6, "MICRO": 1e-3}
SURFACE_KINDS = {
    "PLANE": "plane",
    "CYLINDRICAL_SURFACE": "cylinder",
    "CONICAL_SURFACE": "cone",
    "TOROIDAL_SURFACE": "torus",
    "DEGENERATE_TOROIDAL_SURFACE": "torus",
    "SPHERICAL_SURFACE": "sphere",
    "SURFACE_OF_REVOLUTION": "revolution",
}


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Vec3) -> Vec3:
    length = math.sqrt(_dot(a, a))
    if length == 0:
        raise ContourError("the STEP file has a direction of length zero")
    return (a[0] / length, a[1] / length, a[2] / length)


def _any_perpendicular(axis: Vec3) -> Vec3:
    helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _unit(_cross(axis, helper))


class _Reader:
    def __init__(self, entities: dict[int, Entity]) -> None:
        self.entities = entities
        self.scale = 1.0  # file length unit -> mm
        self.angle_scale = 1.0  # file angle unit -> radians
        self.skipped: dict[str, int] = {}

    def get(self, ref) -> Entity:
        if not isinstance(ref, Ref) or ref.id not in self.entities:
            raise ContourError(f"the STEP file refers to a missing record {ref!r}")
        return self.entities[ref.id]

    # --- basic geometry -------------------------------------------------------------------------------------------

    def point(self, ref) -> Vec3:
        coordinates = self.get(ref).args[1]
        values = [float(c) * self.scale for c in coordinates] + [0.0, 0.0]
        return (values[0], values[1], values[2])

    def direction(self, ref) -> Vec3:
        values = [float(c) for c in self.get(ref).args[1]] + [0.0, 0.0]
        return _unit((values[0], values[1], values[2]))

    def placement(self, ref) -> tuple[Vec3, Vec3, Vec3]:
        """Origin, axis (z) and reference direction (x) of an AXIS2_PLACEMENT_3D or AXIS1_PLACEMENT."""
        entity = self.get(ref)
        args = entity.args
        origin = self.point(args[1])
        axis = self.direction(args[2]) if len(args) > 2 and args[2] is not None else (0.0, 0.0, 1.0)
        if len(args) > 3 and args[3] is not None:
            reference = self.direction(args[3])
            reference = _unit(_sub(reference, tuple(c * _dot(reference, axis) for c in axis)))  # type: ignore[arg-type]
        else:
            reference = _any_perpendicular(axis)
        return origin, axis, reference

    # --- units ------------------------------------------------------------------------------------------------------

    def read_units(self, context: Entity | None) -> None:
        """Length and angle units of the solid's context (all units of the file when there is no context)."""
        units: list[Entity] = []
        if context is not None and context.has("GLOBAL_UNIT_ASSIGNED_CONTEXT"):
            units = [self.get(r) for r in context.parts["GLOBAL_UNIT_ASSIGNED_CONTEXT"][0]]
        if not units:
            units = [e for e in self.entities.values() if e.has("LENGTH_UNIT") or e.has("PLANE_ANGLE_UNIT")]
        for unit in units:
            if unit.has("LENGTH_UNIT"):
                self.scale = self._unit_factor(unit, length=True)
            elif unit.has("PLANE_ANGLE_UNIT"):
                self.angle_scale = self._unit_factor(unit, length=False)

    def _unit_factor(self, unit: Entity, length: bool) -> float:
        if unit.has("SI_UNIT"):
            prefix, name = unit.parts["SI_UNIT"][0], unit.parts["SI_UNIT"][1]
            if not length:
                return 1.0  # radian (steradian is not an angle of a cone)
            key = prefix.name if isinstance(prefix, Enum) else None
            if key not in SI_PREFIX_TO_MM or not isinstance(name, Enum) or name.name != "METRE":
                raise ContourError(f"unknown length unit in the STEP file: {prefix} {name}")
            return SI_PREFIX_TO_MM[key]
        if unit.has("CONVERSION_BASED_UNIT"):
            label, measure_ref = unit.parts["CONVERSION_BASED_UNIT"][:2]
            measure = self.get(measure_ref)
            amount = measure.args[0]
            factor = float(amount.args[0]) if isinstance(amount, Typed) else float(amount)
            base = self.get(measure.args[1])
            return factor * self._unit_factor(base, length)
        if length:
            raise ContourError("the STEP file has a length unit that WOP cannot read")
        return 1.0

    # --- curves -----------------------------------------------------------------------------------------------------

    def sample_edge(self, edge: Entity) -> list[Vec3]:
        """Points along an EDGE_CURVE from its start vertex to its end vertex."""
        start = self.point(self.get(edge.args[1]).args[1])
        end = self.point(self.get(edge.args[2]).args[1])
        curve = self.get(edge.args[3])
        same_sense = not (isinstance(edge.args[4], Enum) and edge.args[4].name == "F")
        return self.sample_curve(curve, start, end, same_sense)

    def sample_curve(self, curve: Entity, start: Vec3, end: Vec3, same_sense: bool) -> list[Vec3]:
        name = curve.name
        if curve.has("SURFACE_CURVE") or curve.has("SEAM_CURVE"):
            inner = curve.parts.get("SURFACE_CURVE") or curve.parts["SEAM_CURVE"]
            return self.sample_curve(self.get(inner[1]), start, end, same_sense)
        if name == "LINE":
            return self._line(start, end)
        if name == "CIRCLE":
            origin, axis, reference = self.placement(curve.args[1])
            radius = float(curve.args[2]) * self.scale
            return self._conic(origin, axis, reference, radius, radius, start, end, same_sense)
        if name == "ELLIPSE":
            origin, axis, reference = self.placement(curve.args[1])
            a, b = float(curve.args[2]) * self.scale, float(curve.args[3]) * self.scale
            return self._conic(origin, axis, reference, a, b, start, end, same_sense)
        if curve.has("B_SPLINE_CURVE_WITH_KNOTS") or curve.has("B_SPLINE_CURVE"):
            return self._spline(curve, start, end)
        if name == "TRIMMED_CURVE":
            return self.sample_curve(self.get(curve.args[1]), start, end, same_sense)
        self.skipped[name] = self.skipped.get(name, 0) + 1
        return self._line(start, end)

    def _line(self, start: Vec3, end: Vec3) -> list[Vec3]:
        length = math.dist(start, end)
        count = max(1, math.ceil(length / STEP_LINE_SAMPLE_MM))
        return [tuple(s + (e - s) * i / count for s, e in zip(start, end)) for i in range(count + 1)]  # type: ignore[misc]

    def _conic(
        self, origin: Vec3, axis: Vec3, reference: Vec3, a: float, b: float, start: Vec3, end: Vec3, same_sense: bool
    ) -> list[Vec3]:
        other = _cross(axis, reference)

        def angle(p: Vec3) -> float:
            d = _sub(p, origin)
            return math.atan2(_dot(d, other) / b, _dot(d, reference) / a)

        first, last = angle(start), angle(end)
        if same_sense:
            sweep = (last - first) % math.tau
        else:
            sweep = -((first - last) % math.tau)
        if abs(sweep) < 1e-9:
            sweep = math.tau if same_sense else -math.tau  # a closed edge: the full circle
        count = max(4, math.ceil(abs(math.degrees(sweep)) / STEP_ARC_SAMPLE_DEG))
        points = []
        for i in range(count + 1):
            t = first + sweep * i / count
            c, s = a * math.cos(t), b * math.sin(t)
            points.append(tuple(o + c * r + s * q for o, r, q in zip(origin, reference, other)))
        return points  # type: ignore[return-value]

    def _spline(self, curve: Entity, start: Vec3, end: Vec3) -> list[Vec3]:
        base = curve.parts.get("B_SPLINE_CURVE") or curve.args
        degree = int(base[0] if curve.has("B_SPLINE_CURVE") else base[1])
        control_refs = base[1] if curve.has("B_SPLINE_CURVE") else base[2]
        if curve.has("B_SPLINE_CURVE_WITH_KNOTS") and curve.has("B_SPLINE_CURVE"):
            knot_args = curve.parts["B_SPLINE_CURVE_WITH_KNOTS"]
            multiplicities, knot_values = knot_args[0], knot_args[1]
        else:
            multiplicities, knot_values = curve.args[6], curve.args[7]
        weights = None
        if curve.has("RATIONAL_B_SPLINE_CURVE"):
            weights = [float(w) for w in curve.parts["RATIONAL_B_SPLINE_CURVE"][0]]
        points = [self.point(r) for r in control_refs]
        knots = expand_knots(multiplicities, knot_values)
        samples = sample_curve(degree, points, knots, max(16, STEP_SPLINE_SAMPLES_PER_POINT * len(points)), weights)
        # the edge may use only a part of the curve: keep the samples between the points nearest its vertices
        nearest_start = min(range(len(samples)), key=lambda i: math.dist(samples[i][1], start))
        nearest_end = min(range(len(samples)), key=lambda i: math.dist(samples[i][1], end))
        low, high = sorted((nearest_start, nearest_end))
        if low == high:
            low, high = 0, len(samples) - 1  # a closed spline
        return [start] + [p for _u, p in samples[low + 1:high]] + [end]

    # --- surfaces and faces -----------------------------------------------------------------------------------------

    def surface(self, entity: Entity) -> StepSurface:
        name = entity.name
        kind = SURFACE_KINDS.get(name, "other")
        if kind == "other":
            return StepSurface("other", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), step_type=name)
        if kind == "revolution":
            origin, axis, _reference = self.placement(entity.args[2])
            return StepSurface(kind, origin, axis, step_type=name)
        origin, axis, _reference = self.placement(entity.args[1])
        radius = float(entity.args[2]) * self.scale if len(entity.args) > 2 else 0.0
        if kind == "cone":
            return StepSurface(kind, origin, axis, radius, semi_angle=float(entity.args[3]) * self.angle_scale, step_type=name)
        if kind == "torus":
            return StepSurface(kind, origin, axis, radius, float(entity.args[3]) * self.scale, step_type=name)
        return StepSurface(kind, origin, axis, radius, step_type=name)

    def face(self, entity: Entity) -> StepFace:
        args = entity.args
        surface = self.surface(self.get(args[2]))
        same_sense = not (isinstance(args[3], Enum) and args[3].name == "F")
        edges: list[tuple[Vec3, ...]] = []
        for bound_ref in args[1]:
            loop = self.get(self.get(bound_ref).args[1])
            if loop.name == "VERTEX_LOOP":
                edges.append((self.point(self.get(loop.args[1]).args[1]),))
                continue
            for oriented_ref in loop.args[1]:
                edge = self.get(self.get(oriented_ref).args[3])
                edges.append(tuple(self.sample_edge(edge)))
        return StepFace(surface, same_sense, tuple(edges))


def _solids(entities: dict[int, Entity]) -> list[tuple[Entity, Entity | None]]:
    """Every MANIFOLD_SOLID_BREP with the context of the representation that holds it."""
    holder: dict[int, Entity] = {}
    for entity in entities.values():
        if entity.name in ("ADVANCED_BREP_SHAPE_REPRESENTATION", "MANIFOLD_SURFACE_SHAPE_REPRESENTATION", "SHAPE_REPRESENTATION"):
            for item in entity.args[1]:
                if isinstance(item, Ref):
                    holder[item.id] = entities.get(entity.args[2].id) if isinstance(entity.args[2], Ref) else None  # type: ignore[assignment]
    return [(e, holder.get(e.id)) for e in entities.values() if e.name in ("MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS")]


def read_step(path: Path) -> StepSolid:
    """The faces of the solid(s) of a STEP file, in mm. Raises ContourError with a readable message."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ContourError(f"cannot read {path.name}: {error}") from error
    try:
        entities = parse_part21(text)
    except Part21Error as error:
        raise ContourError(f"cannot read {path.name}: {error}") from error
    reader = _Reader(entities)
    solids = _solids(entities)
    if not solids:
        raise ContourError(f"{path.name} has no solid (only solid parts can be imported, not surfaces or assemblies of surfaces)")
    notes: list[str] = []
    if len(solids) > 1:
        notes.append(f"the file holds {len(solids)} solids: all of them are used")
    faces: list[StepFace] = []
    try:
        reader.read_units(solids[0][1])
        for solid, _context in solids:
            shell = reader.get(solid.args[1])
            for face_ref in shell.args[1]:
                faces.append(reader.face(reader.get(face_ref)))
    except (IndexError, TypeError, ValueError, AttributeError) as error:
        raise ContourError(f"cannot follow the solid in {path.name}: {error}") from error
    for name, count in sorted(reader.skipped.items()):
        notes.append(f"{count} edge(s) of type {name} were taken as straight lines")
    return StepSolid(tuple(faces), tuple(notes))
