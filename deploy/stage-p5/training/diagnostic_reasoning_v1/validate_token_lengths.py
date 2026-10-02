#!/usr/bin/env python3
"""Optional CPU-only exact chat-template validation; never loads model weights."""
import argparse
import json
from pathlib import Path
from prepare_diagnostic_reasoning_v1 import HERE, read, sha


def check(model_dir):
    from transformers import AutoTokenizer
    from validate_diagnostic_reasoning_v1 import validate
    validate()
    tok=AutoTokenizer.from_pretrained(str(model_dir),local_files_only=True)
    lengths=[]
    for row in read(HERE/'diagnostic_reasoning_v1_replay_train.jsonl'):
        prompt=[{'role':'system','content':row['system']},{'role':'user','content':row['user']}]
        full=prompt+[{'role':'assistant','content':row['assistant']}]
        pids=tok(tok.apply_chat_template(prompt,tokenize=False,add_generation_prompt=True, enable_thinking=False),add_special_tokens=False)['input_ids']
        fids=tok(tok.apply_chat_template(full,tokenize=False,add_generation_prompt=False, enable_thinking=False),add_special_tokens=False)['input_ids']
        if not 0<len(pids)<len(fids)<=768: raise ValueError('token contract: '+row['record_id'])
        if fids[:len(pids)]!=pids: raise ValueError('chat template prompt/target prefix mismatch')
        lengths.append(dict(record_id=row['record_id'],full_tokens=len(fids),target_tokens=len(fids)-len(pids)))
    report=dict(stage='P5.12',status='PASS',records=len(lengths),max_length=768,truncated_records=0,
        dataset_sha256=sha(HERE/'diagnostic_reasoning_v1_replay_train.jsonl'),
        tokenizer_sha256=sha(model_dir/'tokenizer.json'),tokenizer_config_sha256=sha(model_dir/'tokenizer_config.json'),
        max_tokens=max(r['full_tokens'] for r in lengths),max_target_tokens=max(r['target_tokens'] for r in lengths),
        quality_acceptance='PENDING_POST_TRAINING_SMOKE',lengths=lengths)
    return report
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--model-dir',type=Path,required=True)
    ap.add_argument('--output',type=Path,default=HERE/'token_validation.json'); args=ap.parse_args()
    result=check(args.model_dir); args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='lengths'},sort_keys=True))
