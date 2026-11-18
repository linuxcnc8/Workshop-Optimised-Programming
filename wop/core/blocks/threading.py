"""Threading block (requirement B3): a thread along Z, outside or inside, straight or tapered (a pipe thread).

The block gives the crest radius (the outer radius of an outside thread, the inner
radius of an inside thread, so the radius the material has been turned or bored
to), the pitch and the Z range (start and end, both absolute). The thread depth
defaults to the ISO metric value. The other values are those of the G76 cycle:
first cut depth (J), degression (R), compound angle (Q), spring passes (H) and
the tapered entry or exit (E, L). A thread is cut at a fixed spindle speed, so the
spindle of this block is only an RPM (a constant surface speed is turned into the
RPM at the crest). The cutting is one thread operation (X4); the postprocessor maps it
to the controller's cycle. The material must already be at the crest radius over the
thread length: the block does not turn it, and says so if there is more material. A tapered thread (`taper_per_100_mm`, the
change of the crest diameter per 100 mm towards the chuck) is a cone: the crest radius is the one at the start Z, and the
passes follow the cone; it needs a post that writes the passes (a G76 cycle cannot taper).
The thread is not drawn as a V profile: the removed area is the whole band of the
thread depth, widened at both ends by what the tool flanks cut, so later blocks and the
collision check see the envelope of the thread.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..constants import (
    EXAMPLE_THREAD_CREST_RADIUS_MM,
    EXAMPLE_THREAD_LENGTH_MM,
    EXAMPLE_THREAD_PITCH_MM,
    EXAMPLE_THREAD_START_Z_MM,
    GEOMETRY_TOLERANCE_MM,
    MM_PER_M,
    THREAD_COMPOUND_ANGLE_DEG,
    THREAD_COMPOUND_ANGLE_LIMIT_DEG,
    THREAD_DEGRESSION_CONSTANT_AREA,
    THREAD_FIRST_CUT_MM,
    THREAD_FLANK_MISMATCH_DEG,
    THREAD_CREST_TOLERANCE_MM,
    THREAD_LEAD_IN_PITCHES,
    THREAD_SPRING_PASSES,
    THREAD_TAPER_LIMIT_PER_100_MM,
    TAPER_PER_100_MM,
)
from ..geometry import LineSegment, Point, Segment
from ..lathe.machine import Capability
from ..program_model.operations import (
    BlockBegin,
    BlockEnd,
    Rapid,
    SpindleMode,
    SpindleSetting,
    ThreadOperation,
    ThreadTaper,
)
from ..geometry.region import Region
from ..thread_designation import ThreadDesignationError, parse_designation, standard_designations
from ..thread_form import ThreadForm, full_profile_depth, tip_correction
from ..tool_types.base import definition_of
from ..tool_types.thread import ThreadProfile
from ..tooling.tool import Tool, ToolError, flank_angles_by_side, flank_reach_by_side
from .base import BLOCK_TYPES, Block, BlockContext, BlockError, BlockResult
from .sweep import Sweeper
from .turning_common import TurningSide


@BLOCK_TYPES.register
@dataclass(frozen=True, kw_only=True)
class ThreadingBlock(Block):
    type_name = "threading"
    required_capabilities = frozenset({Capability.SPINDLE_SYNC})

    side: TurningSide
    designation: str = ""  # M8x1, Tr40x7, 1/4-20 UNC ...: fills pitch, crest radius, depth and compound angle (see with_derived_fields)
    crest_radius_mm: float
    pitch_mm: float
    start_z_mm: float  # the thread starts here (higher Z)
    end_z_mm: float  # the thread ends here (lower Z), absolute; the form can show it as a length
    taper_per_100_mm: float = 0.0  # a tapered thread: the crest diameter grows by this per 100 mm towards the chuck (negative: shrinks)
    thread_form: ThreadForm = ThreadForm.ISO  # the depth for a full-profile insert and the tip correction (set by a designation)
    thread_depth_mm: float | None = None  # the depth cut, as typed (G76 K); None: auto, from the thread form, the pitch and the tool
    tip_correction: bool = True  # the auto depth of a partial-profile tool is corrected for its tip radius
    first_cut_depth_mm: float = THREAD_FIRST_CUT_MM  # G76 J
    degression: float = THREAD_DEGRESSION_CONSTANT_AREA  # G76 R: 1 same depth, 2 same area, more: decreasing area
    compound_angle_deg: float = THREAD_COMPOUND_ANGLE_DEG  # G76 Q
    spring_passes: int = THREAD_SPRING_PASSES  # G76 H
    taper: ThreadTaper = ThreadTaper.NONE  # G76 L
    taper_distance_mm: float = 0.0  # G76 E: used with a taper

    def form_fields(self) -> tuple[str, ...]:
        """The order of the form (the free comment is not shown)."""
        return (
            "name", "side", "designation", "thread_form", "tool_number", "spindle", "crest_radius_mm", "pitch_mm", "start_z_mm", "end_z_mm",
            "taper_per_100_mm", "end_crest_radius_mm", "thread_depth_mm", "tip_correction", "first_cut_depth_mm", "degression", "compound_angle_deg", "spring_passes",
            "taper", "taper_distance_mm", "coolant",
        )

    def form_headings(self) -> dict[str, str]:
        return {"crest_radius_mm": "Thread", "thread_depth_mm": "Passes (G76 J, K, R, Q, H)", "taper": "Run-in and run-out (G76 L, E)"}

    def form_labels(self) -> dict[str, str]:
        return {
            "spindle.value": "Spindle RPM", "designation": "Thread (type, or pick from the list)", "crest_radius_mm": "Crest X radius", "pitch_mm": "Pitch",
            "start_z_mm": "Start Z (front)", "end_z_mm": "End Z",
            "taper_per_100_mm": "Thread taper (diameter per 100 mm; 1:16 = 6.25)", "thread_depth_mm": "Thread depth", "thread_form": "Thread form",
            "tip_correction": "Correct the auto depth for a partial-profile tool",
            "first_cut_depth_mm": "First cut depth", "degression": "Degression", "compound_angle_deg": "Compound angle",
            "spring_passes": "Spring passes", "taper": "Tapered at", "taper_distance_mm": "Taper length",
        }

    def form_hidden(self) -> frozenset[str]:
        return frozenset({"spindle.mode", "spindle.rpm_limit"})  # a thread is cut at a fixed RPM

    def field_suggestions(self) -> dict[str, tuple]:
        """The menu of standard threads beside the designation (by family); the field still takes any designation."""
        return {"designation": standard_designations(self.side is TurningSide.OUTSIDE)}

    def form_relative_ends(self) -> dict[str, tuple[str, str]]:
        return {"end_z_mm": ("start_z_mm", "Length")}  # end field -> (start field, label when shown as a length)

    def form_disabled(self) -> frozenset[str]:
        return frozenset({"taper_distance_mm"}) if self.taper is ThreadTaper.NONE else frozenset()

    @classmethod
    def example(cls, block_id: str, tool_number: int, spindle: SpindleSetting) -> "ThreadingBlock":
        return cls(
            block_id=block_id, name="Thread", tool_number=tool_number, spindle=spindle,
            side=TurningSide.OUTSIDE, crest_radius_mm=EXAMPLE_THREAD_CREST_RADIUS_MM,
            pitch_mm=EXAMPLE_THREAD_PITCH_MM, start_z_mm=EXAMPLE_THREAD_START_Z_MM,
            end_z_mm=EXAMPLE_THREAD_START_Z_MM - EXAMPLE_THREAD_LENGTH_MM,
        )

    def __post_init__(self) -> None:
        if self.designation.strip():
            try:
                parse_designation(self.designation)
            except ThreadDesignationError as error:
                raise BlockError(str(error)) from error
        if self.crest_radius_mm <= 0:
            raise BlockError("the crest radius must be greater than zero")
        if self.pitch_mm <= 0:
            raise BlockError("the pitch must be greater than zero")
        if self.end_z_mm >= self.start_z_mm - GEOMETRY_TOLERANCE_MM:
            raise BlockError("the thread must end behind its start (a lower Z)")
        if self.thread_depth_mm is not None and self.thread_depth_mm <= 0:
            raise BlockError("the thread depth must be greater than zero")
        if self.first_cut_depth_mm <= 0:
            raise BlockError("the first cut depth must be greater than zero")
        if self.spring_passes < 0:
            raise BlockError("the number of spring passes must not be negative")
        if self.degression < 1:
            raise BlockError("the degression must be 1 or more")
        if not 0 <= self.compound_angle_deg < THREAD_COMPOUND_ANGLE_LIMIT_DEG:
            raise BlockError(f"the compound angle must be from 0 to below {THREAD_COMPOUND_ANGLE_LIMIT_DEG} degrees")
        if self.taper_distance_mm < 0:
            raise BlockError("the taper length must not be negative")
        if abs(self.taper_per_100_mm) >= THREAD_TAPER_LIMIT_PER_100_MM:
            raise BlockError(f"the thread taper must be below {THREAD_TAPER_LIMIT_PER_100_MM:g} on the diameter per 100 mm")
        setting = self.spindle  # a thread is cut at a fixed RPM: a surface speed becomes the RPM at the crest
        if setting.mode is not SpindleMode.CONSTANT_RPM or setting.rpm_limit is not None:
            rpm = setting.value
            if setting.mode is SpindleMode.CONSTANT_SURFACE_SPEED:
                rpm = setting.value * MM_PER_M / (math.pi * 2 * self.crest_radius_mm)
            object.__setattr__(self, "spindle", replace(setting, mode=SpindleMode.CONSTANT_RPM, value=rpm, rpm_limit=None))

    @property
    def length_mm(self) -> float:
        return self.start_z_mm - self.end_z_mm

    @property
    def crest_slope(self) -> float:
        """How much the crest radius grows per mm towards the chuck (0 for a straight thread)."""
        return self.taper_per_100_mm / TAPER_PER_100_MM / 2

    def crest_at(self, z: float) -> float:
        return self.crest_radius_mm + self.crest_slope * (self.start_z_mm - z)

    @property
    def end_crest_radius_mm(self) -> float:
        """X2: the crest radius at the end Z, worked out from the crest, the taper and the length (not stored; the taper is)."""
        return self.crest_at(self.end_z_mm)

    def with_end_crest_radius_mm(self, radius: float) -> "ThreadingBlock":
        """The block with the taper that gives this crest radius at the end Z (typing X2 sets the taper per 100 mm)."""
        length = self.start_z_mm - self.end_z_mm
        if abs(length) <= GEOMETRY_TOLERANCE_MM:
            raise BlockError("the thread has no length: set Start Z and End Z before X2")
        taper = 2 * (radius - self.crest_radius_mm) / length * TAPER_PER_100_MM
        return replace(self, taper_per_100_mm=taper)

    def form_computed_fields(self) -> dict[str, str]:
        """Fields worked out from others that can be typed in as well (see with_end_crest_radius_mm)."""
        return {"end_crest_radius_mm": "X2 crest radius at End Z"}

    def with_derived_fields(self, previous: Block | None) -> "ThreadingBlock":
        """A designation fills pitch, crest radius, depth and compound angle when it or the side changes; a pipe thread also
        the taper and the end Z (the start Z plus the thread length of the standard: on a cone the length and the diameters
        belong together).

        Editing pitch, crest radius, depth or taper by hand makes the thread a custom one: the designation is cleared. The
        block keeps the numbers; the G-code never depends on the designation.
        """
        if not self.designation.strip():
            return self
        spec = parse_designation(self.designation)
        same_thread = isinstance(previous, ThreadingBlock) and previous.designation == self.designation and previous.side is self.side
        if same_thread and (
            previous.pitch_mm != self.pitch_mm or previous.crest_radius_mm != self.crest_radius_mm
            or previous.thread_depth_mm != self.thread_depth_mm or previous.taper_per_100_mm != self.taper_per_100_mm
            or previous.thread_form is not self.thread_form
        ):
            return replace(self, designation="")
        if same_thread:
            return self
        values = spec.values_for(self.side is TurningSide.OUTSIDE)
        end_z = self.end_z_mm if values.length_mm is None else self.start_z_mm - values.length_mm
        return replace(
            self, designation=spec.designation, pitch_mm=values.pitch_mm, crest_radius_mm=values.crest_radius_mm,
            thread_depth_mm=self._depth_to_keep(spec.form, values.pitch_mm, values.depth_mm), thread_form=spec.form, compound_angle_deg=values.compound_angle_deg,
            taper_per_100_mm=values.taper_per_100_mm, end_z_mm=end_z,
        )

    def _designation_messages(self, tool_shape) -> tuple[str, ...]:
        if not self.designation.strip():
            return ()
        spec = parse_designation(self.designation)
        values = spec.values_for(self.side is TurningSide.OUTSIDE)
        messages = [values.summary(spec.designation, self.side is TurningSide.OUTSIDE)]
        flanks = flank_angles_by_side(tool_shape)
        wanted = values.flank_half_angle_deg
        if any(abs(flank - wanted) > THREAD_FLANK_MISMATCH_DEG for flank in flanks):
            if abs(flanks[0] - flanks[1]) <= THREAD_FLANK_MISMATCH_DEG:  # a symmetric tool: one angle is enough
                messages.append(
                    f"threading: the flank angle of the tool ({2 * flanks[0]:g} degrees between the flanks) differs from that of "
                    f"{spec.designation} ({2 * wanted:g} degrees): use a threading tool with the right profile"
                )
            else:
                messages.append(
                    f"threading: the flank angles of the tool ({flanks[0]:g} and {flanks[1]:g} degrees from the radial direction) differ from "
                    f"those of {spec.designation} ({wanted:g} each): use a threading tool with the right profile"
                )
        return tuple(messages)

    def _depth_to_keep(self, form: ThreadForm, pitch: float, depth: float) -> float | None:
        """A designation leaves the depth on auto (so it follows the tool), unless its depth is not the form's (a fit allowance)."""
        auto = full_profile_depth(form, pitch, self.side is TurningSide.OUTSIDE)
        return None if abs(depth - auto) <= GEOMETRY_TOLERANCE_MM else depth

    def full_profile_depth(self) -> float:
        """The depth for a full-profile insert: as typed, else from the thread form and the pitch."""
        if self.thread_depth_mm is not None:
            return self.thread_depth_mm
        return full_profile_depth(self.thread_form, self.pitch_mm, self.side is TurningSide.OUTSIDE)

    def tip_radius_of(self, tool: Tool | None) -> float | None:
        """The tip radius when the auto depth is corrected for it: no typed depth, the box ticked and a partial-profile
        threading tool; else None (a typed depth is cut as typed, as in the big-blue Turning panel)."""
        if tool is None or not self.tip_correction or self.thread_depth_mm is not None:
            return None
        try:
            definition = definition_of(tool)
        except ToolError:
            return None
        if getattr(definition, "profile", None) is not ThreadProfile.PARTIAL:
            return None
        return definition.nose_radius_mm

    def depth(self, tool: Tool | None = None) -> float:
        """The radial depth that is cut: as typed; auto, the full-profile depth plus the tip correction of a partial-profile
        tool (`thread_form.tip_correction`, the arithmetic of the big-blue Turning panel)."""
        base = self.full_profile_depth()
        tip = self.tip_radius_of(tool)
        correction = None if tip is None else tip_correction(self.thread_form, self.pitch_mm, self.side is TurningSide.OUTSIDE, tip)
        return base if correction is None else base + correction

    def form_tool_notes(self, tool: Tool | None) -> dict[str, str]:
        """Under the depth field: where the depth that is cut comes from (a partial-profile tool changes the auto depth)."""
        clear = "Clear the field for the auto depth."
        if self.thread_depth_mm is not None:
            return {"thread_depth_mm": f"Cut as typed. {clear}"}
        base = self.full_profile_depth()
        if tool is None:
            return {"thread_depth_mm": f"Auto: {base:.4f} from the thread form and the pitch. Type a depth to cut it as written."}
        try:
            definition = definition_of(tool)
        except ToolError:
            definition = None
        if getattr(definition, "profile", None) is not ThreadProfile.PARTIAL:
            return {"thread_depth_mm": f"Auto: {base:.4f} for T{tool.number} (full profile). Type a depth to cut it as written."}
        tip = definition.nose_radius_mm
        if not self.tip_correction:
            return {"thread_depth_mm": f"Auto: {base:.4f} as for a full profile; T{tool.number} is partial profile (tip R{tip:g}): tick the box "
                                       "below to correct the depth for it."}
        correction = tip_correction(self.thread_form, self.pitch_mm, self.side is TurningSide.OUTSIDE, tip)
        if correction is None:
            return {"thread_depth_mm": f"Auto: {base:.4f} (no tip correction for a {self.thread_form.value} thread)."}
        return {"thread_depth_mm": f"Auto: {base + correction:.4f} = full profile {base:.4f} {'+' if correction >= 0 else '-'} "
                                   f"{abs(correction):.4f} for the tip of T{tool.number} (partial profile, R{tip:g}). Type a depth to cut it as written."}

    def form_tool_placeholders(self, tool: Tool | None) -> dict[str, str]:
        """The empty depth field shows the auto depth that is cut with the chosen tool."""
        return {"thread_depth_mm": f"auto {self.depth(tool):.4f}"}

    def _depth_messages(self, tool: Tool | None) -> tuple[str, ...]:
        """What the depth was worked out from, when a partial-profile tool changes it."""
        tip = self.tip_radius_of(tool)
        if tip is None:
            return ()
        outside = self.side is TurningSide.OUTSIDE
        correction = tip_correction(self.thread_form, self.pitch_mm, outside, tip)
        if correction is None:
            return (f"threading: partial-profile tool T{tool.number}: no tip correction for a {self.thread_form.value} thread; "
                    f"depth {self.full_profile_depth():.4f} as for a full profile",)
        return (f"threading: partial-profile tool T{tool.number} (tip R{tip:g}): depth {self.depth(tool):.4f} = full profile "
                f"{self.full_profile_depth():.4f} {'+' if correction >= 0 else '-'} {abs(correction):.4f} for the tip "
                f"({self.thread_form.value}); gauge the first one and trim on the wear offset",)

    def target_outline(self, context: BlockContext) -> tuple[Segment, ...]:
        """The crest and the root of the thread along its length."""
        sign = 1 if self.side is TurningSide.OUTSIDE else -1
        ends = (self.start_z_mm, self.end_z_mm)
        crest = [Point(self.crest_at(z), z) for z in ends]
        root = [Point(self.crest_at(z) - sign * self.depth(context.tool), z) for z in ends]
        return (LineSegment(*crest), LineSegment(*root))

    def _between(self, z_low: float, z_high: float, near: Callable[[float], float], far: Callable[[float], float]) -> Region:
        """The area between two lines of X along Z (a rectangle on a straight thread)."""
        if self.crest_slope == 0:
            low, high = sorted((near(z_low), far(z_low)))
            return Region.rectangle(low, z_low, high, z_high)
        return Region.from_points([Point(near(z_low), z_low), Point(far(z_low), z_low), Point(far(z_high), z_high), Point(near(z_high), z_high)])

    def generate(self, context: BlockContext) -> BlockResult:
        """The thread as one thread cycle: the checks of the band and of the crest, the way to the start and out again; a note instead when nothing can be cut."""
        header = BlockBegin(0, self.block_id, self.type_name, self.name)
        footer = BlockEnd(self.block_id)
        nothing = BlockResult((header, footer), Region.empty())

        def refuse(text: str) -> BlockResult:
            return BlockResult(nothing.operations, nothing.removed, (f"threading: {text}",))

        sign = 1 if self.side is TurningSide.OUTSIDE else -1
        depth = self.depth(context.tool)
        z_start = self.start_z_mm
        z_end = self.end_z_mm
        crest_at = self.crest_at

        def root_at(z: float) -> float:
            return crest_at(z) - sign * depth

        if min(root_at(z_start), root_at(z_end)) <= GEOMETRY_TOLERANCE_MM:
            return refuse("the thread is deeper than the radius")
        if min(crest_at(z_start), crest_at(z_end)) <= GEOMETRY_TOLERANCE_MM:
            return refuse("the taper reaches the axis within the thread")
        flank_low, flank_high = flank_reach_by_side(context.tool.shape, depth)  # what the flanks cut beyond the ends
        band = self._between(z_end, z_start, crest_at, root_at)
        residual = context.residual
        planned = residual.intersection(band)
        if planned.is_empty:
            bounds = residual.bounds
            if bounds is not None and (z_start <= bounds.min_z or z_end >= bounds.max_z):
                return refuse(
                    f"the thread (Z {z_end:g} to {z_start:g}) is not in the material (Z {bounds.min_z:g} to {bounds.max_z:g}); "
                    "Z is absolute, behind the front face it is negative"
                )
            return refuse("there is no material in the thread band")
        # the material that must be turned or bored to the crest radius first
        top = max(residual.bounds.max_x, crest_at(z_end), crest_at(z_start)) + 1

        def beyond(z: float) -> float:
            return crest_at(z) + sign * THREAD_CREST_TOLERANCE_MM

        outer = (lambda _z: top) if sign > 0 else (lambda _z: 0.0)
        crest_warnings: tuple[str, ...] = ()  # a warning only (the user's decision, 2026-11-18): the thread is written anyway
        if not residual.intersection(self._between(z_end, z_start, beyond, outer)).is_empty:
            if self.crest_slope:
                crest_warnings = (f"threading: WARNING: there is material beyond the crest, turn or bore the cone first (diameter "
                                  f"{2 * crest_at(z_start):.3f} at Z {z_start:g} to {2 * crest_at(z_end):.3f} at Z {z_end:g}); the thread is written anyway",)
            else:
                crest_warnings = (f"threading: WARNING: there is material beyond the crest radius, turn or bore the thread diameter first "
                                  f"(to diameter {2 * self.crest_radius_mm:.3f}); the thread is written anyway",)
        # the tool flanks run out a little beyond both ends of the thread
        margin_band = self._between(z_end - flank_low, z_start + flank_high, crest_at, root_at)
        sweeper = Sweeper(context, residual.difference(margin_band))
        clearance = context.safety.clearance_mm
        lead_in = THREAD_LEAD_IN_PITCHES * self.pitch_mm
        start_point_z = z_start + lead_in
        start_x = crest_at(start_point_z) + sign * clearance
        reached = sweeper.cut_line(Point(start_x, start_point_z), Point(root_at(start_point_z), start_point_z))
        deep_end = sweeper.cut_line(Point(root_at(start_point_z), start_point_z), Point(root_at(z_end), z_end))
        reach_notes: tuple[str, ...] = ()
        if len(reached) < 2 or len(deep_end) < 2 or abs(deep_end[-1].z - z_end) > GEOMETRY_TOLERANCE_MM:
            # as drawn: the thread is written anyway, the checks report where the tool collides
            reach_notes = ("threading: the tool collides on the way to the thread (holder or point); the thread is written as asked, see the problem list",)
        safe_radius = context.safety.safe_radius_mm
        taper, taper_distance = self.taper, self.taper_distance_mm  # a taper that cannot be cut is left out, with a finding
        notes: list[str] = []
        if taper is not ThreadTaper.NONE and taper_distance <= 0:
            notes.append(f"threading: a tapered {taper.value} is selected but no taper length is given; the thread is cut without a taper")
        elif taper is not ThreadTaper.NONE and taper_distance > self.length_mm / 2 + GEOMETRY_TOLERANCE_MM:
            notes.append("threading: the taper length is more than half the thread length; the thread is cut without a taper")
        else:
            notes = []
        if notes:
            taper, taper_distance = ThreadTaper.NONE, 0.0
        operation = ThreadOperation(
            start_x=start_x, start_z=start_point_z, end_z=z_end, pitch_mm=self.pitch_mm,
            peak_offset_mm=crest_at(start_point_z) - start_x,
            first_cut_mm=min(self.first_cut_depth_mm, depth), depth_mm=depth,
            degression=self.degression,
            compound_angle_deg=self.compound_angle_deg, spring_passes=self.spring_passes,
            taper_distance_mm=taper_distance, taper=taper, crest_slope=self.crest_slope,
        )
        operation.pass_depths()  # raises ValueError when the passes would be absurdly many (first cut, degression, spring passes)
        bounds = residual.bounds
        z_front = max(bounds.max_z + clearance, start_point_z)
        z_safe = max(context.safety.safe_z_mm, z_front)
        safe_point = Point(safe_radius, z_safe)
        here = Point(start_x, start_point_z)  # the cycle begins and ends here
        if sign > 0:
            approach = [Rapid(Point(safe_radius, start_point_z)), Rapid(here)]
        elif sweeper.line_is_free(Point(start_x, z_safe), here):  # like a drill: X first, then straight down
            approach = [Rapid(Point(start_x, z_safe))] if z_safe - start_point_z <= GEOMETRY_TOLERANCE_MM else [
                Rapid(Point(start_x, z_safe)), Rapid(here),
            ]
        else:
            approach = [Rapid(Point(safe_radius, z_front)), Rapid(Point(start_x, z_front)), Rapid(here)]
        if sweeper.line_is_free(here, safe_point):  # one rapid to the safe point
            leave = [Rapid(safe_point)]
        elif sign > 0:
            leave = [Rapid(Point(safe_radius, start_point_z)), Rapid(safe_point)]
        else:
            up = Point(start_x, z_front)
            if sweeper.line_is_free(here, up) and sweeper.line_is_free(up, safe_point):
                leave = [Rapid(up), Rapid(safe_point)]
            else:
                leave = [Rapid(up), Rapid(Point(safe_radius, z_front)), Rapid(safe_point)]
        operations = (header, *approach, operation, *leave, footer)
        removed = residual.intersection(margin_band)
        return BlockResult(operations, removed, (*crest_warnings, *reach_notes, *notes, *self._depth_messages(context.tool), *self._designation_messages(context.tool.shape)))
