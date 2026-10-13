"""Synthetic ingestion tests: no downloaded VisA data or GPU required."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image

SRC = Path(__file__).resolve().parents[1] / "prepare_visa.py"
spec = importlib.util.spec_from_file_location("prepare_visa", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class VisaImportTests(unittest.TestCase):
    def build_dataset(self, root):
        for family in mod.CATEGORIES:
            base = root / family / "Data"
            for name in ("Images/Normal", "Images/Anomaly", "Masks/Anomaly"):
                (base / name).mkdir(parents=True)
            seed = mod.CATEGORIES.index(family)
            Image.new("RGB", (12, 10), (40 + 40 * seed, 40, 40)).save(base / "Images/Normal/0000.JPG")
            Image.new("RGB", (12, 10), (20 + 50 * seed, 100, 200)).save(base / "Images/Anomaly/000.JPG")
            mask = Image.new("L", (12, 10), 0)
            for yy in (3, 4):
                for xx in (5, 6):
                    mask.putpixel((xx, yy), 1)
            mask.save(base / "Masks/Anomaly/000.png")
            csv_file = root / family / "image_anno.csv"
            csv_file.write_text(
                "image,label,mask\n"
                f"{family}/Data/Images/Normal/0000.JPG,normal,\n"
                f"{family}/Data/Images/Anomaly/000.JPG,scratch,{family}/Data/Masks/Anomaly/000.png\n",
                encoding="utf-8"
            )

    def test_real_mask_to_box_and_family_roles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build_dataset(root)
            old_norm, old_anomaly = mod.EXPECTED_NORMAL, mod.EXPECTED_ANOMALY
            try:
                mod.EXPECTED_NORMAL = (1, 1, 1, 1)
                mod.EXPECTED_ANOMALY = (1, 1, 1, 1)
                rows = mod.load_dataset(root)
                self.assertEqual(len(rows), 8)
                anomaly = next(x for x in rows if x["label"] == "anomaly")
                self.assertEqual(anomaly["regions"][0]["box"], [5/12, 3/10, 7/12, 5/10])
                for fold in range(4):
                    truth, report = mod.make_fold(rows, fold)
                    self.assertEqual(len(truth), 7)
                    self.assertEqual(report["excluded_train_anomalies"], 1)
                    self.assertEqual({x["family"] for x in truth if x["split"] == "challenge"},
                                     {mod.CATEGORIES[(fold+3)%4].upper()})
                    self.assertEqual({x["label"] for x in truth if x["split"] == "train"}, {"normal"})
            finally:
                mod.EXPECTED_NORMAL, mod.EXPECTED_ANOMALY = old_norm, old_anomaly

    def test_mask_missing_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.build_dataset(root)
            (root / "pcb1/Data/Masks/Anomaly/000.png").unlink()
            old_norm, old_anomaly = mod.EXPECTED_NORMAL, mod.EXPECTED_ANOMALY
            try:
                mod.EXPECTED_NORMAL = (1, 1, 1, 1)
                mod.EXPECTED_ANOMALY = (1, 1, 1, 1)
                with self.assertRaises(FileNotFoundError):
                    mod.load_dataset(root)
            finally:
                mod.EXPECTED_NORMAL, mod.EXPECTED_ANOMALY = old_norm, old_anomaly

    def test_immutable_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "manifest.jsonl"
            mod.save_immutable(target, b"hello")
            mod.save_immutable(target, b"hello")
            with self.assertRaises(FileExistsError):
                mod.save_immutable(target, b"different")

if __name__ == "__main__":
    unittest.main()
