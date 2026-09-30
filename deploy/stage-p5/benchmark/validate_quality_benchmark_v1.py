#!/usr/bin/env python3
from pathlib import Path
import argparse,json,re,difflib
ROOT=Path(__file__).resolve().parents[3]
def norm(s): return ' '.join(re.findall(r'[a-z0-9ąćęłńóśźż]+',s.lower()))
def main():
 p=argparse.ArgumentParser(); p.add_argument('--dataset',default=str(ROOT/'benchmarks/electronics_v3_quality_v1/cases.v1.jsonl')); a=p.parse_args()
 rows=[json.loads(x) for x in Path(a.dataset).read_text().splitlines() if x.strip()]
 assert len(rows)>=40, f'too few cases: {len(rows)}'
 ids=[r['case_id'] for r in rows]; assert len(ids)==len(set(ids))
 assert all(r.get('training_exclusion') is True for r in rows)
 cats={r['category'] for r in rows}; assert len(cats)>=7
 train=[]
 for pat in ['deploy/stage-p5/training/electronics/*jsonl','deploy/stage-p5/training/electronics_v2/*jsonl','deploy/stage-p5/training/electronics_v3/*jsonl']:
  for f in ROOT.glob(pat):
   for line in f.read_text().splitlines():
    if not line.strip(): continue
    x=json.loads(line); train.append(norm(x.get('user','')))
 max_ratio=0; closest=None
 for r in rows:
  q=norm(r['prompt']); assert q not in train, f'exact leakage {r["case_id"]}'
  for t in train:
   if not t: continue
   ratio=difflib.SequenceMatcher(None,q,t,autojunk=True).ratio()
   if ratio>max_ratio: max_ratio=ratio; closest=r['case_id']
 assert max_ratio < 0.82, f'near-copy leakage {closest}: {max_ratio:.3f}'
 forbidden=('scania','bosch','xj3','kl15','kl30','john deere','mpc555','mc33816')
 for r in rows:
  low=r['prompt'].lower(); assert not any(x in low for x in forbidden), f'OEM leakage {r["case_id"]}'
 print(json.dumps({'status':'PASS','records':len(rows),'categories':sorted(cats),'max_train_similarity':round(max_ratio,4),'closest_case':closest},ensure_ascii=False))
 print('P5_5_DATASET_VALIDATION=PASS')
if __name__=='__main__': main()
