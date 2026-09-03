#!/usr/bin/env bash
set -euo pipefail

PYTHON="/opt/ai-bridge/.venv/bin/python"
HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
OLLAMA="http://127.0.0.1:11434"
GATEWAY="http://127.0.0.1:11435"
MAX_TOKENS=192

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$PYTHON" ] || { say "FAIL: missing $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: missing $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: missing $HERMES_CONFIG"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama inactive"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: gateway inactive"; exit 1; }

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg=yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
m=cfg.get('model') or {}
if isinstance(m,str): model=m.strip()
elif isinstance(m,dict): model=str(m.get('default') or m.get('model') or '').strip()
else: model=''
if not model:
    for item in cfg.get('custom_providers') or []:
        if isinstance(item,dict) and item.get('model'):
            model=str(item['model']).strip(); break
print(model)
PY
)"
[ -n "$MODEL" ] || { say "FAIL: model unresolved"; exit 1; }

section "STAGE-8 HERMES INFERENCE PATH PROFILE"
say "model:      $MODEL"
say "max tokens: $MAX_TOKENS"
say "Read-only benchmark: no service restarts and no config changes."

section "GATEWAY PRECHECK"
"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:11435/status',timeout=2) as r:
    s=json.load(r)
assert s.get('active_count')==0 and s.get('queued_count')==0,s
print(json.dumps(s,indent=2))
PY

section "MODEL SHOW SUMMARY"
"$PYTHON" - "$MODEL" <<'PY'
import json,sys,urllib.request
model=sys.argv[1]
payload=json.dumps({'model':model}).encode()
req=urllib.request.Request('http://127.0.0.1:11434/api/show',data=payload,headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=20) as r:
    d=json.load(r)
print('details:',json.dumps(d.get('details') or {},ensure_ascii=False,indent=2))
print('parameters:')
print((d.get('parameters') or '').strip() or '<none>')
print('system:')
print((d.get('system') or '').strip()[:2000] or '<none>')
print('template head:')
t=(d.get('template') or '').strip()
print(t[:2000] if t else '<none>')
PY

section "PROFILE FOUR REQUEST PATHS"
"$PYTHON" - "$MODEL" "$MAX_TOKENS" <<'PY'
from __future__ import annotations
import json,sys,time,urllib.request

model=sys.argv[1]
max_tokens=int(sys.argv[2])
prompt='Wyjaśnij w sposób techniczny, ale zwięzły, czym różni się scheduler AI od silnika inferencji. Nie używaj narzędzi.'


def post(url,payload,timeout=600):
    data=json.dumps(payload).encode()
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'})
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=timeout) as r:
        body=json.load(r)
        headers=dict(r.headers.items())
    return time.monotonic()-t0,body,headers


def native(label, think_marker):
    payload={
      'model':model,
      'messages':[{'role':'user','content':prompt}],
      'stream':False,
      'options':{'temperature':0,'num_predict':max_tokens},
    }
    if think_marker is not None:
        payload['think']=think_marker
    wall,b,h=post('http://127.0.0.1:11434/api/chat',payload)
    content=((b.get('message') or {}).get('content') or '')
    thinking=((b.get('message') or {}).get('thinking') or b.get('thinking') or '')
    return {
      'label':label,'wall_s':wall,'eval_count':b.get('eval_count'),
      'eval_duration_ns':b.get('eval_duration'),'prompt_eval_count':b.get('prompt_eval_count'),
      'content_chars':len(content),'thinking_chars':len(thinking),'done':b.get('done'),
      'done_reason':b.get('done_reason'),
    }


def openai(label,url):
    payload={
      'model':model,
      'messages':[{'role':'user','content':prompt}],
      'stream':False,
      'temperature':0,
      'max_tokens':max_tokens,
    }
    wall,b,h=post(url,payload)
    choices=b.get('choices') or []
    msg=(choices[0].get('message') or {}) if choices else {}
    content=msg.get('content') or ''
    reasoning=msg.get('reasoning_content') or msg.get('reasoning') or ''
    usage=b.get('usage') or {}
    return {
      'label':label,'wall_s':wall,
      'prompt_tokens':usage.get('prompt_tokens'),'completion_tokens':usage.get('completion_tokens'),
      'content_chars':len(content),'reasoning_chars':len(reasoning),
      'finish_reason':choices[0].get('finish_reason') if choices else None,
      'gateway_job_id':h.get('X-AI-Gateway-Job-Id'),
      'gateway_priority':h.get('X-AI-Gateway-Priority'),
      'gateway_wait_ms':h.get('X-AI-Gateway-Wait-Ms'),
      'response_keys':sorted(b.keys()),'message_keys':sorted(msg.keys()),
    }

results=[]
for fn in [
    lambda: native('native-think-false',False),
    lambda: native('native-default-think',None),
    lambda: openai('ollama-openai-direct','http://127.0.0.1:11434/v1/chat/completions'),
    lambda: openai('gateway-hermes-openai','http://127.0.0.1:11435/clients/hermes/v1/chat/completions'),
]:
    r=fn(); results.append(r); print(json.dumps(r,ensure_ascii=False,indent=2))

base=results[0]['wall_s']
print('\n===== SUMMARY =====')
for r in results:
    ratio=r['wall_s']/base if base else None
    print(f"{r['label']:<24} {r['wall_s']:>8.2f}s  vs think:false = {ratio:.2f}x")
print('\nfull JSON: /tmp/ai-gateway-stage8-hermes-profile.json')
open('/tmp/ai-gateway-stage8-hermes-profile.json','w',encoding='utf-8').write(json.dumps(results,ensure_ascii=False,indent=2))
PY

section "POSTCHECK"
"$PYTHON" - <<'PY'
import json,urllib.request
with urllib.request.urlopen('http://127.0.0.1:11435/status',timeout=2) as r:
    s=json.load(r)
assert s.get('active_count')==0 and s.get('queued_count')==0,s
print('PASS: gateway idle')
PY
say "PASS: stage-8 Hermes inference path profile completed"
