"""Synthetic pixel-metric math tests, no model inference or dataset."""
from pathlib import Path
import importlib.util
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location("pixel_eval_256",Path(__file__).resolve().parents[1]/"pixel_eval_256.py")
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
pixel=importlib.util.module_from_spec(spec);spec.loader.exec_module(pixel)

class PixelMetricTests(unittest.TestCase):
    def fixtures(self,defect_score=.9):
        score=np.linspace(.01,.5,256*256,dtype=np.float32).reshape((256,256))
        mask=np.zeros((256,256),dtype=bool)
        mask[75:79,88:92]=True
        anomaly=score.copy()
        anomaly[mask]=defect_score
        return [score,anomaly],[np.zeros_like(mask),mask]

    def test_perfect_anomaly_segmentation(self):
        scores,masks=self.fixtures()
        m=pixel.pixel_metrics(scores,masks,max_fpr=.3)
        self.assertAlmostEqual(m["pixel_auroc"],1.,places=6)
        self.assertAlmostEqual(m["pixel_average_precision"],1.,places=6)
        self.assertGreater(m["aupro_approx_256"],.99)
        self.assertEqual(m["connected_regions"],1)

    def test_reverse_anomaly_ranking(self):
        scores,masks=self.fixtures(0.)
        m=pixel.pixel_metrics(scores,masks,max_fpr=.3)
        self.assertAlmostEqual(m["pixel_auroc"],0.,places=6)
        self.assertLess(m["aupro_approx_256"],.01)

    def test_requires_both_classes(self):
        score=np.zeros((256,256),dtype="float32")
        mask=np.zeros((256,256),dtype=bool)
        with self.assertRaises(ValueError):
            pixel.pixel_metrics([score],[mask])
        with self.assertRaises(ValueError):
            pixel.pixel_metrics([score],[~mask])

    def test_reject_map_nan(self):
        scores,masks=self.fixtures()
        scores[0][0,0]=float("nan")
        with self.assertRaises(ValueError):
            pixel.pixel_metrics(scores,masks)

    def test_constant_normal_scores_no_fake_aupro(self):
        normal=np.full((256,256),.2,dtype="float32")
        anomaly=normal.copy()
        mask=np.zeros((256,256),dtype=bool)
        mask[20:40,50:60]=True
        anomaly[mask]=.9
        m=pixel.pixel_metrics([normal,anomaly],[np.zeros_like(mask),mask])
        self.assertAlmostEqual(m["pixel_auroc"],1.0)
        self.assertIsNone(m["aupro_approx_256"])
        self.assertEqual(m["aupro_status"],"fpr_coverage_insufficient")

if __name__=="__main__":unittest.main()
