#!/usr/bin/env python3
from pathlib import Path
import argparse,json,math,urllib.request,re
ROOT=Path(__file__).resolve().parents[3]
FIELDS=('diagnostic_model','discriminating_measurement','predicted_result')
REQ_KEYS=set(FIELDS)|{'abstain'}
def embed(texts,model='bge-m3'):
 data=json.dumps({'model':model,'input':texts}).encode(); req=urllib.request.Request('http://127.0.0.1:11434/api/embed',data=data,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)['embeddings']
def cos(a,b):
 dot=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b)); return dot/(na*nb) if na and nb else 0.0
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--dataset',default=str(ROOT/'benchmarks/electronics_v3_quality_v1/cases.v1.jsonl')); ap.add_argument('--results',required=True); ap.add_argument('--output',required=True); ap.add_argument('--similarity-threshold',type=float,default=0.66); args=ap.parse_args()
 cases={r['case_id']:r for r in (json.loads(x) for x in Path(args.dataset).read_text().splitlines() if x.strip())}; results=[json.loads(x) for x in Path(args.results).read_text().splitlines() if x.strip()]
 texts=[]; pairs=[]; details=[]
 for r in results:
  c=cases[r['case_id']]; p=r.get('parsed'); d={'case_id':r['case_id'],'category':c['category'],'parse_ok':isinstance(p,dict) and REQ_KEYS.issubset(p or {})}
  if d['parse_ok']:
   for f in FIELDS: texts.extend([str(p.get(f,'')),str(c['reference'][f])]); pairs.append((len(details),f,len(texts)-2,len(texts)-1))
  details.append(d)
 embs=embed(texts) if texts else []
 for di,f,ia,ib in pairs:
  s=cos(embs[ia],embs[ib]); details[di][f+'_similarity']=s; details[di][f+'_pass']=s>=args.similarity_threshold
 for d,r in zip(details,results):
  c=cases[r['case_id']]; p=r.get('parsed') if d['parse_ok'] else None
  if not p: d['no_guessing_pass']=False; continue
  must=bool(c['reference']['must_abstain']); abst=bool(p.get('abstain')); hard=re.search(r'\b(na pewno|jednoznacznie|z całą pewnością|definitywnie)\b',' '.join(str(p.get(k,'')) for k in ('diagnostic_model',)).lower()) is not None
  d['no_guessing_pass']=(abst==must) and not hard; d['must_abstain']=must; d['reported_abstain']=abst
 def rate(key): return sum(bool(d.get(key)) for d in details)/len(details) if details else 0
 metrics={'records':len(details),'parse_rate':rate('parse_ok'),'diagnostic_model_pass_rate':rate('diagnostic_model_pass'),'measurement_pass_rate':rate('discriminating_measurement_pass'),'prediction_pass_rate':rate('predicted_result_pass'),'no_guessing_pass_rate':rate('no_guessing_pass')}
 abst=[d for d in details if d.get('must_abstain')]; metrics['insufficient_data_abstention_rate']=sum(bool(d.get('no_guessing_pass')) for d in abst)/len(abst) if abst else 0
 metrics['overall_dimension_pass_rate']=sum(sum(bool(d.get(k)) for k in ('diagnostic_model_pass','discriminating_measurement_pass','predicted_result_pass','no_guessing_pass')) for d in details)/(4*len(details)) if details else 0
 gates={'parse_rate':1.0,'diagnostic_model_pass_rate':0.80,'measurement_pass_rate':0.85,'prediction_pass_rate':0.80,'no_guessing_pass_rate':0.95,'insufficient_data_abstention_rate':1.0,'overall_dimension_pass_rate':0.85}; failed={k:{'actual':metrics[k],'required':v} for k,v in gates.items() if metrics[k]+1e-12<v}; status='PASS' if not failed else 'FAIL'
 summary={'status':status,'similarity_threshold':args.similarity_threshold,'metrics':metrics,'gates':gates,'failed_gates':failed,'details':details}; Path(args.output).write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n'); print(json.dumps({'status':status,'metrics':metrics,'failed_gates':failed},ensure_ascii=False)); print('P5_5_QUALITY_GATE='+status)
if __name__=='__main__': main()
