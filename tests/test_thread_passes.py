"""The passes of a thread move by move (`ThreadOperation.pass_moves`) and the threading style `synced_passes` (LinuxCNC G33).

The numbers are those of LinuxCNC's own G76, expanded by rs274 (LinuxCNC 2.10): a straight thread written as G33 passes must
make exactly the moves of the cycle. `G76AgainstRs274Tests` repeats the comparison with the real interpreter when it is there.
"""

from __future__ import annotations

import itertools
import math
import re
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.post_helpers import shipped_post
from wop.core.geometry import Point
from wop.core.program_model.operations import LinearMove, Rapid, ThreadFeed, ThreadOperation, ThreadTaper

# P1.5 Z-15 I-2 J0.6 K1.84 R2 Q29.5 H1 from X32 Z4.5 (diameter mode): the example of the threading block
OUTSIDE = ThreadOperation(start_x=16, start_z=4.5, end_z=-15, pitch_mm=1.5, peak_offset_mm=-1, first_cut_mm=0.3, depth_mm=0.92,
                          degression=2, compound_angle_deg=29.5, spring_passes=1)
INSIDE = replace(OUTSIDE, start_x=10, peak_offset_mm=1)  # from X20, I2: the crest at radius 11


def _rounded(point: Point) -> tuple[float, float]:
    return round(point.x, 4), round(point.z, 4)


class PassMovesTests(unittest.TestCase):
    def test_the_first_pass_is_that_of_linuxcnc_g76(self):
        moves = OUTSIDE.pass_moves()
        self.assertEqual([_rounded(move.end) for move in moves[:4]], [(16.62, 4.3303), (14.7, 4.3303), (14.7, -14.6492), (16.62, -14.6492)])
        self.assertIsInstance(moves[2], ThreadFeed)
        self.assertEqual(moves[2].lead_mm, 1.5)

    def test_the_second_pass_is_deeper_by_the_degression_and_shifted_by_the_compound_angle(self):
        moves = OUTSIDE.pass_moves()
        self.assertEqual([_rounded(move.end) for move in moves[4:8]], [(16.4957, 4.26), (14.5757, 4.26), (14.5757, -14.7195), (16.4957, -14.7195)])

    def test_the_full_depth_ends_on_the_end_z_and_the_tool_goes_back_to_the_start(self):
        moves = OUTSIDE.pass_moves()
        self.assertEqual([_rounded(move.end) for move in moves[-4:-1]], [(14.08, 3.9795), (14.08, -15.0), (16.0, -15.0)])  # the spring pass
        self.assertEqual(_rounded(moves[-2].end), (16.0, -15.0))  # at full depth it retracts to the start X at the end Z
        self.assertEqual(_rounded(moves[-1].end), (16.0, 4.5))  # then back to the start point, where the block goes on from
        self.assertEqual(OUTSIDE.end, Point(16, 4.5))

    def test_an_inside_thread_cuts_outwards_and_retracts_towards_the_axis(self):
        moves = INSIDE.pass_moves()
        self.assertEqual([_rounded(move.end) for move in moves[:4]], [(9.38, 4.3303), (11.3, 4.3303), (11.3, -14.6492), (9.38, -14.6492)])
        self.assertEqual(_rounded(moves[-1].end), (10.0, 4.5))

    def test_spring_passes_repeat_the_full_depth(self):
        cuts = [move for move in OUTSIDE.pass_moves() if isinstance(move, ThreadFeed)]
        self.assertEqual(len(cuts), len(OUTSIDE.pass_depths()))
        self.assertEqual(_rounded(cuts[-1].end), _rounded(cuts[-2].end))

    def test_a_tapered_entry_and_exit_ramp_from_the_crest_by_the_depth_of_the_pass(self):
        tapered = replace(OUTSIDE, taper=ThreadTaper.BOTH, taper_distance_mm=3, spring_passes=0)
        moves = tapered.pass_moves()
        first = moves[:6]  # retract, to the crest, ramp in, along, ramp out, retract
        self.assertEqual([_rounded(move.end) for move in first],
                         [(16.62, 4.3303), (15.0, 4.3303), (14.7, 1.3303), (14.7, -11.6492), (15.0, -14.6492), (16.62, -14.6492)])
        self.assertEqual([type(move) for move in first], [Rapid, Rapid, ThreadFeed, ThreadFeed, ThreadFeed, Rapid])
        self.assertAlmostEqual(first[2].lead_mm, 1.5 * math.hypot(3, 0.3) / 3)  # the pitch along the ramp keeps 1.5 along Z
        self.assertEqual(first[3].lead_mm, 1.5)

    def test_the_explicit_moves_are_the_passes_with_feed_moves_at_the_pitch(self):
        explicit = OUTSIDE.explicit_moves()
        self.assertEqual([move.end for move in explicit], [move.end for move in OUTSIDE.pass_moves()])
        self.assertTrue(all(move.feed_mm_per_rev == 1.5 for move in explicit if isinstance(move, LinearMove)))


class SyncedPassesPostTests(unittest.TestCase):
    def _post(self, style: str):
        engine = shipped_post("linuxcnc")
        definition = replace(engine.definition, settings=replace(engine.definition.settings, threading_style=style))
        return type(engine)(definition)

    def test_synced_passes_write_g33_with_the_lead(self):
        lines = self._post("synced_passes").thread(OUTSIDE)
        self.assertEqual(lines[0], "(thread: 1.5 pitch, G33 passes)")
        self.assertEqual(lines[1:5], ["G0 X16.62 Z4.33", "X14.7", "G33 X14.7 Z-14.649 K1.5", "G0 X16.62"])  # radius: no G7 set here
        self.assertEqual(sum(line.startswith("G33") for line in lines), len(OUTSIDE.pass_depths()))
        self.assertEqual(lines[-1], "Z4.5")  # back along the start X to the start point

    def test_the_g76_cycle_goes_back_along_the_drive_line_to_the_start_z(self):
        lines = self._post("cycle").thread(OUTSIDE)
        self.assertTrue(lines[0].startswith("G76 P1.5 Z-15"))
        self.assertEqual(lines[1], "G0 Z4.5")  # LinuxCNC's G76 ends at the end Z; WOP plans the next move from the start point


MOVE = re.compile(r"(STRAIGHT_TRAVERSE|STRAIGHT_FEED)\(([-\d.]+), [-\d.]+, ([-\d.]+)")
RS274_INI = "[RS274NGC]\nPARAMETER_FILE = sim.var\n[EMCIO]\nTOOL_TABLE = sim.tbl\n[TRAJ]\nLINEAR_UNITS = mm\nANGULAR_UNITS = degree\n"


@unittest.skipIf(shutil.which("rs274") is None, "LinuxCNC's rs274 is not installed")
class G76AgainstRs274Tests(unittest.TestCase):
    """The G33 passes and LinuxCNC's own G76, both expanded by rs274, make the same moves (to 0.001 mm)."""

    def _expand(self, folder: Path, body: str) -> list[tuple[str, float, float]]:
        program = folder / "p.ngc"
        program.write_text("G7 G18 G21 G90 G95\nG97 S300 M3\n" + body + "M5\nM30\n")
        output = subprocess.run(["rs274", "-i", "sim.ini", "-t", "sim.tbl", "-g", str(program)], cwd=folder, capture_output=True, text=True,
                                timeout=60).stdout
        moves = [(kind, round(float(x), 3), round(float(z), 3)) for kind, x, z in MOVE.findall(output)]
        return [move for index, move in enumerate(moves) if index == 0 or move[1:] != moves[index - 1][1:]]

    def test_straight_threads_outside_and_inside(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            (folder / "sim.ini").write_text(RS274_INI)
            (folder / "sim.tbl").write_text("T1 P1 ;\n")
            (folder / "sim.var").write_text("")
            for outside, angle, degression, springs in itertools.product((True, False), (0, 29.5), (1, 2), (0, 2)):
                base = OUTSIDE if outside else INSIDE
                operation = replace(base, compound_angle_deg=angle, degression=degression, spring_passes=springs)
                start = f"G0 X{2 * operation.start_x:.6f} Z{operation.start_z}\n"
                cycle = (f"G76 P{operation.pitch_mm} Z{operation.end_z} I{2 * operation.peak_offset_mm:.6f} J{2 * operation.first_cut_mm:.6f} "
                         f"K{2 * operation.depth_mm:.6f} R{degression} Q{angle} H{springs}\n")
                passes = "".join(
                    f"G0 X{2 * move.end.x:.6f} Z{move.end.z:.6f}\n" if isinstance(move, Rapid)
                    else f"G33 X{2 * move.end.x:.6f} Z{move.end.z:.6f} K{move.lead_mm:.6f}\n"
                    for move in operation.pass_moves()[:-1]  # without the way back to the start point (G76 ends at the end Z)
                )
                with self.subTest(outside=outside, angle=angle, degression=degression, springs=springs):
                    self.assertEqual(self._expand(folder, start + passes), self._expand(folder, start + cycle))


if __name__ == "__main__":
    unittest.main()
