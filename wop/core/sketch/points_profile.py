"""A contour typed as points (requirement C12): one row per corner, X and Z, with a radius (R) or a chamfer (C) at the corner, the way
the Turning panel of the big-blue lathe takes a profile.

`sketch_from_rows` draws the rows as a sketch: straight lines from point to point, the corners rounded or cut by the sketch's own fillet
and chamfer, so the sketch editor can still change it. `rows_from_sketch` reads such a sketch back into rows: a fillet or chamfer keeps
its sharp corner in the sketch (`CornerLink`), so a radius comes back as R and a chamfer as C on the row of its corner. An outline with
an arc that is not the radius of a corner cannot be written as rows. `parse_profile_text` reads the text of the Turning panel: one point
per line, `X Z [R<radius> | C<chamfer>]`, X a diameter, commas allowed, `;`, `#` or `(` start a comment.

X is a radius in the rows (the program's convention); the dialog and the text convert at their edge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..contour import CornerKind
from ..geometry import Point
from .corners import chamfer_corner, fillet_corner
from .loops import find_chains
from .model import Sketch, SketchArc, SketchError

MIN_ROWS = 2
COMMENT_STARTS = (";", "#", "(")
_CORNER_WORD = re.compile(r"^([RC])(\d+(?:\.\d+)?|\.\d+)$", re.IGNORECASE)


class ProfileError(ValueError):
    """The rows cannot make a contour; `index` is the row (0-based) when one row is the reason."""

    def __init__(self, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.index = index


@dataclass(frozen=True)
class ProfileRow:
    x: float  # radius
    z: float
    corner: CornerKind = CornerKind.NONE  # FILLET: a radius at this corner, CHAMFER: a chamfer
    size_mm: float = 0.0  # the radius, or the chamfer measured along each side from the sharp corner

    @property
    def position(self) -> Point:
        return Point(self.x, self.z)


def check_rows(rows: list[ProfileRow] | tuple[ProfileRow, ...]) -> None:
    """Raises ProfileError when the rows cannot be drawn (before any geometry is made)."""
    if len(rows) < MIN_ROWS:
        raise ProfileError(f"a contour needs at least {MIN_ROWS} points")
    for index, row in enumerate(rows):
        if row.x < 0:
            raise ProfileError(f"point {index + 1}: X is below the spindle axis", index)
        if row.corner is not CornerKind.NONE:
            if index in (0, len(rows) - 1):
                raise ProfileError(f"point {index + 1}: the first and the last point have no corner, so no radius or chamfer", index)
            if row.size_mm <= 0:
                raise ProfileError(f"point {index + 1}: the radius or chamfer must be more than zero", index)
        if index and row.position.distance_to(rows[index - 1].position) <= 0:
            raise ProfileError(f"point {index + 1}: the same as the point before it", index)


def sketch_from_rows(rows: list[ProfileRow] | tuple[ProfileRow, ...]) -> Sketch:
    """The rows drawn as a sketch: lines from point to point, then the corners rounded (R) or cut (C)."""
    check_rows(rows)
    sketch = Sketch()
    ids = [sketch.add_point(row.x, row.z) for row in rows]
    for start, end in zip(ids, ids[1:]):
        sketch.add_line(start, end)
    for index, (row, point_id) in enumerate(zip(rows, ids)):
        try:
            if row.corner is CornerKind.FILLET:
                fillet_corner(sketch, point_id, row.size_mm)
            elif row.corner is CornerKind.CHAMFER:
                chamfer_corner(sketch, point_id, row.size_mm)
        except (SketchError, ValueError) as error:
            raise ProfileError(f"point {index + 1}: the {'radius' if row.corner is CornerKind.FILLET else 'chamfer'} does not fit ({error})", index) from None
    return sketch


def rows_from_sketch(sketch: Sketch) -> list[ProfileRow]:
    """The outline of the sketch as rows, front (highest Z) first. Raises ProfileError when it cannot be written as rows."""
    try:
        chains = find_chains(sketch)
    except SketchError as error:
        raise ProfileError(str(error)) from None
    if len(chains) != 1 or chains[0].closed:
        raise ProfileError("the points table needs one open outline; edit this contour in the sketch editor")
    chain = chains[0]
    first, forward = chain.pieces[0], chain.forward[0]
    rows = [_row(sketch, first.start if forward else first.end)]
    for piece, goes_forward in zip(chain.pieces, chain.forward):
        piece_id = piece.arc_id if isinstance(piece, SketchArc) else piece.line_id
        link = sketch.corners.get(piece_id)
        if link is not None:  # a fillet or chamfer: its sharp corner replaces the end of the piece before it
            corner = sketch.point(link.point)
            if isinstance(piece, SketchArc):
                centre, start = sketch.point(piece.centre), sketch.point(piece.start)
                rows[-1] = ProfileRow(corner.x, corner.z, CornerKind.FILLET, centre.position.distance_to(start.position))
            else:
                rows[-1] = ProfileRow(corner.x, corner.z, CornerKind.CHAMFER, corner.position.distance_to(sketch.point(piece.start).position))
            continue
        if isinstance(piece, SketchArc):
            raise ProfileError("the outline has an arc that is not the radius of a corner; edit this contour in the sketch editor")
        rows.append(_row(sketch, piece.end if goes_forward else piece.start))
    if rows[0].z < rows[-1].z:
        rows.reverse()
    return rows


def _row(sketch: Sketch, point_id: int) -> ProfileRow:
    point = sketch.point(point_id)
    return ProfileRow(point.x, point.z)


def parse_profile_text(text: str, x_is_diameter: bool = True) -> list[ProfileRow]:
    """Rows from the text of the Turning panel: `X Z [R.. | C..]` per line (X a diameter unless told otherwise). Raises ProfileError
    with the line number."""
    rows: list[ProfileRow] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for start in COMMENT_STARTS:
            line = line.split(start, 1)[0]
        words = line.replace(",", " ").split()
        if not words:
            continue
        if len(words) not in (2, 3):
            raise ProfileError(f"line {number}: write X Z and maybe R<radius> or C<chamfer>, for example 40 -20 R2")
        try:
            x, z = float(words[0]), float(words[1])
        except ValueError:
            raise ProfileError(f"line {number}: X and Z must be numbers") from None
        corner, size = CornerKind.NONE, 0.0
        if len(words) == 3:
            found = _CORNER_WORD.match(words[2])
            if found is None:
                raise ProfileError(f"line {number}: the corner is R<radius> or C<chamfer>, for example R2 or C0.5")
            corner = CornerKind.FILLET if found.group(1).upper() == "R" else CornerKind.CHAMFER
            size = float(found.group(2))
        rows.append(ProfileRow(x / 2 if x_is_diameter else x, z, corner, size))
    return rows


def profile_text(rows: list[ProfileRow], x_is_diameter: bool = True) -> str:
    """The rows as the text `parse_profile_text` reads (X a diameter unless told otherwise)."""
    lines = []
    for row in rows:
        x = row.x * 2 if x_is_diameter else row.x
        words = [f"{x:.4f}".rstrip("0").rstrip("."), f"{row.z:.4f}".rstrip("0").rstrip(".")]
        if row.corner is not CornerKind.NONE:
            words.append(("R" if row.corner is CornerKind.FILLET else "C") + f"{row.size_mm:.4f}".rstrip("0").rstrip("."))
        lines.append(" ".join(words))
    return "\n".join(lines)
