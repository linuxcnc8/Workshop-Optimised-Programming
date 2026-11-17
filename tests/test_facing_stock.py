"""The stock on the face of a facing block (`face_stock_mm`): material in front of the face that the block takes off, so the finished face
can be Z0 with a few mm in front of it that the raw part does not show."""

from __future__ import annotations

import unittest

from tests.helpers import simple_tool
from wop.core.blocks.base import BlockContext, BlockError, Safety
from wop.core.blocks.facing import FacingBlock, FacingDirection
from wop.core.program_model.operations import LinearMove, SpindleMode, SpindleSetting
from wop.core.program_model.raw_part import RawPart
from wop.core.program_model.stock import stock_region

SPINDLE = SpindleSetting(SpindleMode.CONSTANT_RPM, 1000)


def facing(**overrides) -> FacingBlock:
    values = dict(block_id="f", tool_number=1, spindle=SPINDLE, target_z_mm=0, feed_mm_per_rev=0.2, depth_of_cut_mm=1, face_stock_mm=2)
    values.update(overrides)
    return FacingBlock(**values)


def context(raw: RawPart | None = None) -> BlockContext:
    raw = raw or RawPart("steel", 30, 60)  # its front face is Z0
    return BlockContext(raw, simple_tool(1), stock_region(raw), Safety(25, 10, 1))


def pass_levels(result) -> list[float]:
    """The Z of every feed across the face: a feed that keeps its Z and travels more than a millimetre in X."""
    levels, here = [], None
    for operation in result.operations:
        end = getattr(operation, "end", None)
        if isinstance(operation, LinearMove) and here is not None and abs(end.z - here.z) < 1e-9 and abs(end.x - here.x) > 1:
            levels.append(round(end.z, 6))
        here = end if end is not None else here
    return levels


class FaceStockTests(unittest.TestCase):
    def test_the_stock_in_front_of_z0_is_faced_off_down_to_the_target(self):
        result = facing().generate(context())
        self.assertEqual(pass_levels(result), [1, 0])
        self.assertEqual(result.messages, ())

    def test_without_stock_a_target_on_the_face_has_nothing_to_cut(self):
        result = facing(face_stock_mm=0).generate(context())
        self.assertEqual(pass_levels(result), [])
        self.assertIn("nothing to cut", result.messages[0])

    def test_centre_out_takes_the_stock_off_too(self):
        result = facing(direction=FacingDirection.CENTER_OUT).generate(context())
        self.assertEqual(pass_levels(result), [1, 0])

    def test_the_removed_material_leaves_the_part_at_the_target(self):
        result = facing().generate(context())
        self.assertAlmostEqual(result.removed.bounds.min_z, 0, places=5)
        self.assertAlmostEqual(result.removed.bounds.max_z, 2, places=5)

    def test_a_tube_gets_its_stock_only_between_the_bore_and_the_outside(self):
        result = facing().generate(context(RawPart("steel", 30, 60, inner_diameter_mm=10)))
        self.assertAlmostEqual(result.removed.bounds.min_x, 5)

    def test_negative_stock_is_refused(self):
        with self.assertRaises(BlockError):
            facing(face_stock_mm=-1)

    def test_a_new_block_takes_the_preferences(self):
        from wop.core import constants

        block = FacingBlock.example("f", 1, SPINDLE)
        self.assertEqual((block.target_z_mm, block.face_stock_mm), (constants.FACING_TARGET_Z_MM, constants.FACING_FACE_STOCK_MM))


if __name__ == "__main__":
    unittest.main()
