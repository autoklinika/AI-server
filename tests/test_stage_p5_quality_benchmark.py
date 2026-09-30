import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'benchmarks/electronics_v3_quality_v1/cases.v1.jsonl'
def rows(): return [json.loads(x) for x in DATA.read_text().splitlines() if x.strip()]
def test_p55_has_several_dozen_frozen_cases():
 r=rows(); assert len(r)==42; assert len({x['case_id'] for x in r})==42; assert all(x['training_exclusion'] is True for x in r)
def test_p55_covers_requested_case_families():
 cats={x['category'] for x in rows()}; assert {'schematic_symptom_measurements','numeric_waveform','thermal_intermittent','pcb_short','good_bad_channel_comparison','insufficient_data'} <= cats
def test_p55_dataset_is_novel_against_electronics_training():
 p=subprocess.run([sys.executable,str(ROOT/'deploy/stage-p5/benchmark/validate_quality_benchmark_v1.py')],cwd=ROOT,text=True,capture_output=True); assert p.returncode==0,p.stdout+p.stderr; assert 'P5_5_DATASET_VALIDATION=PASS' in p.stdout
