"""A cut on material with loops of no area (a line out and back) drops them after every strip: each split doubled them, and in the user's
bolt project (2026-11-23: a left-hand VNMG with an X limit of 17) 31 of them grew to four million pieces, so the planning took minutes and
gigabytes in the window."""

import time
import unittest
from pathlib import Path

from wop.adapters.project_files import load_project
from wop.core.program_model.program import plan_program

PROJECT = Path(__file__).parent / "data" / "projects" / "bolt_left_hand_x_limit.wop.json"


class NeedleTests(unittest.TestCase):
    def test_the_users_project_plans_in_seconds(self):
        program = load_project(PROJECT).program
        start = time.perf_counter()
        plan_program(program)
        self.assertLess(time.perf_counter() - start, 30)


if __name__ == "__main__":
    unittest.main()
