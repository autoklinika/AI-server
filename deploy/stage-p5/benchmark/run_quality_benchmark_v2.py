#!/usr/bin/env python3
from pathlib import Path
import argparse,json,time,sys,torch
from peft import PeftModel
from transformers import AutoTokenizer

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'deploy/stage-p5/training'))
from streaming_bf16_loader import load_qwen_bf16

SYSTEM='''Jesteś diagnostą elektroniki. Używaj wyłącznie danych przypadku. Nie zgaduj konkretnej części bez pomiaru rozdzielającego. Zwróć WYŁĄCZNIE jeden krótki poprawny JSON, bez markdownu i bez dodatkowego tekstu: {"diagnostic_model":"maks. 25 słów: fizyczny model usterki lub ograniczony zestaw hipotez","discriminating_measurement":"maks. 25 słów: jeden test o największej wartości rozdzielającej","predicted_result":"maks. 30 słów: przewidywany wynik i jak rozdzieli hipotezy","abstain":true|false}. `abstain=true` tylko gdy dane są zbyt słabe, by odpowiedzialnie zawęzić model usterki; sam fakt, że trzeba wykonać pomiar rozdzielający, NIE oznacza abstain. Nie podawaj chain-of-thought.'''
REPAIR='''Poprzednia odpowiedź nie spełniła kontraktu JSON. Zwróć WYŁĄCZNIE poprawny JSON z dokładnie czterema kluczami: diagnostic_model, discriminating_measurement, predicted_result, abstain. Zachowaj sens poprzedniej odpowiedzi, niczego nie dopowiadaj i nie używaj markdownu.'''
REQ={'diagnostic_model','discriminating_measurement','predicted_result','abstain'}

def extract_json(text):
    s=text.find('{'); e=text.rfind('}')
    if s<0 or e<s: return None
    try:
        x=json.loads(text[s:e+1])
        return x if isinstance(x,dict) and set(x)==REQ and isinstance(x.get('abstain'),bool) else None
    except Exception:
        return None

def render(tok,msgs):
    try: return tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    except TypeError: return tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True)

def generate(model,tok,prompts,max_new_tokens):
    enc=tok(prompts,return_tensors='pt',padding=True,add_special_tokens=False).to('cuda')
    t0=time.perf_counter()
    with torch.inference_mode():
        gen=model.generate(**enc,max_new_tokens=max_new_tokens,do_sample=False,use_cache=True,
          pad_token_id=tok.pad_token_id,eos_token_id=tok.eos_token_id)
    torch.cuda.synchronize(); dt=time.perf_counter()-t0; prefix=enc['input_ids'].shape[1]
    out=[]
    for seq in gen:
        new=seq[prefix:]; out.append((tok.decode(new,skip_special_tokens=True).strip(),int((new!=tok.pad_token_id).sum().item())))
    return out,dt

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--model-dir',required=True); ap.add_argument('--adapter-dir',required=True)
    ap.add_argument('--dataset',required=True); ap.add_argument('--output',required=True); ap.add_argument('--batch-size',type=int,default=8)
    ap.add_argument('--max-new-tokens',type=int,default=140); ap.add_argument('--limit',type=int); a=ap.parse_args()
    rows=[json.loads(x) for x in Path(a.dataset).read_text().splitlines() if x.strip()]
    if a.limit: rows=rows[:a.limit]
    tok=AutoTokenizer.from_pretrained(a.model_dir,local_files_only=True); tok.pad_token_id=tok.pad_token_id or tok.eos_token_id; tok.padding_side='left'
    model,load=load_qwen_bf16(a.model_dir); model=PeftModel.from_pretrained(model,a.adapter_dir,is_trainable=False); model.eval()
    outp=Path(a.output); outp.parent.mkdir(parents=True,exist_ok=True)
    records=[]; raw_ok=0; repaired=0
    for start in range(0,len(rows),a.batch_size):
        batch=rows[start:start+a.batch_size]
        prompts=[render(tok,[{'role':'system','content':SYSTEM},{'role':'user','content':r['prompt']}]) for r in batch]
        outs,dt=generate(model,tok,prompts,a.max_new_tokens)
        pending=[]
        for j,(r,(text,nt)) in enumerate(zip(batch,outs)):
            parsed=extract_json(text)
            if parsed is not None: raw_ok+=1
            rec={'case_id':r['case_id'],'category':r['category'],'raw':text,'raw_parse_ok':parsed is not None,
                 'parsed':parsed,'repaired':False,'batch_seconds':dt,'output_tokens':nt}
            records.append(rec)
            if parsed is None: pending.append((len(records)-1,r,text))
        if pending:
            repair_prompts=[]
            for _,r,text in pending:
                repair_prompts.append(render(tok,[{'role':'system','content':SYSTEM},{'role':'user','content':r['prompt']},
                  {'role':'assistant','content':text},{'role':'user','content':REPAIR}]))
            routs,rdt=generate(model,tok,repair_prompts,a.max_new_tokens)
            for (idx,_,_), (text,nt) in zip(pending,routs):
                parsed=extract_json(text); records[idx]['repair_raw']=text; records[idx]['repair_tokens']=nt
                records[idx]['repair_seconds']=rdt; records[idx]['parsed']=parsed; records[idx]['repaired']=parsed is not None
                if parsed is not None: repaired+=1
        print(json.dumps({'completed':len(records),'total':len(rows),'raw_parse_ok':raw_ok,'repaired':repaired}),flush=True)
    with outp.open('w',encoding='utf-8') as f:
        for r in records: f.write(json.dumps(r,ensure_ascii=False)+'\n')
    final_ok=sum(r['parsed'] is not None for r in records)
    summary={'status':'PASS' if final_ok==len(records) else 'FAIL','records':len(records),
      'raw_parse_rate':raw_ok/len(records) if records else 0,'repair_successes':repaired,
      'final_parse_rate':final_ok/len(records) if records else 0,'model_load':load}
    print(json.dumps(summary,default=str)); print('P57_GENERATION='+summary['status'])
if __name__=='__main__': main()
