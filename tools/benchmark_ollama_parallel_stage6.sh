#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/AI-server"
HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
OLLAMA_DROPIN_DIR="/etc/systemd/system/ollama.service.d"
BENCH_DROPIN="${OLLAMA_DROPIN_DIR}/99-ai-gateway-benchmark.conf"
BENCH_DROPIN_BACKUP="/tmp/99-ai-gateway-benchmark.conf.pre-stage6.$$.bak"
RESULT_JSON="/tmp/ai-gateway-stage6-benchmark.json"
OLLAMA_URL="http://127.0.0.1:11434"
GATEWAY_URL="http://127.0.0.1:11435"

HAD_BENCH_DROPIN=0
HERMES_WAS_ACTIVE=0
TIMER_WAS_ACTIVE=0
RESTORED=0

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

if [ -f "$BENCH_DROPIN" ]; then
    HAD_BENCH_DROPIN=1
fi

restore_everything() {
    rc=$?
    trap - EXIT INT TERM
    if [ "$RESTORED" -eq 0 ]; then
        section "RESTORE ORIGINAL OLLAMA + SERVICES"
        if [ "$HAD_BENCH_DROPIN" -eq 1 ] && [ -f "$BENCH_DROPIN_BACKUP" ]; then
            sudo install -D -m 0644 "$BENCH_DROPIN_BACKUP" "$BENCH_DROPIN" || true
            say "restored pre-existing benchmark drop-in"
        else
            sudo rm -f "$BENCH_DROPIN" || true
            say "removed temporary benchmark drop-in"
        fi
        sudo systemctl daemon-reload || true
        sudo systemctl restart ollama.service || true

        # Wait for Ollama and leave the normal model warm again.
        for _ in $(seq 1 120); do
            if "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as r:
    assert r.status == 200
PY
            then
                break
            fi
            sleep 0.5
        done

        if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then
            sudo systemctl start ai-bridge-analysis.timer >/dev/null 2>&1 || true
        fi
        if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
            systemctl --user start hermes-gateway.service >/dev/null 2>&1 || true
        fi
        RESTORED=1
    fi
    rm -f "$BENCH_DROPIN_BACKUP" >/dev/null 2>&1 || true
    exit "$rc"
}
trap restore_everything EXIT INT TERM

[ -d "$ROOT/.git" ] || { say "FAIL: repo missing at $ROOT"; exit 1; }
[ -x "$PYTHON" ] || { say "FAIL: Python missing: $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ "$(systemctl is-active ollama.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ollama.service not active"; exit 1; }
[ "$(systemctl is-active ai-gateway.service 2>/dev/null || true)" = "active" ] || { say "FAIL: ai-gateway.service not active"; exit 1; }

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
m = cfg.get("model") or {}
if isinstance(m, str):
    model = m.strip()
elif isinstance(m, dict):
    model = str(m.get("default") or m.get("model") or "").strip()
else:
    model = ""
if not model:
    for item in cfg.get("custom_providers") or []:
        if isinstance(item, dict) and item.get("model"):
            model = str(item["model"]).strip(); break
print(model)
PY
)"
[ -n "$MODEL" ] || { say "FAIL: could not resolve Hermes model"; exit 1; }

HERMES_STATE="$(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
[ "$HERMES_STATE" = "active" ] && HERMES_WAS_ACTIVE=1
[ "$TIMER_STATE" = "active" ] && TIMER_WAS_ACTIVE=1

section "STAGE-6 OLLAMA PARALLELISM BENCHMARK"
say "model:             $MODEL"
say "Hermes before:     $HERMES_STATE"
say "analysis timer:    $TIMER_STATE"
say "gateway:           $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
say "ollama:            $(systemctl is-active ollama.service 2>/dev/null || true)"
say "result JSON:       $RESULT_JSON"
say "NOTE: benchmark temporarily pauses Hermes and the analysis timer."
say "NOTE: original Ollama configuration is restored automatically at exit."

section "PRECHECK CURRENT RUNNER"
ps -eo pid,args | grep '[l]lama-server' || true
systemctl show ollama.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^OLLAMA_' || true

if [ "$HAD_BENCH_DROPIN" -eq 1 ]; then
    cp -a "$BENCH_DROPIN" "$BENCH_DROPIN_BACKUP"
    say "saved existing $BENCH_DROPIN"
fi

section "PAUSE LIVE CLIENTS"
if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then
    sudo systemctl stop ai-bridge-analysis.timer
fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then
    systemctl --user stop hermes-gateway.service
fi
say "Hermes:          $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer:  $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"

# Gateway must be idle before direct Ollama testing.
"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s = json.load(r)
assert s.get("active_count") == 0 and s.get("queued_count") == 0, s
print("PASS: AI Gateway idle")
PY

run_variant() {
    local parallel="$1"
    local out="/tmp/ai-gateway-stage6-np${parallel}.json"
    section "BENCHMARK OLLAMA_NUM_PARALLEL=${parallel}"

    sudo mkdir -p "$OLLAMA_DROPIN_DIR"
    printf '[Service]\nEnvironment="OLLAMA_NUM_PARALLEL=%s"\n' "$parallel" \
      | sudo tee "$BENCH_DROPIN" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl restart ollama.service

    for _ in $(seq 1 120); do
        if "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1) as r:
    assert r.status == 200
PY
        then break; fi
        sleep 0.5
    done

    # Warm/load the exact production Hermes model first so load time does not skew the pair test.
    "$PYTHON" - "$MODEL" <<'PY'
import json, sys, urllib.request
model=sys.argv[1]
payload=json.dumps({
    "model": model,
    "messages":[{"role":"user","content":"Odpowiedz dokładnie: WARM"}],
    "stream":False,
    "think":False,
    "options":{"temperature":0,"num_predict":8},
}).encode()
req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=payload,headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=300) as r:
    body=json.load(r)
assert body.get("done") is True, body
print("PASS: model warm")
PY

    say "runner command:"
    ps -eo pid,args | grep '[l]lama-server' || true

    # The benchmark launches two identical clients simultaneously. At np=1 one is internally
    # queued by Ollama; at np=2 the runner should admit both and report -np 2.
    "$PYTHON" - "$MODEL" "$parallel" "$out" <<'PY'
from __future__ import annotations
import json, os, sys, threading, time, urllib.request
from pathlib import Path

model=sys.argv[1]
parallel=int(sys.argv[2])
out=Path(sys.argv[3])
URL="http://127.0.0.1:11434/api/chat"
PROMPT=(
    "Wygeneruj zwartą techniczną odpowiedź po polsku o architekturze lokalnego serwera AI. "
    "Nie używaj narzędzi. Kontynuuj do osiągnięcia limitu odpowiedzi."
)

results=[None,None]
errors=[]
start_evt=threading.Event()
stop_sampler=threading.Event()
samples=[]

def mem_sample():
    while not stop_sampler.is_set():
        mem_avail_kb=None
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):
                    mem_avail_kb=int(line.split()[1]); break
        except Exception:
            pass
        rss_kb=0
        runner_pids=[]
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():
                continue
            try:
                cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='ignore')
            except Exception:
                continue
            if 'llama-server' not in cmd:
                continue
            runner_pids.append(int(p.name))
            try:
                for line in (p/'status').read_text().splitlines():
                    if line.startswith('VmRSS:'):
                        rss_kb += int(line.split()[1]); break
            except Exception:
                pass
        samples.append({"t":time.monotonic(),"mem_available_kb":mem_avail_kb,"runner_rss_kb":rss_kb,"runner_pids":runner_pids})
        time.sleep(0.1)

def worker(i):
    payload=json.dumps({
        "model":model,
        "messages":[{"role":"user","content":PROMPT}],
        "stream":False,
        "think":False,
        "options":{"temperature":0,"num_predict":192},
    }).encode()
    req=urllib.request.Request(URL,data=payload,headers={"Content-Type":"application/json"})
    start_evt.wait()
    t0=time.monotonic()
    try:
        with urllib.request.urlopen(req,timeout=600) as r:
            body=json.load(r)
        t1=time.monotonic()
        results[i]={
            "wall_s":t1-t0,
            "eval_count":body.get("eval_count"),
            "eval_duration_ns":body.get("eval_duration"),
            "prompt_eval_count":body.get("prompt_eval_count"),
            "prompt_eval_duration_ns":body.get("prompt_eval_duration"),
            "total_duration_ns":body.get("total_duration"),
            "load_duration_ns":body.get("load_duration"),
            "done":body.get("done"),
        }
    except Exception as exc:
        errors.append(f"worker {i}: {exc!r}")

sampler=threading.Thread(target=mem_sample,daemon=True); sampler.start()
threads=[threading.Thread(target=worker,args=(i,),daemon=True) for i in range(2)]
for t in threads: t.start()
wall0=time.monotonic(); start_evt.set()
for t in threads: t.join()
wall1=time.monotonic(); stop_sampler.set(); sampler.join(timeout=2)

if errors:
    raise SystemExit("FAIL: "+"; ".join(errors))
if any(r is None or not r.get('done') for r in results):
    raise SystemExit(f"FAIL: incomplete results {results}")

min_mem=min((s['mem_available_kb'] for s in samples if s['mem_available_kb'] is not None), default=None)
max_rss=max((s['runner_rss_kb'] for s in samples), default=0)
total_eval=sum(int(r.get('eval_count') or 0) for r in results)
wall=wall1-wall0
summary={
    "parallel":parallel,
    "wall_pair_s":wall,
    "total_eval_tokens":total_eval,
    "aggregate_eval_tokens_per_s": (total_eval/wall if wall else None),
    "requests":results,
    "min_mem_available_kb":min_mem,
    "max_llama_runner_rss_kb":max_rss,
    "sample_count":len(samples),
}
out.write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))
PY

    # Assert the runner was actually configured for the requested parallel count.
    RUNNER_CMD="$(ps -eo args | grep '[l]lama-server' | head -n 1 || true)"
    case " $RUNNER_CMD " in
      *" -np ${parallel} "*) say "PASS: runner confirmed -np ${parallel}" ;;
      *) say "FAIL: runner does not show -np ${parallel}"; say "$RUNNER_CMD"; exit 1 ;;
    esac
    cp "$out" "/tmp/ai-gateway-stage6-np${parallel}.json"
}

run_variant 1
run_variant 2

section "COMPARISON"
"$PYTHON" - /tmp/ai-gateway-stage6-np1.json /tmp/ai-gateway-stage6-np2.json "$RESULT_JSON" <<'PY'
import json, sys
from pathlib import Path
p1=json.loads(Path(sys.argv[1]).read_text())
p2=json.loads(Path(sys.argv[2]).read_text())
wall1=float(p1['wall_pair_s']); wall2=float(p2['wall_pair_s'])
agg1=float(p1['aggregate_eval_tokens_per_s']); agg2=float(p2['aggregate_eval_tokens_per_s'])
summary={
  'np1':p1,
  'np2':p2,
  'pair_wall_speedup': wall1/wall2 if wall2 else None,
  'aggregate_throughput_gain_pct': ((agg2/agg1)-1)*100 if agg1 else None,
  'np2_vs_np1_min_mem_delta_gib': ((p1.get('min_mem_available_kb') or 0)-(p2.get('min_mem_available_kb') or 0))/1024/1024,
  'np2_vs_np1_runner_rss_delta_gib': ((p2.get('max_llama_runner_rss_kb') or 0)-(p1.get('max_llama_runner_rss_kb') or 0))/1024/1024,
}
Path(sys.argv[3]).write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(f"np=1 pair wall: {wall1:.2f}s")
print(f"np=2 pair wall: {wall2:.2f}s")
print(f"pair speedup:   {summary['pair_wall_speedup']:.2f}x")
print(f"np=1 aggregate: {agg1:.2f} eval tok/s")
print(f"np=2 aggregate: {agg2:.2f} eval tok/s")
print(f"throughput gain: {summary['aggregate_throughput_gain_pct']:.1f}%")
print(f"extra memory pressure (MemAvailable delta): {summary['np2_vs_np1_min_mem_delta_gib']:.2f} GiB")
print(f"runner RSS delta: {summary['np2_vs_np1_runner_rss_delta_gib']:.2f} GiB")
print(f"full JSON: {sys.argv[3]}")
PY

section "RESTORE NOW"
# Explicit restore here; EXIT trap remains a safety net for earlier failures.
if [ "$HAD_BENCH_DROPIN" -eq 1 ] && [ -f "$BENCH_DROPIN_BACKUP" ]; then
    sudo install -D -m 0644 "$BENCH_DROPIN_BACKUP" "$BENCH_DROPIN"
else
    sudo rm -f "$BENCH_DROPIN"
fi
sudo systemctl daemon-reload
sudo systemctl restart ollama.service
for _ in $(seq 1 120); do
    if "$PYTHON" - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",timeout=1) as r: assert r.status==200
PY
    then break; fi
    sleep 0.5
done

# Warm normal model after restoring original settings.
"$PYTHON" - "$MODEL" <<'PY' >/dev/null
import json,sys,urllib.request
payload=json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":"Odpowiedz: OK"}],"stream":False,"think":False,"options":{"num_predict":4,"temperature":0}}).encode()
req=urllib.request.Request("http://127.0.0.1:11434/api/chat",data=payload,headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=300) as r: json.load(r)
PY

if [ "$TIMER_WAS_ACTIVE" -eq 1 ]; then sudo systemctl start ai-bridge-analysis.timer; fi
if [ "$HERMES_WAS_ACTIVE" -eq 1 ]; then systemctl --user start hermes-gateway.service; fi
RESTORED=1
rm -f "$BENCH_DROPIN_BACKUP" >/dev/null 2>&1 || true

section "POSTCHECK"
say "ollama:          $(systemctl is-active ollama.service 2>/dev/null || true)"
say "gateway:         $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
say "Hermes:          $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer:  $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"
"$PYTHON" - <<'PY'
import json,urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health",timeout=2) as r:
    h=json.load(r)
assert h.get('status')=='ok' and h.get('ollama')=='ok',h
with urllib.request.urlopen("http://127.0.0.1:11435/status",timeout=2) as r:
    s=json.load(r)
assert s.get('active_count')==0 and s.get('queued_count')==0,s
print("PASS: gateway healthy and idle after restore")
PY

say
say "PASS: stage-6 reversible Ollama np=1 vs np=2 benchmark completed"
say "No permanent parallelism change was made."
