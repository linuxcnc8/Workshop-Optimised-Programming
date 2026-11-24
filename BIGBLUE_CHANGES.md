# Changes on branch `bigblue-changes`

Changes made on top of WOP v0.1.0 (GitHub `LooksAboutRight/Workshop-Optimised-Programming`, base commit `82a637d`)
for one user's LinuxCNC lathe ("Big Blue", Mesa hardware, LinuxCNC on Debian 13). They were written with Claude Code
following this repository's own rules (`CLAUDE.md`, `docs/wop_03_conventions.md`): each commit keeps the docs, the
manual, the requirements and the tests in step, and the full suite was green before each commit.

This file is for the author, to see what changed and why, and to merge what he wants. Each feature is in its own
commit (or two), so commits can be picked one by one. `git log 82a637d..bigblue-changes` lists them;
`git diff 82a637d bigblue-changes` shows everything.

## At a glance

| Commit | What | Requirement IDs |
|---|---|---|
| `6b403c0` | Threads as longhand G33 passes (`threading_style = synced_passes`); fix: LinuxCNC G76 ends at the end Z | O35, O36 |
| `d411501` | Tapered threads; pipe thread designations BSPT (R / Rc) and NPT | N54, N55 |
| `c632103` | Facing: stock on the face (`face_stock_mm`) and two new Preferences | X16 |
| `ec6b614` | Contour from points: a points table with R / C corners, paste from text | C16 |
| `5a61b19` | Threading: "material beyond the crest" is a warning, not a refusal; a menu of standard threads | N56, N57 |
| `8a7e92e` | Threading: X2, the crest diameter at the end Z (typing it sets the taper) | N58 |
| `f42f799` | Thread depth for partial-profile inserts (from the tool data); metric table from the Turning panel | N59, N60 |
| `ab3e6a3` | Thread depth: empty = auto, shown in the field with the tool's tip correction; typed = cut as typed | N60 |
| `76e1fc4` | Fix: File > New / Open / Undo crashed with "tool T1 is not defined" when the Tools view had a tool chosen | — |
| `3f7e0d9`, `57b6522`, `ef01747` | Requirement status only ("tried by the user") | — |
| branch `step-import` | STEP part import for a turning contour (turned outline, no CAD library) | C17 |
| branch `toolpath-limits` (backward cuts) | Fix: roughing fed back up a slope towards the front (the user's crowned roller on the big blue lathe, the pawn, the custom bolt): the pass over a bump takes the level of its line, not where its ride begins (`_behind_a_bump`); a dip pass never climbs back towards the front, it rises straight up instead (`dips._forward`, `dips._straight_up`); no plunged pocket layer a pass over the bump takes anyway (`needless_layers`) | — |
| branch `toolpath-limits` (check speed) | Fix: the check follows an arc of 2 mm radius or more as straight chords within 0.001 mm (the user's choice; all checks about 3x faster) (`verify._with_flat_arcs_as_chords`): a long arc in 0.5 mm steps left teeth in the material that every step looked at again (the user's crowned roller: minutes per change, now under a second; same findings on all test projects) | — |
| branch `toolpath-limits` (STEP relations) | STEP and DXF import add horizontal / vertical / tangent / on-axis relations (new `wop/core/sketch/auto_relations.py`, called in `load_profile` and `load_drawing`) | C18 |
| branch `toolpath-limits` (finish only) | Contour block: Roughing tick (default on); off = only the finishing pass, a note when too much stands | B35 |
| branch `toolpath-limits` (step) | Step through: the moves of the block still to come are drawn faintly, the blocks before show only their material (`svg_preview._path_elements`, 2D only; the user found the old picture empty at move 1) | — |
| branch `toolpath-limits` (fix) | Fix: a cut doubled loops of no area with every strip (the user's left-hand VNMG project: minutes and gigabytes while planning); the picture no longer fails on a tool that a newer change removed | — |
| branch `toolpath-limits` | Toolpath limits: Z+ / Z- / X on a turning contour block, X on a facing block, dashed in the picture; fixes at the Z limits; plunge mode; finishing allowance X / Z | B30-B34 |

About 52 files, +2100 / -130 lines, of which more than half are tests, docs and the manual. No new library. None of the
mypyc-compiled modules (`wop/core/compiled.py`) were touched. Only run on Linux (Python 3.13, PySide6, offscreen Qt
tests); the Windows build was not tried.

## Behaviour that changes for existing users

Read these first: they are the changes that make an existing project or post behave differently.

1. **Threading: material beyond the crest no longer refuses the block** (`5a61b19`). Before, a thread over stock that
   was not yet turned or bored to the crest gave no thread at all. Now the thread is written and the block gets a note
   that starts with "WARNING:"; the collision check still reports the tool hitting the stock, and Export still asks.
   The user's reason: "I don't want so many checks to tick before I can use the software"; sometimes the stock is
   already turned on the machine and WOP's raw part does not show it. This is in the spirit of the "written as drawn"
   rule in `CLAUDE.md`.
2. **Metric and Unified thread depths use exact fractions** (`f42f799`): 17H/24 = 0.6134347 P outside and
   5H/8 = 0.5412659 P inside instead of the rounded 0.6134 / 0.5413. The depth changes by about 0.00003 x pitch.
3. **A designation leaves Thread depth empty (auto)** (`ab3e6a3`). Before, picking M24x3 wrote 1.8403 into the depth
   field as a fixed number. Now the field stays empty and shows the depth it will cut as grey text ("auto 1.8403"), so
   the depth follows the tool (see partial-profile inserts below). A designation still writes a number when a fit
   allowance (`THREAD_EXTERNAL_CREST_ALLOWANCE_MM`, `THREAD_INTERNAL_BORE_ALLOWANCE_MM`) makes the depth differ from the
   form's. A typed depth is cut exactly as typed. Projects saved before keep their stored number.
4. **The shipped LinuxCNC post rapids back to the thread start Z after G76** (`6b403c0`). LinuxCNC's G76 ends at the
   end Z of its drive line; WOP planned the next move from the start Z, so an inside thread could rapid through the
   bore wall. This is a fix, but it adds a line to every G76 the post writes.
5. **New fields in saved files** (all have defaults, so older files load unchanged; an older WOP would refuse the new
   files because the codec rejects unknown fields):
   - `FacingBlock.face_stock_mm` (0)
   - `ThreadingBlock.thread_form` (`ISO`), `ThreadingBlock.tip_correction` (true)
   - threading tool `ThreadDefinition.profile` (`FULL`): a tool saved before is a full-profile one, so its depths do not change
6. **New Preferences (New blocks)**: `FACING_TARGET_Z_MM` (-1) and `FACING_FACE_STOCK_MM` (0). The built-in values keep
   the old behaviour.
7. **Labels in the threading form**: "Thread (type, or pick from the list)", new "Thread form", "X2 crest diameter at
   End Z", "Correct the auto depth for a partial-profile tool".

## The features

### 1. Threads as synchronised passes, LinuxCNC G33 (`6b403c0`)

Why: the user wanted to see and control every threading pass in the G-code rather than one G76 line, and G76 cannot cut
a tapered thread along a cone.

- `ThreadOperation.pass_moves` (`wop/core/program_model/operations.py`): the passes move by move exactly as LinuxCNC's
  G76 makes them (depth schedule J x i^(1/R) up to K, the compound-angle shift, retract by K - d, spring passes); a
  tapered run-in or run-out ramps from the crest. The picture and the checks use these moves.
- New `threading_style = synced_passes` in the post definition, a `[thread_move]` concept and a `<lead>` token (G33 K
  measured along the move): `wop/post/concepts.py`, `wop/post/engine.py`, `wop/post/post_definition.py`,
  `wop/post/tokens.py`. The shipped `linuxcnc.post.ini` gets `thread_feed = G33` and the template; **its default stays
  G76**.
- The G76 end-position fix described above.
- `tests/test_thread_passes.py`: pinned to rs274's G76 expansion, plus a live comparison with `rs274` when LinuxCNC is
  installed (144 cases matched move for move).

### 2. Tapered threads and pipe threads (`d411501`)

- `ThreadingBlock.taper_per_100_mm`: a thread along a cone (crest diameter at the start Z, growing per 100 mm towards
  the chuck; negative shrinks, as an inside pipe thread). The band, the material check, the flank run-out and the
  approach follow the cone; `ThreadOperation.crest_slope` makes the passes follow the crest.
- A cycle post (G76, packed Fanuc words) refuses a tapered thread with a message that names `synced_passes`.
- Designations `R 1/2`, `Rc 1/2`, `BSPT 1/2` (ISO 7-1) and `1/2 NPT`, `1/2-14 NPT` (ASME B1.20.1) fill pitch, crest,
  depth, flank angle, taper and the end Z (thread length of the standard). Rows and formulas come from the user's own
  LinuxCNC "Turning panel" (`thread_data.py`), checked there against the standards and gauges; all 68 values match it.
- `tests/test_pipe_threads.py`.

### 3. Facing: stock on the face (`c632103`)

Why: the user zeroes Z on the finished face and saws the bar a few mm long; the raw part should not have to show that
slab.

- `FacingBlock.face_stock_mm`: a slab in front of the material that this block takes off, for this block only. Outside
  in and centre out; a tube gets the slab from its bore out. The slab is not drawn as raw material.
- Preferences `FACING_TARGET_Z_MM`, `FACING_FACE_STOCK_MM` (entries in `wop/core/conventions.py`).
- `tests/test_facing_stock.py`; examples regenerated.

### 4. Contour from points (`ec6b614`)

Why: typing a turned profile as a list of points is quicker than drawing it, and the user's Turning panel already uses
that text format.

- `wop/core/sketch/points_profile.py`: rows (X, Z, a radius `R` or chamfer `C` at the corner) become a sketch of lines
  with the sketch's own fillets and chamfers; a sketch reads back into rows; the text format `X Z [R.. | C..]` (X as a
  diameter).
- `AppModel.contour_from_rows` / `contour_rows` (with undo); `wop/ui/qt/points_dialog.py` (table, live picture, Paste
  text...); Add block > "Contour from points..." and "Edit as points..." on the contour panel.
- `tests/test_points_profile.py` (core, model, the real dialog offscreen).

### 5. Crest check as a warning; menu of standard threads (`5a61b19`)

- The warning: see "Behaviour that changes" 1. `wop/core/blocks/threading.py`.
- A ▼ arrow inside the Thread text field opens a menu of standard threads by family (metric coarse, metric fine by
  diameter, Tr, UNC, UNF, BSPT with R outside / Rc inside, NPT); typing stays free. `standard_designations` in
  `wop/core/thread_designation.py`.
- `tests/test_thread_menu.py`.

### 6. X2, the crest diameter at the end Z (`8a7e92e`)

Why: on a tapered thread the user wants to see, and be able to type, the diameter at the back.

- `ThreadingBlock.end_crest_radius_mm` (a property, not stored) and `with_end_crest_radius_mm` (sets
  `taper_per_100_mm`). The taper stays the stored value, so the file format does not change.
- `tests/test_thread_x2.py`.

### 7. Thread depth for partial-profile inserts (`f42f799`, `ab3e6a3`)

Why: a partial-profile insert (one insert for many pitches, with its own tip radius) must go deeper than the standard
depth on coarse pitches; cutting the full-form depth with a 0.2 mm tip leaves an M24 x 3 thread 0.47 mm oversize on the
diameter. The user's Turning panel already does this and it was checked on the machine with gauges.

- `wop/core/thread_form.py` (new): `ThreadForm` (ISO / Unified 60, Whitworth / BSP 55, NPT 60 with flat root,
  trapezoidal), `full_profile_depth`, `tip_correction`. A tip radius r sits back from the tool's own virtual apex by
  r x k, k = 1 / sin(angle / 2) - 1, so the depth is h_std x P + (r_std x P - r) x k (zero for a full-profile insert;
  negative for a blunter tip on a fine pitch). NPT's 0.033 P truncation enters as the setback of a radius with the
  same effect. Trapezoidal threads get no correction. Identical to the panel's `thread_depth` in 576 cases
  (4 forms x 12 pitches x 2 sides x 6 radii).
- Threading tool: `ThreadDefinition.profile` (Full / Partial) above "Tip radius" (`wop/core/tool_types/thread.py`);
  partial uses `nose_radius_mm`. Decision of the user: from the tool data, not a box in the block, so the insert is
  described once and the picture, the checks and the depth use the same radius.
- Threading block: `thread_form` (set by a designation, editable for a custom thread) and `tip_correction` (ticked).
  Empty depth = auto and shown in the field; typed = cut as typed (the panel's behaviour).
- Metric coarse M1 to M100 and the ISO 261 fine pitches (50 sizes, 127 fine pitches) come from the panel's table; the
  menu groups the fine pitches by diameter. `METRIC_THREADS` in `wop/core/constants.py`; `METRIC_COARSE_PITCHES` is
  derived from it.
- `tests/test_thread_tip.py` (reference depths printed by the panel).

### 8. Fix: File > New with a tool chosen in the Tools view (`76e1fc4`)

`AppModel.selected_tool` was kept when the project was replaced (File > New, Open, Undo of adding the tool); the tool
form then asked for a tool that no longer existed and the window crashed with `BlockError: tool T1 is not defined`.
`_drop_missing_tool` (`wop/ui/model/tools.py`) clears it after every change, as `_drop_missing_contour` does for
contours. Tests in `tests/test_app_model.py` (`ChosenToolGoneTests`).

### 9. STEP part import (branch `step-import`, on top of `bigblue-changes`)

The sketch editor's Import button of a turning contour also takes a STEP part (`.step`, `.stp`); tools and
workholding still take DXF only. **No library**: the user asked to keep WOP free of extra dependencies (OpenCASCADE
via `cadquery-ocp` is a 68 MB wheel and was rejected). STEP is text, and a turned part is made of analytic faces
(cylinder, cone, torus, sphere, plane), so a small reader is enough:

- `wop/adapters/step_part21.py`: the ISO 10303-21 text into records (simple and complex records, strings, comments).
- `wop/adapters/step_files.py`: MANIFOLD_SOLID_BREP -> CLOSED_SHELL -> ADVANCED_FACE; surfaces with their axes; edges
  (line, circle, ellipse, B-spline, rational B-spline) sampled; lengths in mm from the solid's
  GLOBAL_UNIT_ASSIGNED_CONTEXT (mm, m, inch).
- `wop/core/bspline.py`: de Boor (and NURBS) evaluation, also meant for DXF splines (C4).
- `wop/core/turned_profile.py`: axis = the line most round faces share; every round face is an exact line or arc in
  (z, radius); the outside is the **turned envelope** (largest radius per z): faces that are not round about the axis
  count only where they stick out, so a hex comes in at its across-corners size and flats, keyways, cross holes and
  gear teeth drop out; a bore is the smallest radius of the faces whose outward normal points to the axis. The user
  picks the front end (Z0) and the outside or a bore.
- `dxf_contour.contour_from_chain`: the pieces are already one exact chain, so they are not joined by distance
  (`DXF_JOIN_TOLERANCE_MM` = 0.1 merged a real 0.057 mm land of one part).
- Tried offline on 8 of the user's parts (seven from SolidWorks 2014, `CONFIG_CONTROL_DESIGN`; one from Autodesk, AP214):
  flanges with bolt holes, a stepped bore, a pipe fitting with R150 and R8 arcs, shafts with fillets and keyways, a
  split gear, a bolt with flats, a BSPT plug. All import as valid contours with either end as front. Parsing takes
  0.01-0.4 s; the largest file (465 kB) takes about 1 s in all.
- Open: a spline on a revolved face comes in as short lines (thinned within 0.002 mm); fitting arcs to it is C4.
  Assemblies with placed parts (transforms) are not read: export one part.
- New constants `STEP_*` at the end of `constants.py`, below `NOT_EDITABLE_BELOW` (not in Preferences).
- Tests: `tests/test_step_import.py` (a hand-written `tests/data/step/cylinder_20x30.step`; the user's parts are not
  in the repository).

### 10. Toolpath limits (branch `toolpath-limits`, on top of `step-import`)

The user comes from ECAM, where every turning operation has "toolpath limits" (Z+, Z-, X+, X-). He uses them "a lot":
to share one contour between tools (a back-turning tool for the last part), to keep away from the chuck, to stop facing
before the centre, and to rough the front of a long part first while the bar is stiff. The contour is never changed.

- `ContourTurningBlock`: `z_plus_limit_mm`, `z_minus_limit_mm`, `x_limit_radius_mm`; `FacingBlock`: `x_limit_radius_mm`.
  All default to None (no limit), so old projects plan as before. Plain Z values from Z0 and an X radius (shown as a
  diameter); minus is towards the chuck. The user dropped ECAM's other references ("Model top", "Stock top"...): "just
  keep distance from Z0".
- Only the X limit on the part side (outside: the smallest diameter, inside: the largest). On the free side it would
  make the tool run through the stock to get in; left out.
- `wop/core/blocks/toolpath_limits.py`: the contour clipped to the limits (`limited_path`: beyond the X limit straight
  along it) and the box of the limits. The contour block plans the wanted lines from the material clipped to the box;
  the cuts, the ways and the check see all the material; `protected` stays the part as drawn, so the back of the insert
  may touch stock beyond a Z+ limit.
- The finishing pass obeys the limits (user: "Z limit retracts, X limit carries on straight"): at a Z- limit it leaves
  at 45 degrees by the clearance instead of cutting up the limit; over a neck below the X limit it runs along the limit.
- Facing with an X limit: no overtravel (greyed), its face contour gets a wall at the limit so no line runs on.
- A note on a limited block names the limits; `Block.limit_lines` + `render_svg(limits=...)` draw them as thin dashed
  lines while the block is chosen (user: only then). The 3D view does not show them.
- The "written as drawn" line in `CLAUDE.md` now says typed limits are the only thing that shortens a block.
- The example projects gained the three empty fields (`make_block_examples.py`, `make_example_project.py`,
  `make_compensation_test.py`, run with an empty settings folder so the user's own presets stay out).
- Tests: `tests/test_toolpath_limits.py`.
- Fix after the user tried it (2026-11-23, his bolt with Z- -90 and a TNMG R0.8): the roughing left the finishing
  allowance standing on the Z- limit as if it were a shoulder of the part, and the 45-degree way away was added to the
  contour before the nose compensation, so the tool dipped 0.37 mm into the finished diameter and then fed straight up
  through that wall. Now the roughing path runs on past the limit by the allowance (`_roughing_inputs`), the low ends
  of the lines are judged in the material as it stands beyond the limit (`WantedJob.low_stock`, `make_lines(low_stock=)`)
  so the tool rides up the limit like a shoulder, and the way away is a line added to the tool path after the
  compensation (`FinishingJob.exit`, and `entry` for a left-hand tool planned mirrored). The finishing pass finishes the
  diameter right up to the limit (the user: "finishing pass could go right up to the z- limit"). Regression project:
  `tests/data/projects/bolt_z_minus_limit.wop.json` (the contour of his STEP part, not the file).
- Second fix the same day: the finishing pass ended with the nose centre on the limit, so the nose cut 0.8 mm past it
  (user: "i need that finishing pass to stop at the limit or what use is a limit"). Now the tool path is cut back where
  the outline of the tool reaches the limit (`wop/core/analytic/path_trim.py`, `FinishingJob.z_floor` / `z_ceiling`); a
  compensated pass gets the contour point the nose touches there. The corner at the limit keeps the nose radius.
- Z+ limit (user: "the idea is that the stock outside the limits is not cut"): the stock in front of the limit joins the
  region no tool may enter in the roughing (`RoughingJob.stays`) and `protected` (the checker reports a touch); lines with
  no way in are left out with the usual note. The finishing pass starts where the nose reaches the limit.

### 11. Plunge mode of the finishing pass (branch `toolpath-limits`)

ECAM's "Plunge mode" (Free / Tool Geometry / Don't plunge / Same as roughing), for the user's case of a TNMG in a 91-degree
holder going down a 45-degree back chamfer and down a face to the centre with the bar behind it.
- `ContourTurningBlock.plunge_mode` (`PlungeMode` in `wop/core/analytic/finish_modes.py`): FREE (default, as before),
  TOOL_SHAPE, NO_PLUNGE. "Same as roughing" is not needed: WOP's roughing always keeps the tool shape. Roughing unchanged.
- Tool shape: the region of reference points where the planning tool (back edge turned by the back clearance) overlaps
  what stays after the block (part, stock beyond the limits, bar behind the contour) is made exactly with the region
  code: what stays grown by the nose radius, swept along the edges of the tool outline shrunk by the nose radius and
  turned a half turn (Minkowski sum). The free-mode tool path runs along its border where it dives in.
  `Region.offset(-r)` fails when an arc of radius r would shrink to a point, so the outline is shrunk by r - 0.001 mm.
- Don't plunge: the tool path held at the greatest height so far.
- Both refuse cutter compensation; what they leave is shown and noted. The plain turning block keeps free.
- Don't plunge applies to the roughing too (the user: "it would be nice to apply it to roughing also"): the roughing
  contour is the same held-height contour (`_roughing_inputs`).

### 12. Finishing allowance X / Z (branch `toolpath-limits`)

From ECAM ("Finishing Allowance X" and "Z"). Contour block only (the user: "just contour cycle for now"; grooving undecided).
- `finish_allowance_mm` stays the X allowance (old projects unchanged), kept as a radius but typed as a diameter in
  diameter mode (the user: "i want X in dia") through a new generic form hook `form_radius_fields`. New
  `finish_allowance_z_mm` (None: as X); its empty field shows "same as X: .. per side" (new hook `form_placeholders`).
- `wop/core/analytic/allowance_xz.py`: part + disc(min) + line along the axis of the larger (Minkowski sum). The roughing
  contour is pushed along that axis by the difference; the planner offsets by the smaller value as before, so equal
  values give exactly the old plan. Slopes get a value between the two. A face down to the centre and the run-on wall
  back up it are left unpushed (they would cross).
- Tests: `tests/test_allowance_xz.py`. Not tried by the user yet.
- Tests: `tests/test_plunge_mode.py` (the user's bolt). Not tried by the user yet.

### 13. Fix: no backward cuts in the roughing (branch `toolpath-limits`)

The user ran the crowned roller (one arc of 15 m radius, Ø34 at the ends, Ø36 in the middle, from Ø37) on the big blue lathe:
"the tool paths are a mess. i even found some backwards cutting". Two causes, both in the analytic roughing:

- **The pass over a bump** (`roughing_cuts._behind_a_bump`) took its level from where the ride up the contour begins. On a nearly level
  contour the end of the line is moved to the start of the arc, a few thousandths lower (0.004 mm here), so the line behind the crown at the
  same radius counted as higher and was not joined. The pass stopped on the crown and the far side was left to the dip passes. Now the
  caller passes the line's radius.
- **A dip pass** (`dips.follow_dip`) goes down the contour and up again. Where no wall stands behind the hollow (the contour falls to its
  end, or to a spot lower than the floor) the only way up was back up the slope it came down: a feed in +Z with the back of the tool, up
  to 245 mm long on the roller. The way up now ends where it would turn back towards the front (`_forward`); the tool rises straight up
  instead (`_straight_up`, only where the tool may stand), as a line rides up the wall at its end.

On all test projects and examples only three plans change: the roller (no backward cut, 10 moves fewer), the pawn example (one 3 mm
back-climb becomes a straight rise) and the user's bolt (a dip that took 0.045 mm² by climbing back is dropped; the finishing pass takes it).
Collision findings are the same everywhere. Test: `tests/test_no_backward_roughing.py`.

Then the user: "that extra harmless pass seems a bit silly". The far half of the roller is a pocket (the crown on one side, the bar beyond
the end on the other), and a pocket is cut in layers of the plunge depth of cut (0.5): a plunged pass of 0.275 at Ø36.45 came first, before
the pass over the crown took the rest. Now, when a pass over a bump reaches a pocket line, the layers above it are left out if the material
above that line is no deeper than the depth of cut and they lie between the top of the bump and the end of the line
(`_Roughing.needless_layers`; the block hands its depth of cut to `RoughingJob.depth_of_cut`): the roughing is planned once more without them,
and that plan is kept only when the same passes come over the bump again. Only the roller changes among the test projects (56 -> 38 operations).

## New generic form hooks

Three small additions to the form framework (`wop/ui/block_forms.py`, `wop/ui/qt/form_panel.py`); any block or form can
use them. They are listed in `CLAUDE.md` with the other hooks.

| Hook on the object | FieldSpec field | What it does |
|---|---|---|
| `field_suggestions()` -> {name: entries} | `suggestions` | A ▼ menu inside a text field; an entry is a value or `(heading, entries)` for a submenu. Typing stays free. |
| `form_computed_fields()` -> {name: label} | `computed` | A property shown as a float field; typing it calls `with_<name>(value)` (`set_value` does this). Never dimmed, no "Reset to default"; typing it marks the fields it changed as touched. |
| `form_tool_notes(tool)`, `form_tool_placeholders(tool)` | `placeholder` | Notes and the grey text of an empty optional field that depend on the object's chosen tool; `FormContext.tool_objects` carries the program's tools. |

The window also shows the form again after an edit of a block that has computed fields, so the computed field and its
sources follow each other (`wop/ui/qt/window_parts/form.py`).

## Values that are guessed (GUESS)

- `TRAPEZOIDAL_THREADS` (the Tr list in the menu): the ISO 2904 preferred pitch per diameter as remembered, not checked
  against the standard. Marked GUESS in `wop/core/constants.py` and the design notes.

All other new tables (BSPT, NPT, metric ISO 261, the thread forms) come from the user's Turning panel, where they were
checked against the standards and on the machine.

## Not part of this branch

The user's own settings live outside the repository and are not committed: the "Big Blue lathe" machine, a custom
post `big_blue.post.ini` (Fanuc-style `T0303 M6`, no `G43 H` because the machine's tool-change remap applies the
offsets, `threading_style = synced_passes`, footer G97/M9/M30), and two presets in `conventions.json`
(`FACING_TARGET_Z_MM` 0, `FACING_FACE_STOCK_MM` 2).

## Tested

- The full suite (`tools/run_tests.py`, about 2390 tests) before every commit, with an empty `XDG_CONFIG_HOME` so the
  user's presets do not change the example tests. One Qt hover test (`tests/test_style_pictures.py`) failed once under
  load and passed on every rerun; it was not touched.
- The example projects were regenerated with `tools/make_block_examples.py` where a model change needed it.
- On the machine, by the user: the tapered G33 passes look right in AXIS; X2 shows and sets the taper; the menu of
  threads; the partial-profile depth (M24x3, tip R0.4: auto 1.8733); stock on the face; contour from points with
  Paste text; File > New after the fix. Nothing has been cut in metal yet.
- Latency (LinuxCNC servo thread 1 ms, the sim, 60 s each): with WOP planning flat out on the three housekeeping cores,
  servo period jitter 7.7 µs (99 %) / 105 µs worst, against 6.4 / 85 µs with WOP idle; the realtime thread is on an
  isolated core, and WOP never runs there.

## Merging

- The commits are in feature order and each one passes the suite on its own. `5a61b19` to `ab3e6a3` build on each other
  (all threading); `c632103` and `ec6b614` stand alone.
- Likely conflict spots if the upstream code has moved on: `wop/core/blocks/threading.py`, `wop/core/constants.py`
  (new constants were put in the thread section, below `NOT_EDITABLE_BELOW`), `wop/ui/block_forms.py`,
  `docs/wop_02_requirements.md` (new IDs C16, N54 to N60, O35, O36, X16; if they clash with IDs used upstream, renumber
  them here, never upstream).
- After a merge: run `tools/make_*.py` for the examples, then the suite.
