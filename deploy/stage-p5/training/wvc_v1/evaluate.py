#!/usr/bin/env python3
"""Raw generation benchmark; no JSON repair, schema-constrained decoding or fallback."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from dataset import digest, validate, schema, expected_ids, current


def score(row, raw):
    result={'record_id':row['record_id'],'task':row['task'], 'valid':False, 'decision_correct':False,
            'grounded':False, 'raw':raw}
    try:
        answer=json.loads(raw)
        expected=json.loads(row['assistant'])
        if row['task']=='CURRENT':
            parsed=schema.EnvironmentalDecisionV121.model_validate(answer,strict=True)
            schema.validate_environmental_decision(row['packet'],parsed)
            assert set(answer)=={'schema_version','environmental_attention','selected_fact_ids'}
            assert parsed.environmental_attention or not parsed.selected_fact_ids
            result['valid']=True
            result['decision_correct']=parsed.environmental_attention==expected['environmental_attention']
            result['grounded']=set(parsed.selected_fact_ids)==set(expected['selected_fact_ids'])
        else:
            assert set(answer)==set(expected) and answer['task']=='WVC_FUTURE_EXTENDED_V1'
            assert type(answer['environmental_attention']) is bool
            assert isinstance(answer['observations'],list) and isinstance(answer['deterministic_facts'],list)
            assert all(isinstance(answer[k],str) and answer[k] for k in ('interpretation_pl','limitations_pl','recommendation_pl'))
            result['valid']=True
            result['decision_correct']=answer['environmental_attention']==expected['environmental_attention']
            result['grounded']=(answer['observations']==expected['observations'] and
                                answer['deterministic_facts']==expected['deterministic_facts'])
            # Narrative still requires human review; do not label factual JSON a semantic pass.
            result['narrative_review']='REQUIRED'
    except (ValueError,TypeError,KeyError,AssertionError):
        pass
    return result


def compare(before, after):
    assert before['manifest_sha256']==after['manifest_sha256']
    results={}
    for split in ('holdout','challenge'):
        b={r['record_id']:r for r in before['results'][split] if r['task']=='CURRENT'}
        a={r['record_id']:r for r in after['results'][split] if r['task']=='CURRENT'}
        assert b.keys()==a.keys() and b
        results[split]={'valid_schema_100_percent':all(r['valid'] for r in a.values()),
            'no_decision_regression':all(not b[k]['decision_correct'] or a[k]['decision_correct'] for k in b),
            'no_evidence_regression':all(not b[k]['grounded'] or a[k]['grounded'] for k in b)}
    return {'current':results,'pass':all(all(r.values()) for r in results.values()),
            'future':'SEPARATE_SCORES_NARRATIVE_REVIEW_REQUIRED','production_promotion':False}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model-dir',required=True)
    ap.add_argument('--data',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--adapter',type=Path)
    args=ap.parse_args()
    validate(args.data)
    if Path(args.model_dir).name!='Qwen3.8-27B-buffered-512m':
        raise RuntimeError('wrong base model')
    if args.adapter:
        manifest=json.loads((args.adapter/'wvc_training_manifest.json').read_text())
        assert manifest['parent_adapter'] is None and manifest['base_model']=='Qwen/Qwen3.8-27B'
        assert manifest['dataset_sha256']==digest(args.data/'train.jsonl')
        assert manifest['adapter_sha256']==digest(args.adapter/'adapter_model.safetensors')
    import torch
    from transformers import AutoTokenizer
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from streaming_bf16_loader import load_qwen_bf16
    tok=AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True)
    model,metrics=load_qwen_bf16(args.model_dir)
    if args.adapter:
        from peft import PeftModel
        model=PeftModel.from_pretrained(model,args.adapter,is_trainable=False)
    model.eval()
    report={'status':'RUNNING','base_model':'Qwen/Qwen3.8-27B',
            'adapter':str(args.adapter) if args.adapter else None,
            'manifest_sha256':digest(args.data/'manifest.json'),'loader':metrics,'results':{},'scores':{}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for split in ('holdout','challenge'):
        report['results'][split]=[]
        for row in map(json.loads,(args.data/f'{split}.jsonl').read_text().splitlines()):
            prompt=[{'role':'system','content':row['system']},{'role':'user','content':row['user']}]
            text=tok.apply_chat_template(prompt,tokenize=False,add_generation_prompt=True,enable_thinking=False)
            inputs=tok(text,add_special_tokens=False,return_tensors='pt').to('cuda')
            if inputs.input_ids.shape[-1]>8192: raise RuntimeError('eval prompt too long; refusing truncation')
            start=time.monotonic()
            with torch.inference_mode():
                generated=model.generate(**inputs,do_sample=False,max_new_tokens=256 if row['task']=='CURRENT' else 4096,
                                         pad_token_id=tok.eos_token_id)
            raw=tok.decode(generated[0,inputs.input_ids.shape[-1]:],skip_special_tokens=True)
            result=score(row,raw)|{'seconds':time.monotonic()-start}
            report['results'][split].append(result)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'eval':split,**{k:v for k,v in result.items() if k!='raw'}}),flush=True)
        report['scores'][split]={}
        for task in ('CURRENT','FUTURE'):
            rows=[r for r in report['results'][split] if r['task']==task]
            report['scores'][split][task]={'count':len(rows),**{k:sum(r[k] for r in rows)/len(rows) for k in ('valid','decision_correct','grounded')}}
    report['status']='COMPLETE'
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__': main()
