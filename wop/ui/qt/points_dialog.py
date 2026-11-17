"""The points table of a contour (requirement C12): one row per corner, X and Z with a radius (R) or a chamfer (C), the way the Turning
panel of the big-blue lathe takes a profile. The picture under the table shows the contour as it is typed; OK stays off until it is
one. X is shown as a diameter or a radius as the project says; the text of "Paste text..." is always the Turning panel's: X a diameter.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.contour import CornerKind
from ...core.geometry import LineSegment
from ...core.sketch.model import SketchError
from ...core.sketch.modes import TURNING, contour_from_sketch
from ...core.sketch.points_profile import ProfileError, ProfileRow, parse_profile_text, profile_text, sketch_from_rows

X_COLUMN, Z_COLUMN, CORNER_COLUMN, SIZE_COLUMN = range(4)
CORNERS = ((CornerKind.NONE, "sharp"), (CornerKind.FILLET, "R  radius"), (CornerKind.CHAMFER, "C  chamfer"))
PREVIEW_HEIGHT_PX = 220
PREVIEW_MARGIN_PX = 14
ARC_STEPS = 16  # an arc of the picture is drawn as this many short lines
POINT_DOT_PX = 3
CHOSEN_DOT_PX = 5
NUMBER_FORMAT = "{:.4f}"
EMPTY_ROWS = 2  # a new table starts with this many empty rows


def _number_text(value: float) -> str:
    return NUMBER_FORMAT.format(value).rstrip("0").rstrip(".") or "0"


class ProfilePreview(QWidget):
    """The contour of the table: X up, Z to the right, the spindle axis dash-dotted, the typed points as dots (the chosen one larger)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(PREVIEW_HEIGHT_PX)
        self.segments: tuple = ()
        self.points: list[tuple[float, float]] = []  # (x radius, z) of the rows
        self.chosen: int | None = None

    def show_profile(self, segments: tuple, points: list[tuple[float, float]], chosen: int | None) -> None:
        self.segments, self.points, self.chosen = segments, points, chosen
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        outline = [segment.point_at(step / ARC_STEPS) for segment in self.segments
                   for step in (range(ARC_STEPS + 1) if not isinstance(segment, LineSegment) else (0, ARC_STEPS))]
        xs = [0.0] + [p.x for p in outline] + [x for x, _z in self.points]
        zs = [p.z for p in outline] + [z for _x, z in self.points]
        if not zs:
            return
        span_x, span_z = max(max(xs) - min(xs), 1e-6), max(max(zs) - min(zs), 1e-6)
        width, height = self.width() - 2 * PREVIEW_MARGIN_PX, self.height() - 2 * PREVIEW_MARGIN_PX
        scale = min(width / span_z, height / span_x)
        low_z, low_x = min(zs), min(xs)

        def place(x: float, z: float) -> QPointF:
            return QPointF(PREVIEW_MARGIN_PX + (z - low_z) * scale, self.height() - PREVIEW_MARGIN_PX - (x - low_x) * scale)

        axis = QPen(self.palette().mid().color(), 1, Qt.DashDotLine)
        painter.setPen(axis)
        painter.drawLine(place(0, low_z), place(0, low_z + span_z))
        if outline:
            path = QPainterPath(place(outline[0].x, outline[0].z))
            for point in outline[1:]:
                path.lineTo(place(point.x, point.z))
            painter.setPen(QPen(self.palette().text().color(), 2))
            painter.drawPath(path)
        for index, (x, z) in enumerate(self.points):
            chosen = index == self.chosen
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#d33") if chosen else self.palette().highlight().color())
            size = CHOSEN_DOT_PX if chosen else POINT_DOT_PX
            painter.drawEllipse(place(x, z), size, size)


class PointsDialog(QDialog):
    """`rows` the points to start with (radius X), `x_diameter` how X is shown. After OK, `rows()` are the points."""

    def __init__(self, parent: QWidget | None, title: str, rows: list[ProfileRow], x_diameter: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.x_diameter = x_diameter
        self._result: list[ProfileRow] = []
        self._filling = False
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([f"X ({'diameter' if x_diameter else 'radius'})", "Z", "Corner", "Size"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(lambda _item: self._changed())
        self.table.currentCellChanged.connect(lambda *_cells: self._changed())
        buttons = QHBoxLayout()
        for text, tip, handler in (
            ("Add point", "A new point at the end", self._add),
            ("Insert point", "A new point before the chosen one", self._insert),
            ("Delete point", "Delete the chosen point", self._delete),
            ("Up", "Move the chosen point up", lambda: self._move(-1)),
            ("Down", "Move the chosen point down", lambda: self._move(1)),
            ("Paste text...", "The points as text, as the Turning panel writes them (X Z R.. or C..; X a diameter): copy them, or paste a profile", self._paste),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            buttons.addWidget(button)
        self.preview = ProfilePreview()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.box.accepted.connect(self._accept)
        self.box.rejected.connect(self.reject)
        hint = QLabel("One row per corner, from the front (Z0) towards the chuck. A corner gets a radius (R) or a chamfer (C); the first and "
                      "the last point have none. The contour starts on the axis (X 0) at the face for a solid part.")
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.preview)
        layout.addWidget(self.status)
        layout.addWidget(self.box)
        self._fill(rows)
        if not rows:
            for _ in range(EMPTY_ROWS):
                self._add()
        self._changed()

    # --- the table -------------------------------------------------------------------------------------------------------------
    def _fill(self, rows: list[ProfileRow]) -> None:
        self._filling = True
        self.table.setRowCount(0)
        for row in rows:
            self._put_row(self.table.rowCount(), row)
        self._filling = False

    def _put_row(self, position: int, row: ProfileRow | None) -> None:
        self._filling, was = True, self._filling
        self.table.insertRow(position)
        scale = 2 if self.x_diameter else 1
        texts = ("", "", "") if row is None else (_number_text(row.x * scale), _number_text(row.z), _number_text(row.size_mm) if row.size_mm else "")
        for column, text in zip((X_COLUMN, Z_COLUMN, SIZE_COLUMN), texts):
            self.table.setItem(position, column, QTableWidgetItem(text))
        choice = QComboBox()
        for kind, label in CORNERS:
            choice.addItem(label, kind)
        if row is not None:
            choice.setCurrentIndex([kind for kind, _label in CORNERS].index(row.corner))
        choice.currentIndexChanged.connect(lambda _index: self._changed())
        self.table.setCellWidget(position, CORNER_COLUMN, choice)
        self._filling = was

    def _row_values(self, position: int) -> ProfileRow:
        """One row of the table; raises ProfileError when a number is missing or wrong."""
        def number(column: int, name: str, required: bool = True) -> float:
            item = self.table.item(position, column)
            text = (item.text() if item is not None else "").strip().replace(",", ".")
            if not text:
                if required:
                    raise ProfileError(f"point {position + 1}: {name} is empty", position)
                return 0.0
            try:
                return float(text)
            except ValueError:
                raise ProfileError(f"point {position + 1}: {name} is not a number", position) from None

        x = number(X_COLUMN, "X") / (2 if self.x_diameter else 1)
        z = number(Z_COLUMN, "Z")
        kind = self.table.cellWidget(position, CORNER_COLUMN).currentData()
        size = number(SIZE_COLUMN, "the size", kind is not CornerKind.NONE)
        return ProfileRow(x, z, kind, size if kind is not CornerKind.NONE else 0.0)

    def table_rows(self) -> list[ProfileRow]:
        return [self._row_values(position) for position in range(self.table.rowCount())]

    def rows(self) -> list[ProfileRow]:
        """The points after OK."""
        return self._result

    # --- buttons -----------------------------------------------------------------------------------------------------------------
    def _chosen(self) -> int:
        return self.table.currentRow()

    def _add(self) -> None:
        self._put_row(self.table.rowCount(), None)
        self.table.setCurrentCell(self.table.rowCount() - 1, X_COLUMN)
        self._changed()

    def _insert(self) -> None:
        position = max(self._chosen(), 0)
        self._put_row(position, None)
        self.table.setCurrentCell(position, X_COLUMN)
        self._changed()

    def _delete(self) -> None:
        position = self._chosen()
        if position >= 0:
            self.table.removeRow(position)
            self._changed()

    def _move(self, step: int) -> None:
        position = self._chosen()
        other = position + step
        if position < 0 or not 0 <= other < self.table.rowCount():
            return
        try:
            rows = self.table_rows()
        except ProfileError as error:
            self.status.setText(f"Fill the row in first: {error}")
            return
        rows[position], rows[other] = rows[other], rows[position]
        self._fill(rows)
        self.table.setCurrentCell(other, X_COLUMN)
        self._changed()

    def _paste(self) -> None:
        try:
            current = profile_text(self.table_rows())
        except ProfileError:
            current = ""
        text, ok = QInputDialog.getMultiLineText(
            self, "Points as text", "One point per line: X Z, then R<radius> or C<chamfer> if the corner has one. X is a diameter.", current)
        if not ok:
            return
        try:
            rows = parse_profile_text(text, x_is_diameter=True)
        except ProfileError as error:
            self.status.setText(str(error))
            return
        self._fill(rows)
        self._changed()

    # --- checking --------------------------------------------------------------------------------------------------------------
    def _changed(self) -> None:
        if self._filling:
            return
        ok_button = self.box.button(QDialogButtonBox.Ok)
        chosen = self._chosen() if self._chosen() >= 0 else None
        points: list[tuple[float, float]] = []
        try:
            rows = self.table_rows()
            points = [(row.x, row.z) for row in rows]
            contour = contour_from_sketch(sketch_from_rows(rows), TURNING, "points", "points")
        except (ProfileError, SketchError) as error:
            self.preview.show_profile((), points, chosen)
            self.status.setText(str(error))
            ok_button.setEnabled(False)
            return
        self.preview.show_profile(contour.segments, points, chosen)
        self.status.setText("The contour is fine.")
        ok_button.setEnabled(True)

    def _accept(self) -> None:
        try:
            self._result = self.table_rows()
        except ProfileError as error:
            self.status.setText(str(error))
            return
        self.accept()
