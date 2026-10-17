import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pcb_benchmark', ROOT / 'benchmark.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
GT = ROOT / 'fixtures' / 'ground_truth.jsonl'


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.ground = mod.load_jsonl(GT)
        self.calibration = mod.load_jsonl(ROOT / 'fixtures' / 'winclip_calibration.jsonl')
        self.holdout = mod.load_jsonl(ROOT / 'fixtures' / 'winclip_holdout.jsonl')

    def test_fixture_valid(self):
        self.assertEqual(mod.validate_ground(self.ground)['count'], 14)

    def test_specimen_split_leakage_fail_closed(self):
        altered = copy.deepcopy(self.ground)
        altered[-1]['specimen_id'] = altered[0]['specimen_id']
        with self.assertRaisesRegex(mod.BenchmarkError, 'LEAKAGE'):
            mod.validate_ground(altered)

    def test_hash_split_leakage_fail_closed(self):
        altered = copy.deepcopy(self.ground)
        altered[-1]['sha256'] = altered[0]['sha256']
        with self.assertRaisesRegex(mod.BenchmarkError, 'LEAKAGE'):
            mod.validate_ground(altered)

    def test_challenge_family_must_be_new(self):
        altered = copy.deepcopy(self.ground)
        altered[-1]['family'] = 'A'
        with self.assertRaisesRegex(mod.BenchmarkError, 'LEAKAGE'):
            mod.validate_ground(altered)

    def test_prediction_coverage_and_no_other_split(self):
        with self.assertRaisesRegex(mod.BenchmarkError, 'incomplete prediction'):
            mod.validate_predictions(self.holdout[:-1], self.ground, 'holdout')
        with self.assertRaisesRegex(mod.BenchmarkError, 'unexpected prediction'):
            mod.validate_predictions(self.calibration, self.ground, 'holdout')

    def test_perfect_prediction_image_and_box_score(self):
        model,pred = mod.validate_predictions(self.holdout, self.ground, 'holdout')
        self.assertEqual(model,'winclip')
        result=mod.evaluate(self.ground,pred,'holdout',0.201,0.5,0.3)
        self.assertEqual(result['image']['auroc'],1.0)
        self.assertEqual(result['image']['average_precision'],1.0)
        self.assertEqual(result['image']['recall'],1.0)
        self.assertEqual(result['localization']['recall'],1.0)
        self.assertEqual(result['localization']['false_alarms_per_pcb'],0.0)

    def test_calibration_never_uses_holdout(self):
        _,pred=mod.validate_predictions(self.calibration,self.ground,'calibration')
        result=mod.thresholds_calibrate(self.ground,pred,0.05)
        self.assertGreater(result['image_threshold'],0.2)
        self.assertEqual(result['calibration_fpr'],0)

    def test_auc_ties_and_ap_order_invariant(self):
        a=mod.average_precision([1,0,1,0],[0.5,0.5,0.1,0.1])
        b=mod.average_precision([0,1,0,1],[0.5,0.5,0.1,0.1])
        self.assertAlmostEqual(a,b)
        self.assertEqual(mod.roc_auc([1,0],[0.5,0.5]),0.5)

    def test_region_metrics_unsupported_not_zero(self):
        altered=copy.deepcopy(self.holdout)
        for item in altered:
            item['localization_mode']='none'
            item['regions']=[]
        _,pred=mod.validate_predictions(altered,self.ground,'holdout')
        result=mod.evaluate(self.ground,pred,'holdout',0.3,0.5,0.3)
        self.assertEqual(result['localization']['status'],'not_supported')
        self.assertIsNone(result['localization']['recall'])

    def test_cli_end_to_end_and_immutable_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            calib=pathlib.Path(d)/'thresholds.json'
            scored=pathlib.Path(d)/'score.json'
            base=[sys.executable,str(ROOT/'benchmark.py')]
            r=subprocess.run(base+['validate','--ground-truth',str(GT)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run(base+['calibrate','--ground-truth',str(GT),'--predictions',str(ROOT/'fixtures/winclip_calibration.jsonl'),'--output',str(calib)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run(base+['score','--ground-truth',str(GT),'--predictions',str(ROOT/'fixtures/winclip_holdout.jsonl'),'--thresholds',str(calib),'--calibration-predictions',str(ROOT/'fixtures/winclip_calibration.jsonl'),'--split','holdout','--output',str(scored)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads(scored.read_text())['metrics']['image']['recall'],1.0)
            r=subprocess.run(base+['score','--ground-truth',str(GT),'--predictions',str(ROOT/'fixtures/winclip_holdout.jsonl'),'--thresholds',str(calib),'--calibration-predictions',str(ROOT/'fixtures/winclip_calibration.jsonl'),'--split','holdout','--output',str(scored)],capture_output=True,text=True)
            self.assertEqual(r.returncode,2)


    def test_calibration_provenance_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            cal = d/'cal.json'
            base = [sys.executable, str(ROOT/'benchmark.py')]
            correct = ROOT/'fixtures/winclip_calibration.jsonl'
            subprocess.run(base+['calibrate','--ground-truth',str(GT),'--predictions',str(correct),'--output',str(cal)],check=True,capture_output=True)
            tampered = d/'tampered.jsonl'
            contents = correct.read_text().replace('0.2,', '0.21,')
            self.assertNotEqual(contents, correct.read_text())
            tampered.write_text(contents)
            result = subprocess.run(base+['score','--ground-truth',str(GT),'--predictions',str(ROOT/'fixtures/winclip_holdout.jsonl'),'--thresholds',str(cal),'--calibration-predictions',str(tampered),'--split','holdout','--output',str(d/'invalid.json')],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('calibration predictions changed',result.stderr)
            self.assertFalse((d/'invalid.json').exists())

    def test_calibration_proof_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            d=pathlib.Path(d)
            cal=d/'cal.json'
            base=[sys.executable,str(ROOT/'benchmark.py')]
            correct=ROOT/'fixtures/winclip_calibration.jsonl'
            subprocess.run(base+['calibrate','--ground-truth',str(GT),'--predictions',str(correct),'--output',str(cal)],check=True,capture_output=True)
            data=json.loads(cal.read_text())
            data['image_threshold']=0.9
            cal.write_text(json.dumps(data))
            res=subprocess.run(base+['score','--ground-truth',str(GT),'--predictions',str(ROOT/'fixtures/winclip_holdout.jsonl'),'--thresholds',str(cal),'--calibration-predictions',str(correct),'--split','holdout','--output',str(d/'invalid.json')],capture_output=True,text=True)
            self.assertEqual(res.returncode,2)
            self.assertIn('calibration proof failed',res.stderr)


if __name__=='__main__':
    unittest.main()
