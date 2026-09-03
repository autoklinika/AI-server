#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"
PYTHON="/opt/ai-bridge/.venv/bin/python"
MODEL=""

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$PYTHON" ] || { say "FAIL: production Python missing: $PYTHON"; exit 1; }
[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }

MODEL="$($HERMES_PYTHON - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8')) or {}
m = cfg.get('model') or {}
if isinstance(m, str):
    model = m.strip()
elif isinstance(m, dict):
    model = str(m.get('default') or m.get('model') or '').strip()
else:
    model = ''
if not model:
    for item in cfg.get('custom_providers') or []:
        if isinstance(item, dict) and item.get('model'):
            model = str(item['model']).strip(); break
print(model)
PY
)"
[ -n "$MODEL" ] || { say "FAIL: could not resolve Hermes model"; exit 1; }

section "STAGE-6B OLLAMA PARALLELISM DIAGNOSIS"
say "model: $MODEL"
say "ollama version: $(ollama --version 2>&1 | head -n 1 || true)"

section "SERVICE HEALTH AFTER STAGE-6 RESTORE"
say "ollama:         $(systemctl is-active ollama.service 2>/dev/null || true)"
say "gateway:        $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
say "Hermes:         $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "analysis timer: $(systemctl is-active ai-bridge-analysis.timer 2>/dev/null || true)"

section "EFFECTIVE OLLAMA ENVIRONMENT"
systemctl show ollama.service -p Environment --value 2>/dev/null | tr ' ' '\n' | grep '^OLLAMA_' | sort || true

section "MODEL METADATA"
"$PYTHON" - "$MODEL" <<'PY'
import json, sys, urllib.request
model = sys.argv[1]
payload = json.dumps({'model': model}).encode('utf-8')
req = urllib.request.Request(
    'http://127.0.0.1:11434/api/show',
    data=payload,
    method='POST',
    headers={'Content-Type':'application/json'},
)
with urllib.request.urlopen(req, timeout=10) as r:
    data = json.load(r)

details = data.get('details') or {}
model_info = data.get('model_info') or {}
interesting = {
    'family': details.get('family'),
    'families': details.get('families'),
    'parameter_size': details.get('parameter_size'),
    'quantization_level': details.get('quantization_level'),
    'format': details.get('format'),
}
# Ollama exposes architecture-specific keys in model_info; print only safe structural metadata.
arch_keys = {k:v for k,v in model_info.items() if k in {
    'general.architecture', 'general.name', 'general.parameter_count',
    'qwen35.context_length', 'qwen3.context_length', 'qwen3next.context_length'
}}
print(json.dumps({'details': interesting, 'model_info': arch_keys}, indent=2, ensure_ascii=False))
PY

section "CURRENT RUNNER"
ps -eo pid,args | grep '[l]lama-server' || true

section "RECENT OLLAMA PARALLELISM LOGS"
sudo journalctl -u ollama.service --since '-30 min' --no-pager \
  | grep -Ei 'parallel|architecture|num_parallel|qwen|runner' \
  | tail -n 120 || true

section "INTERPRETATION"
"$PYTHON" - "$MODEL" <<'PY'
import json, sys, urllib.request
model = sys.argv[1]
payload = json.dumps({'model': model}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:11434/api/show', data=payload, method='POST', headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    data = json.load(r)
details = data.get('details') or {}
info = data.get('model_info') or {}
family = str(details.get('family') or info.get('general.architecture') or '').lower()
blocked = {'mllama','qwen3vl','qwen3vlmoe','qwen35','qwen35moe','qwen3next','lfm2','lfm2moe','nemotron_h','nemotron_h_moe','nemotron_h_omni'}
print(f'effective family/architecture: {family or "unknown"}')
if family in blocked:
    print('PASS: diagnosis confirmed — current Ollama intentionally forces this architecture to num_parallel=1')
    print('NEXT: do not force -np 2 inside one runner; benchmark two isolated np=1 runners instead')
else:
    print('NOTE: architecture is not on the current Ollama forced-serial list')
    print('NEXT: inspect service env precedence / version-specific scheduler behavior before changing production')
PY

section "FINAL HEALTH"
"$PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:11435/health', timeout=3) as r:
    h=json.load(r)
print(json.dumps(h, indent=2))
PY

say
say "PASS: stage-6B read-only diagnosis completed"
