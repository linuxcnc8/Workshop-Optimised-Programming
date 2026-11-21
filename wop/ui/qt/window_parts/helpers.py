"""Constants and small functions shared by the parts."""

from __future__ import annotations

from ....adapters.project_files import PROJECT_FILE_SUFFIX


MODE_SETUP = "setup"  # the right panel shows the Setup entry (raw part, material, safe positions)


MODE_BLOCK = "block"  # ... the selected block


MODE_CONTOUR = "contour"  # ... the contour chosen in the flow list (C9)


MODE_TOOLS = "tools"  # ... the form of the tool chosen in the Tools view (T8)




MODE_WORKHOLDING = "workholding"  # ... the form of the item chosen in the Workholding view (WH2)


CONTOURS_HEADER = "Contours"


COPY_MENU_TEXT = "Copy"  # right click on a block or contour of the flow list
CONTOUR_MENU_TEXT = "Contour"  # the last entries of the Add block menu
POINTS_MENU_TEXT = "Contour from points..."


PROJECT_FILTER = f"WOP project (*{PROJECT_FILE_SUFFIX} *.json)"


DXF_FILTER = "DXF drawing (*.dxf)"
PART_FILTER = "DXF drawing or STEP part (*.dxf *.DXF *.step *.stp *.STEP *.STP);;DXF drawing (*.dxf *.DXF);;STEP part (*.step *.stp *.STEP *.STP)"
STEP_SUFFIXES = (".step", ".stp")


LIBRARY_FILTER = "Library (*.json)"


GCODE_FILTER = "G-code (*.ngc);;All files (*)"


GCODE_ENCODING = "utf-8"
