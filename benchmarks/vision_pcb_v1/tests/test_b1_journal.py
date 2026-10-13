"""No GPU, no network: tests of B1 incremental evidence and resumability."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

file=Path(__file__).resolve().parents[1]/"b1_journal.py"
spec=importlib.util.spec_from_file_location("b1_journal",file)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

class JournalTests(unittest.TestCase):
    @staticmethod
    def config():
        return {"preprocessing_mode":"global","ground_truth_sha256":"a"*64}
    @staticmethod
    def row(sid,score=.3):
        return {"sample_id":sid,"model_id":"winclip","image_score":score,
                "regions":[],"localization_mode":"none",
                "image_sha256":"b"*64,"preprocessing_mode":"global"}
    def test_complete_only_exact_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d)/"run",self.config(),{"s1","s2"})
            self.assertFalse(j.finalize())
            j.write(self.row("s1"))
            self.assertEqual(j.progress(),(1,2))
            self.assertFalse(j.finalize())
            j.close()
            j2=mod.Journal(Path(d)/"run",self.config(),{"s1","s2"})
            self.assertEqual(j2.read("s1")["image_score"],.3)
            j2.write(self.row("s2"))
            self.assertTrue(j2.finalize())
            self.assertTrue(j2.finalize())
            self.assertEqual(len((Path(d)/"run"/"predictions.jsonl").read_text().splitlines()),2)
            j2.close()
    def test_reject_changed_config(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d),self.config(),{"s1"});j.close()
            with self.assertRaises(FileExistsError):
                mod.Journal(Path(d),{"preprocessing_mode":"tiled"}, {"s1"})
    def test_reject_duplicate_sample(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d),self.config(),{"s1"})
            j.write(self.row("s1"))
            with self.assertRaises(FileExistsError):j.write(self.row("s1",.9))
            j.close()
    def test_reject_invalid_prediction(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d),self.config(),{"s1"})
            with self.assertRaises(ValueError):j.write(self.row("unknown"))
            with self.assertRaises(ValueError):j.write(self.row("s1",float("nan")))
            j.close()
    def test_tampered_cached_record(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d),self.config(),{"s1"})
            j.write(self.row("s1"))
            p=j.path("s1");obj=json.loads(p.read_text());obj["image_score"]=1.4
            p.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):j.read("s1")
            j.close()
    def test_unexpected_record_detected(self):
        with tempfile.TemporaryDirectory() as d:
            j=mod.Journal(Path(d),self.config(),{"s1"})
            p=j.dir/"records"/"fake.json";p.write_text(json.dumps(self.row("other")))
            with self.assertRaises(ValueError):j.finalize()
            j.close()

    def test_missing_or_corrupted_map_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            cfg={**self.config(),"anomaly_map_resolution":256}
            j=mod.Journal(Path(d),cfg,{"s1"})
            row=self.row("s1")
            raw=b"dummy-map"
            row["map_sha256"]=mod.sha256_bytes(raw)
            j.write(row)
            with self.assertRaises(ValueError):j.read("s1")
            f=j.dir/"maps"/(mod.hashlib.sha256(b"s1").hexdigest()+".npz")
            f.parent.mkdir(exist_ok=True)
            f.write_bytes(raw)
            self.assertEqual(j.read("s1")["map_sha256"],row["map_sha256"])
            f.write_bytes(b"corrupted")
            with self.assertRaises(ValueError):j.finalize()
            j.close()

if __name__=="__main__":unittest.main()
