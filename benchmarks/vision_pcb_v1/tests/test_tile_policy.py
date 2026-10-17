"""CPU/network-free tiling contract tests."""
import importlib.util
from pathlib import Path
import unittest

modpath=Path(__file__).resolve().parents[1]/"tile_policy.py"
spec=importlib.util.spec_from_file_location("vision_tile_policy",modpath)
tile=importlib.util.module_from_spec(spec)
spec.loader.exec_module(tile)

class TilingTests(unittest.TestCase):
    def test_small_image_one_tile(self):
        self.assertEqual(tile.tile_rectangles(320,240),( [(0,0,320,240)] ))
    def test_right_bottom_covered(self):
        for width,height in [(1404,1070),(1562,960),(1358,1104),(1024,512),(700,700)]:
            rects=tile.tile_rectangles(width,height,640,.25)
            self.assertTrue(any(r[2]==width and r[3]==height for r in rects))
            self.assertEqual(rects[0][0:2],(0,0))
            for y in range(0,height,20):
                for x in range(0,width,20):
                    self.assertTrue(any(a<=x<c and b<=y<d for a,b,c,d in rects),(width,height,x,y))
    def test_determinism(self):
        self.assertEqual(tile.tile_rectangles(1404,1070),tile.tile_rectangles(1404,1070))
    def test_invalid_geometry(self):
        for args in [(0,300),(-1,250),(100,100,100,.75)]:
            with self.assertRaises(ValueError):tile.tile_rectangles(*args)
    def test_aggregation_and_validation(self):
        self.assertEqual(tile.aggregate_max(.2,[.1,.3]),.3)
        self.assertEqual(tile.aggregate_max(.9,[]),.9)
        for bad in [[-0.2],[float("nan")],[1.1]]:
            with self.assertRaises(ValueError):tile.aggregate_max(.3,bad)

if __name__=='__main__':
    unittest.main()
