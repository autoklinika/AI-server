#!/usr/bin/env python3
from pathlib import Path
import argparse,json,time,sys,torch
from peft import PeftModel
from transformers import AutoTokenizer
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'deploy/stage-p5/training'))
from streaming_bf16_loader import load_qwen_bf16
SYSTEM='''Jesteś diagnostą elektroniki. Używaj wyłącznie danych przypadku. Nie zgaduj konkretnej części bez pomiaru rozdzielającego. Zwróć WYŁĄCZNIE jeden krótki poprawny JSON, bez markdownu i bez dodatkowego tekstu: {"diagnostic_model":"maks. 25 słów: fizyczny model usterki lub ograniczony zestaw hipotez","discriminating_measurement":"maks. 25 słów: jeden test o największej wartości rozdzielającej","predicted_result":"maks. 30 słów: przewidywany wynik i jak rozdzieli hipotezy","abstain":true|false}. `abstain=true` tylko gdy dane są zbyt słabe, by odpowiedzialnie zawęzić model usterki; sam fakt, że trzeba wykonać pomiar rozdzielający, NIE oznacza abstain. Nie podawaj chain-of-thought.'''
REQ_KEYS={'diagnostic_model','discriminating_measurement','predicted_result','abstain'}
def extract_json(text):
 s=text.find('{'); e=text.rfind('}')
 if s<0 or e<s: return None
 try:
  x=json.loads(text[s:e+1]); return x if isinstance(x,dict) and REQ_KEYS.issubset(x) else None
 except Exception: return None
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--model-dir',default='/srv/ai-data/training/p5/models/Qwen3.8-27B-buffered-512m'); ap.add_argument('--adapter-dir',default='/srv/ai-data/training/p5/adapters/electronics-foundation-v3/current'); ap.add_argument('--dataset',default=str(ROOT/'benchmarks/electronics_v3_quality_v1/cases.v1.jsonl')); ap.add_argument('--output',required=True); ap.add_argument('--limit',type=int); ap.add_argument('--max-new-tokens',type=int,default=140); ap.add_argument('--batch-size',type=int,default=1); ap.add_argument('--resume',action='store_true'); args=ap.parse_args()
 rows=[json.loads(x) for x in Path(args.dataset).read_text().splitlines() if x.strip()]; rows=rows[:args.limit] if args.limit else rows
 outpath=Path(args.output); done=set(); mode='w'
 if args.resume and outpath.exists():
  for line in outpath.read_text().splitlines():
   if line.strip(): done.add(json.loads(line)['case_id'])
  mode='a'
 rows=[r for r in rows if r['case_id'] not in done]
 tok=AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True); tok.pad_token_id=tok.pad_token_id or tok.eos_token_id; tok.padding_side='left'
 model,load_metrics=load_qwen_bf16(args.model_dir); model=PeftModel.from_pretrained(model,args.adapter_dir,is_trainable=False); model.eval()
 completed=0; parsed_count=0
 outpath.parent.mkdir(parents=True,exist_ok=True)
 with outpath.open(mode,encoding='utf-8') as fh:
  for start in range(0,len(rows),args.batch_size):
   batch=rows[start:start+args.batch_size]; prompts=[]
   for row in batch:
    msgs=[{'role':'system','content':SYSTEM},{'role':'user','content':row['prompt']}]
    try: prompt=tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    except TypeError: prompt=tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True)
    prompts.append(prompt)
   enc=tok(prompts,return_tensors='pt',padding=True,add_special_tokens=False).to('cuda'); t0=time.perf_counter()
   with torch.inference_mode(): gen=model.generate(**enc,max_new_tokens=args.max_new_tokens,do_sample=False,use_cache=True,pad_token_id=tok.pad_token_id,eos_token_id=tok.eos_token_id)
   torch.cuda.synchronize(); batch_seconds=time.perf_counter()-t0; prefix=enc['input_ids'].shape[1]
   for row,seq in zip(batch,gen):
    new=seq[prefix:]; text=tok.decode(new,skip_special_tokens=True).strip(); parsed=extract_json(text); n_tok=int((new!=tok.pad_token_id).sum().item())
    rec={'case_id':row['case_id'],'category':row['category'],'batch_seconds':batch_seconds,'batch_size':len(batch),'output_tokens':n_tok,'raw':text,'parsed':parsed}
    fh.write(json.dumps(rec,ensure_ascii=False)+'\n'); fh.flush(); completed+=1; parsed_count+=parsed is not None
    print(json.dumps({'index':len(done)+completed,'case_id':row['case_id'],'parsed':parsed is not None,'batch_seconds':round(batch_seconds,3),'batch_size':len(batch),'tokens':n_tok}),flush=True)
 print(json.dumps({'status':'PASS','records_generated':completed,'records_preexisting':len(done),'parsed_generated':parsed_count,'model_load':load_metrics},default=str)); print('P5_5_GENERATION=PASS')
if __name__=='__main__': main()
