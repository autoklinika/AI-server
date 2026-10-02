#!/usr/bin/env python3
"""Explicit opt-in future two-model Ollama smoke; no imports trigger inference."""
import argparse
import hashlib
import json
import re
import unicodedata
import urllib.request
from prepare_diagnostic_reasoning_v1 import HERE, read, sha


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.lower().replace('ł','l')) if not unicodedata.combining(c))

def score(text,row):
    text=normalized(text)
    matches={k:any(normalized(a) in text for a in anchors) for k,anchors in row['expected_anchors'].items()}
    # Hypotheses must cover both competing concepts, not just one keyword.
    matches['hypotheses']=all(normalized(a) in text for a in row['expected_anchors']['hypotheses'])
    matches['high_information_next_measurement']=matches['next_a'] and matches['next_b']
    if not row['metadata']['good_channel_applicable']: matches.pop('good_channel')
    # Conservative flag; human review handles false positives, including quoted guesses.
    unsupported=bool(re.search(r'\b(?:wymien|winny jest|uszkodzony jest)\b|\b[a-z]{2,}\d+[a-z\d-]*\b',text))
    matches['unsupported_component_guess']=matches['unsupported_component_guess'] and not unsupported
    return dict(criteria=matches,points=sum(matches.values()),possible=len(matches),unsupported_guess_flag=unsupported,
                quality_acceptance='PENDING_HUMAN_REVIEW_OF_POST_TRAINING_SMOKE')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--models',nargs=2,required=True)
    ap.add_argument('--output',type=__import__('pathlib').Path,required=True)
    ap.add_argument('--url',default='http://127.0.0.1:11434'); args=ap.parse_args()
    if args.models[0]==args.models[1]: ap.error('two distinct model names required')
    from validate_diagnostic_reasoning_v1 import validate
    validate()
    rows=read(HERE/'diagnostic_reasoning_v1_smoke.jsonl')
    results=[]
    for model in args.models:
        for row in rows:
            body=dict(model=model,system=row['system'],prompt=row['user'],stream=False,think=False,keep_alive='0s',
                      options=dict(temperature=0,seed=20261003,num_ctx=4096,num_predict=768))
            req=urllib.request.Request(args.url+'/api/generate',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=600) as response: raw=json.load(response)
            if raw.get('done') is not True or not raw.get('response','').strip(): raise RuntimeError('incomplete smoke response')
            text=raw['response']
            results.append(dict(model=model,record_id=row['record_id'],response=text,response_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                done_reason=raw.get('done_reason'),score=score(text,row)))
    args.output.write_text(json.dumps(dict(stage='P5.12',smoke_sha256=sha(HERE/'diagnostic_reasoning_v1_smoke.jsonl'),
        quality_acceptance='PENDING_HUMAN_REVIEW_OF_POST_TRAINING_SMOKE',results=results),ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__': main()
