#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
PRIMARY="http://127.0.0.1:11434"
SECONDARY="http://127.0.0.1:11436"
MODELS_DIR="/usr/share/ollama/.ollama/models"
SECONDARY_UNIT="ollama-stage7-secondary.service"
SECONDARY_UNIT_FILE="/run/systemd/system/${SECONDARY_UNIT}"
RESULT_JSON="/tmp/ai-gateway-stage7-dual-runner.json"
CONTEXT=32768
NUM_PREDICT=128
SECONDARY_MEMORY_MAX="32G"

HERMES_WAS_ACTIVE=0
TIMER_WAS_ACTIVE=0
SECONDARY_STARTED=0
RESTORED=0

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

mem_available_gib() {
    awk '/^MemAvailable:/ {printf "%.2f", $2/1024/1024}' /proc/meminfo
}

stop_secondary() {
    if [ "$SECONDARY_STARTED" -eq 1 ] || systemctl is-active --quiet "$SECONDARY_UNIT" 2>/dev/null; then
        sudo systemctl stop "$SECONDARY_UNIT" >/dev/null 2>&1 || true
    fi
    sudo rm -f "$SECONDARY_UNIT_FILE" >/dev/null 2>&1 || true
    sudo systemctl daemon-reload >/dev/null 2>&1 || true
    SECONDARY_STARTED=0
}

warm_primary_production() {
    "$PYTHON" - "$MODEL" <<'PY' >/dev/null 2>&1 || true
import json, sys, urllib.request
payload=json.dumps({
    "model":sys.argv[1],
    "messages":[{"role":"user","content":"Odpowiedz dokładnie: OK"}],
    "stream":False,
    "think":False,
    "options":{"temperature":0,"num_predict":4},
}).encode()
req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=payload,headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=300) as r:
    body=json.load(r)
assert body.get("done") is True, body
PY
}

restore_everything() {
    rc=$?
    trap - EXIT INT TERM
    if [ "$RESTORED" -eq 0 ]; then
        section "AUTOMATIC RESTORE"
        stop_secondary
        warm_primary_production
        if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then
            sudo systemctl start ai-bridge-analysis.timer >/dev/null 2>&1 || true
        fi
        if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
            systemctl --user start hermes-gateway.service >/dev/null 2>&1 || true
        fi
        RESTORED=1
    fi
    exit "$rc"
}
trap restore_everything EXIT INT TERM

[ -x "$PYTHON" ] || { say "FAIL: production Python missing: $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -d "$MODELS_DIR" ] || { say "FAIL: Ollama models directory missing: $MODELS_DIR"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: primary ollama.service is not active"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service is not active"; exit 1; }
command -v ollama >/dev/null 2>&1 || { say "FAIL: ollama executable not found"; exit 1; }
OLLAMA_BIN="$(command -v ollama)"

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg=yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
m=cfg.get("model") or {}
if isinstance(m,str): model=m.strip()
elif isinstance(m,dict): model=str(m.get("default") or m.get("model") or "").strip()
else: model=""
if not model:
    for item in cfg.get("custom_providers") or []:
        if isinstance(item,dict) and item.get("model"):
            model=str(item["model"]).strip(); break
print(model)
PY
)"
[ -n "$MODEL" ] || { say "FAIL: could not resolve Hermes model"; exit 1; }

HERMES_STATE="$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
[ "$HERMES_STATE" = "active" ] && HERMES_WAS_ACTIVE=1
[ "$TIMER_STATE" = "active" ] && TIMER_WAS_ACTIVE=1

section "STAGE-7 DUAL OLLAMA RUNNER BENCHMARK"
say "model:                $MODEL"
say "context per runner:   $CONTEXT"
say "tokens per request:   $NUM_PREDICT"
say "primary:              $PRIMARY"
say "secondary:            $SECONDARY"
say "secondary MemoryMax:  $SECONDARY_MEMORY_MAX"
say "MemAvailable before:  $(mem_available_gib) GiB"
say "Temporary benchmark only; no production routing changes are made."

section "PAUSE LIVE CLIENTS"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl stop ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user stop hermes-gateway.service || true; fi
say "Hermes:          $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer:  $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"

"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status",timeout=2) as r:
    s=json.load(r)
assert s.get("active_count")==0 and s.get("queued_count")==0,s
print("PASS: AI Gateway idle")
PY

run_pair() {
    local mode="$1"
    local url_a="$2"
    local url_b="$3"
    local out="$4"
    "$PYTHON" - "$MODEL" "$CONTEXT" "$NUM_PREDICT" "$mode" "$url_a" "$url_b" "$out" <<'PY'
from __future__ import annotations
import json, sys, threading, time, urllib.request
from pathlib import Path

model=sys.argv[1]
num_ctx=int(sys.argv[2])
num_predict=int(sys.argv[3])
mode=sys.argv[4]
urls=[sys.argv[5],sys.argv[6]]
out=Path(sys.argv[7])
prompt=(
    "Wygeneruj zwartą techniczną odpowiedź po polsku o lokalnym serwerze AI. "
    "Nie używaj narzędzi i kontynuuj do limitu odpowiedzi."
)
results=[None,None]
errors=[]
start_evt=threading.Event()
stop_evt=threading.Event()
samples=[]

def sample_mem():
    while not stop_evt.is_set():
        mem=None
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):
                    mem=int(line.split()[1]); break
        except Exception:
            pass
        runner_pids=[]
        runner_rss=0
        for p in Path('/proc').iterdir():
            if not p.name.isdigit(): continue
            try:
                cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='ignore')
            except Exception:
                continue
            if 'llama-server' not in cmd: continue
            runner_pids.append(int(p.name))
            try:
                for line in (p/'status').read_text().splitlines():
                    if line.startswith('VmRSS:'):
                        runner_rss += int(line.split()[1]); break
            except Exception:
                pass
        samples.append({"t":time.monotonic(),"mem_available_kb":mem,"runner_rss_kb":runner_rss,"runner_pids":runner_pids})
        time.sleep(0.1)

def worker(i):
    payload=json.dumps({
        "model":model,
        "messages":[{"role":"user","content":prompt}],
        "stream":False,
        "think":False,
        "options":{"temperature":0,"num_predict":num_predict,"num_ctx":num_ctx},
    }).encode()
    req=urllib.request.Request(urls[i]+"/api/chat",data=payload,headers={"Content-Type":"application/json"})
    start_evt.wait()
    t0=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=900) as r:
            body=json.load(r)
        results[i]={
            "wall_s":time.monotonic()-t0,
            "eval_count":body.get("eval_count"),
            "eval_duration_ns":body.get("eval_duration"),
            "prompt_eval_count":body.get("prompt_eval_count"),
            "total_duration_ns":body.get("total_duration"),
            "done":body.get("done"),
            "url":urls[i],
        }
    except Exception as exc:
        errors.append(f"worker {i}: {exc!r}")

sampler=threading.Thread(target=sample_mem,daemon=True); sampler.start()
threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(2)]
for t in threads: t.start()
wall0=time.monotonic(); start_evt.set()
for t in threads: t.join()
wall=time.monotonic()-wall0
stop_evt.set(); sampler.join(timeout=2)
if errors:
    raise SystemExit("FAIL: "+"; ".join(errors))
if any(r is None or not r.get('done') for r in results):
    raise SystemExit(f"FAIL: incomplete results {results}")
min_mem=min((s['mem_available_kb'] for s in samples if s['mem_available_kb'] is not None),default=None)
max_rss=max((s['runner_rss_kb'] for s in samples),default=0)
total_eval=sum(int(r.get('eval_count') or 0) for r in results)
summary={
    "mode":mode,
    "wall_pair_s":wall,
    "aggregate_eval_tokens_per_s": total_eval/wall if wall else None,
    "total_eval_tokens":total_eval,
    "requests":results,
    "min_mem_available_kb":min_mem,
    "max_runner_rss_kb":max_rss,
    "sample_count":len(samples),
}
out.write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
PY
}

section "BASELINE: ONE 32K RUNNER, TWO REQUESTS"
"$PYTHON" - "$MODEL" "$CONTEXT" <<'PY'
import json,sys,urllib.request
payload=json.dumps({
  "model":sys.argv[1],"messages":[{"role":"user","content":"Odpowiedz dokładnie: WARM"}],
  "stream":False,"think":False,
  "options":{"temperature":0,"num_predict":4,"num_ctx":int(sys.argv[2])}
}).encode()
req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=payload,headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=600) as r:
    body=json.load(r)
assert body.get("done") is True,body
print("PASS: primary 32k warm")
PY
PRIMARY_CMD="$(ps -eo args | grep '[l]lama-server' | head -n 1 || true)"
case " $PRIMARY_CMD " in
  *" -c ${CONTEXT} "*" -np 1 "*) say "PASS: primary runner is -c $CONTEXT -np 1" ;;
  *) say "FAIL: primary runner is not 32k/np1"; say "$PRIMARY_CMD"; exit 1 ;;
esac
run_pair "single-runner" "$PRIMARY" "$PRIMARY" "/tmp/ai-gateway-stage7-single.json"

section "START ISOLATED SECONDARY OLLAMA"
cat <<EOF | sudo tee "$SECONDARY_UNIT_FILE" >/dev/null
[Unit]
Description=Temporary Stage-7 secondary Ollama benchmark instance
After=network.target

[Service]
Type=simple
User=ollama
Group=ollama
Environment="OLLAMA_HOST=127.0.0.1:11436"
Environment="OLLAMA_MODELS=$MODELS_DIR"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_CONTEXT_LENGTH=$CONTEXT"
Environment="OLLAMA_VULKAN=1"
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_NOPRUNE=1"
Environment="OLLAMA_NO_CLOUD=1"
MemoryAccounting=yes
MemoryMax=$SECONDARY_MEMORY_MAX
MemorySwapMax=0
OOMPolicy=stop
ExecStart=$OLLAMA_BIN serve
Restart=no
EOF
sudo systemctl daemon-reload
sudo systemctl start "$SECONDARY_UNIT"
SECONDARY_STARTED=1

for _ in $(seq 1 120); do
    if "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11436/api/tags",timeout=1) as r: assert r.status==200
PY
    then break; fi
    if [ "$(systemctl is-active "$SECONDARY_UNIT" 2>/dev/null || true)" = "failed" ]; then break; fi
    sleep 0.5
done
[ "$(systemctl is-active "$SECONDARY_UNIT" 2>/dev/null || true)" = "active" ] || {
    say "FAIL: secondary Ollama service did not stay active"
    sudo systemctl --no-pager --full status "$SECONDARY_UNIT" || true
    exit 1
}
say "PASS: secondary Ollama listening on 11436"

section "LOAD SECOND 32K QWEN RUNNER"
if ! "$PYTHON" - "$MODEL" "$CONTEXT" <<'PY'
import json,sys,urllib.request
payload=json.dumps({
  "model":sys.argv[1],"messages":[{"role":"user","content":"Odpowiedz dokładnie: WARM2"}],
  "stream":False,"think":False,
  "options":{"temperature":0,"num_predict":4,"num_ctx":int(sys.argv[2])}
}).encode()
req=urllib.request.Request("http://127.0.0.1:11436/api/chat",data=payload,headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=600) as r:
    body=json.load(r)
assert body.get("done") is True,body
print("PASS: secondary 32k model warm")
PY
then
    say "FAIL: second Qwen runner could not be loaded safely"
    sudo journalctl -u "$SECONDARY_UNIT" -n 60 --no-pager || true
    exit 1
fi

RUNNER_COUNT="$(ps -eo args | grep -c '[l]lama-server' || true)"
say "llama-server runner count: $RUNNER_COUNT"
ps -eo pid,args | grep '[l]lama-server' || true
[ "$RUNNER_COUNT" -ge 2 ] || { say "FAIL: expected two independent llama-server runners"; exit 1; }

MEM_AFTER_LOAD="$(mem_available_gib)"
say "MemAvailable after second load: $MEM_AFTER_LOAD GiB"
"$PYTHON" - "$MEM_AFTER_LOAD" <<'PY'
import sys
v=float(sys.argv[1])
if v < 8.0:
    raise SystemExit(f"FAIL: only {v:.2f} GiB MemAvailable after second runner load; refusing contention benchmark")
print(f"PASS: memory headroom after dual load = {v:.2f} GiB")
PY

section "DUAL RUNNER: ONE REQUEST PER OLLAMA INSTANCE"
run_pair "dual-runner" "$PRIMARY" "$SECONDARY" "/tmp/ai-gateway-stage7-dual.json"

section "COMPARISON"
"$PYTHON" - /tmp/ai-gateway-stage7-single.json /tmp/ai-gateway-stage7-dual.json "$RESULT_JSON" <<'PY'
import json,sys
from pathlib import Path
single=json.loads(Path(sys.argv[1]).read_text())
dual=json.loads(Path(sys.argv[2]).read_text())
sw=float(single['wall_pair_s']); dw=float(dual['wall_pair_s'])
sa=float(single['aggregate_eval_tokens_per_s']); da=float(dual['aggregate_eval_tokens_per_s'])
min_mem=(dual.get('min_mem_available_kb') or 0)/1024/1024
summary={
  'single':single,'dual':dual,
  'pair_wall_speedup':sw/dw if dw else None,
  'aggregate_throughput_gain_pct':((da/sa)-1)*100 if sa else None,
  'dual_min_mem_available_gib':min_mem,
  'recommended_for_further_testing': bool(dw < sw*0.85 and min_mem >= 8.0),
}
Path(sys.argv[3]).write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(f"single 32k pair wall: {sw:.2f}s")
print(f"dual   32k pair wall: {dw:.2f}s")
print(f"pair wall speedup:    {summary['pair_wall_speedup']:.2f}x")
print(f"single aggregate:     {sa:.2f} eval tok/s")
print(f"dual aggregate:       {da:.2f} eval tok/s")
print(f"throughput gain:      {summary['aggregate_throughput_gain_pct']:.1f}%")
print(f"dual min MemAvailable:{min_mem:.2f} GiB")
print(f"candidate:             {summary['recommended_for_further_testing']}")
print(f"full JSON:             {sys.argv[3]}")
PY

section "RESTORE PRODUCTION STATE"
stop_secondary
warm_primary_production
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi
RESTORED=1

section "POSTCHECK"
say "ollama:         $(systemctl is-active ollama.service 2>/dev/null || true)"
say "gateway:        $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
say "runner(s):"
ps -eo pid,args | grep '[l]lama-server' || true
"$PYTHON" - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health",timeout=2) as r:
    h=json.load(r)
assert h.get('status')=='ok' and h.get('ollama')=='ok',h
with urllib.request.urlopen("http://127.0.0.1:11435/status",timeout=2) as r:
    s=json.load(r)
assert s.get('active_count')==0 and s.get('queued_count')==0,s
print("PASS: gateway healthy and idle")
PY

say
say "PASS: stage-7 reversible single-runner vs dual-runner benchmark completed"
say "No permanent dual-runner routing or service was installed."
