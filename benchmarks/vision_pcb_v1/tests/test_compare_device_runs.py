"""CPU/GPU comparison contract tests; synthetic data, no GPU required."""
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/"compare_device_runs.py"
spec=importlib.util.spec_from_file_location("compare_device_runs",path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def report(device):
    return {
        "device":device,"model":"winclip","checkpoint_sha256":"a"*64,
        "backbone":"ViT-B-16-plus-240","pretrained":"laion400m_e31",
        "prompt":"printed circuit board",
        "preprocessing":"model.transform CPU, normalized 240x240",
        "n_images":4,"wall_seconds":12.3 if device=="cpu" else 4.1,
        "records":[{"sample_id":f"s{x}","score":.1+x*.2,
                    "forward_seconds":2.4 if device=="cpu" else .7}
                    for x in range(4)]
    }

class CompareTests(unittest.TestCase):
    def test_equivalence(self):
        data=mod.run(report("cpu"),report("cuda"))
        self.assertTrue(data["score_delta_pass_1e4"])
        self.assertAlmostEqual(data["median_speedup"],2.4/.7)
        self.assertEqual(data["samples"],4)
    def test_sample_mismatch(self):
        cpu,gpu=report("cpu"),report("cuda")
        gpu["records"][0]["sample_id"]="wrong"
        with self.assertRaises(ValueError):
            mod.run(cpu,gpu)
    def test_version_mismatch(self):
        cpu,gpu=report("cpu"),report("cuda")
        gpu["checkpoint_sha256"]="b"*64
        with self.assertRaises(ValueError):
            mod.run(cpu,gpu)
    def test_score_divergence(self):
        cpu,gpu=report("cpu"),report("cuda")
        gpu["records"][2]["score"]+=.01
        result=mod.run(cpu,gpu)
        self.assertFalse(result["score_delta_pass_1e4"])

if __name__=="__main__":unittest.main()
