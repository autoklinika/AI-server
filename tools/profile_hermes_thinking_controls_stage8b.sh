#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
BASE="http://127.0.0.1:11434"
GATEWAY="http://127.0.0.1:11435"

[ -x "$PYTHON" ] || { echo "FAIL: missing $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { echo "FAIL: missing $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { echo "FAIL: missing $HERMES_CONFIG"; exit 1; }

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys,yaml
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
[ -n "$MODEL" ] || { echo "FAIL: could not resolve model"; exit 1; }

printf '%s\n' "===== STAGE-8B OPENAI THINKING CONTROL MATRIX ====="
echo "model: $MODEL"
echo "ollama: $(ollama --version 2>/dev/null || true)"
echo "Read-only: no config or service changes."

"$PYTHON" - "$MODEL" <<'PY'
from __future__ import annotations
import json,sys,time,urllib.error,urllib.request

MODEL=sys.argv[1]
URL='http://127.0.0.1:11434/v1/chat/completions'
GW='http://127.0.0.1:11435/clients/hermes/v1/chat/completions'
BASE_PROMPT='Odpowiedz po polsku jednym krótkim zdaniem: czym jest lokalny serwer AI?'

cases=[
    ('default',{},BASE_PROMPT),
    ('reasoning-none',{'reasoning_effort':'none'},BASE_PROMPT),
    ('reasoning-minimal',{'reasoning_effort':'minimal'},BASE_PROMPT),
    ('reasoning-low',{'reasoning_effort':'low'},BASE_PROMPT),
    ('top-level-think-false',{'think':False},BASE_PROMPT),
    ('chat-template-disable',{'chat_template_kwargs':{'enable_thinking':False}},BASE_PROMPT),
    ('slash-no-think',{},BASE_PROMPT+' /no_think'),
]

def call(label,extra,prompt,url=URL):
    payload={
        'model':MODEL,
        'messages':[{'role':'user','content':prompt}],
        'stream':False,
        'max_tokens':128,
        'temperature':0,
    }
    payload.update(extra)
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    t0=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=180) as r:
            body=json.load(r)
            headers=dict(r.headers.items())
    except urllib.error.HTTPError as exc:
        raw=exc.read().decode(errors='replace')[:1000]
        return {'label':label,'status':exc.code,'error':raw,'wall_s':time.monotonic()-t0}
    choice=(body.get('choices') or [{}])[0]
    msg=choice.get('message') or {}
    usage=body.get('usage') or {}
    return {
        'label':label,
        'status':200,
        'wall_s':time.monotonic()-t0,
        'finish_reason':choice.get('finish_reason'),
        'content_chars':len(msg.get('content') or ''),
        'reasoning_chars':len(msg.get('reasoning') or msg.get('reasoning_content') or ''),
        'completion_tokens':usage.get('completion_tokens'),
        'gateway_job_id':headers.get('X-Ai-Gateway-Job-Id') or headers.get('x-ai-gateway-job-id'),
    }

results=[]
for label,extra,prompt in cases:
    row=call(label,extra,prompt)
    results.append(row)
    print(json.dumps(row,ensure_ascii=False,indent=2))

# Verify the best-looking control through the actual Hermes namespace only if one worked direct.
working=[r for r in results if r.get('status')==200 and r.get('reasoning_chars')==0 and r.get('content_chars',0)>0 and r['label']!='default']
if working:
    label=working[0]['label']
    extra,prompt=next((e,p) for l,e,p in cases if l==label)
    gw=call('gateway-'+label,extra,prompt,GW)
    print(json.dumps(gw,ensure_ascii=False,indent=2))
else:
    gw=None

print('\n===== SUMMARY =====')
for r in results:
    print(f"{r['label']:<24} status={r.get('status')} content={r.get('content_chars','-')} reasoning={r.get('reasoning_chars','-')} wall={r.get('wall_s',0):.2f}s")
if working:
    print(f"WORKING CONTROL: {working[0]['label']}")
    if gw:
        print(f"gateway verification: content={gw.get('content_chars')} reasoning={gw.get('reasoning_chars')} status={gw.get('status')}")
else:
    print('NO WORKING OPENAI-COMPAT THINKING-OFF CONTROL FOUND')
PY

echo
echo "===== POSTCHECK ====="
curl -fsS "$GATEWAY/status"; echo

echo "PASS: stage-8B read-only thinking-control matrix completed"
