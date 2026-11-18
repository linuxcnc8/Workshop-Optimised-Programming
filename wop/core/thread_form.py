"""Thread forms: the depth of a thread for a full-profile insert, and the correction for a partial-profile insert.

The arithmetic is that of the big-blue lathe's Turning panel (`thread_data.thread_depth`), checked there on the machine
against gauges. A full-profile insert has the form's own root radius r_std. A partial-profile insert with tip radius r sits
back from its own virtual apex by r x k, k = 1 / sin(angle / 2) - 1, and it is that apex which must land on the thread's
apex for the flanks (and so the pitch diameter) to come out right. So it goes deeper by

    (r_std - r) x k

which is zero for a full-profile insert; below about 1.4 mm pitch a 0.2 mm tip is blunter than full form on a 60 degree
thread and the correction is negative. NPT is truncated flat: its 0.033 P truncation is entered as the setback of a radius
with the same effect. The fit allowance, the real ground radius of an insert and deflection are not known here: cut one,
gauge it and trim on the wear offset.

A trapezoidal thread has a flat root and no tip correction.
"""

from __future__ import annotations

import math
from enum import Enum

from .constants import (
    THREAD_FORMS,
    THREAD_TRAPEZOID_CLEARANCES,
    THREAD_TRAPEZOID_HEIGHT_FACTOR,
)


class ThreadForm(Enum):
    ISO = "ISO / Unified 60 deg"
    WHITWORTH = "Whitworth / BSP 55 deg"
    NPT = "NPT 60 deg (flat root)"
    TRAPEZOIDAL = "Trapezoidal 30 deg"


def trapezoid_flank_height(pitch: float) -> float:
    """ISO 2904: the flank height of a trapezoidal thread, 0.5 x pitch plus the clearance of its pitch."""
    clearance = THREAD_TRAPEZOID_CLEARANCES[-1][1]
    for limit, value in THREAD_TRAPEZOID_CLEARANCES:
        if pitch <= limit:
            clearance = value
            break
    return THREAD_TRAPEZOID_HEIGHT_FACTOR * pitch + clearance


def _row(form: ThreadForm) -> tuple | None:
    return next((row for row in THREAD_FORMS if row[0] == form.value), None)


def _sharp_height(angle_deg: float) -> float:
    """The height of the sharp V as a multiple of the pitch."""
    return 1 / (2 * math.tan(math.radians(angle_deg / 2)))


def tip_setback_factor(angle_deg: float) -> float:
    """How far a tip radius sits back from the apex of the V, per mm of radius (1 at 60 degrees, 1.166 at 55)."""
    return 1 / math.sin(math.radians(angle_deg / 2)) - 1


def full_profile_depth(form: ThreadForm, pitch: float, outside: bool) -> float:
    """The radial depth of the thread for a full-profile insert (the classic h x pitch)."""
    row = _row(form)
    if row is None:
        return trapezoid_flank_height(pitch)
    _name, angle, depth_outside, depth_inside, _root_outside, _root_inside = row
    return (depth_outside if outside else depth_inside) * _sharp_height(angle) * pitch


def standard_root_radius(form: ThreadForm, pitch: float, outside: bool) -> float | None:
    """The root radius of a full-profile insert at this pitch; None for a form with no tip correction (trapezoidal)."""
    row = _row(form)
    if row is None:
        return None
    _name, angle, _depth_outside, _depth_inside, root_outside, root_inside = row
    return (root_outside if outside else root_inside) * _sharp_height(angle) * pitch


def tip_correction(form: ThreadForm, pitch: float, outside: bool, tip_radius: float) -> float | None:
    """How much deeper (negative: shallower) a partial-profile insert with this tip radius goes than a full-profile one;
    None for a form with no tip correction (trapezoidal)."""
    row = _row(form)
    root = standard_root_radius(form, pitch, outside)
    if row is None or root is None:
        return None
    return (root - tip_radius) * tip_setback_factor(row[1])
