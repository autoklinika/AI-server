#!/usr/bin/env bash
set -euo pipefail

CURRENT="/opt/ai-platform/current"
ENV_FILE="${AI_BRIDGE_ENV_FILE:-/etc/ai-bridge/ai-bridge.env}"

say(){ printf '%s\n' "$*"; }
fail(){ say "FAIL: $*" >&2; exit 1; }

[[ -f "$CURRENT/RELEASE" ]] || fail "active release stamp missing"
grep -qx 'stage=D' "$CURRENT/RELEASE" || fail "active release is not Stage D"
python3 "$(dirname "$0")/validate_release_metadata.py" "$CURRENT"
sudo test -f "$ENV_FILE" || fail "AI Bridge env missing: $ENV_FILE"

POLICY="$(sudo sed -n 's/^AI_BRIDGE_ANALYSIS_USE_GATEWAY=//p' "$ENV_FILE" | tail -1)"
[[ "$POLICY" == "true" ]] || fail "AI_BRIDGE_ANALYSIS_USE_GATEWAY is not true: $POLICY"

MODEL="$(sudo sed -n 's/^AI_BRIDGE_OLLAMA_MODEL=//p' "$ENV_FILE" | tail -1)"
if [[ -z "$MODEL" ]]; then
  ACTIVE_PYTHON="$CURRENT/services/ai-bridge/.venv/bin/python"
  [[ -x "$ACTIVE_PYTHON" ]] || fail "active release Python missing: $ACTIVE_PYTHON"
  MODEL="$(
    PYTHONPATH="$CURRENT/services/ai-bridge/src" "$ACTIVE_PYTHON" - <<'PY'
from ai_bridge.settings import Settings
print(Settings.model_fields["ollama_model"].default)
PY
  )"
  [[ -n "$MODEL" ]] || fail "could not resolve default Ollama model from active release"
  say "AI_BRIDGE_OLLAMA_MODEL not set in env; using active release default: $MODEL"
fi

GATEWAY_URL="$(sudo sed -n 's/^AI_BRIDGE_GATEWAY_URL=//p' "$ENV_FILE" | tail -1)"
[[ -n "$GATEWAY_URL" ]] || GATEWAY_URL="http://127.0.0.1:11435"
GATEWAY_URL="${GATEWAY_URL%/}"

BRIDGE_HOST="$(
  systemctl show ai-bridge.service -p Environment --value \
    | tr ' ' '\n' \
    | sed -n 's/^AI_BRIDGE_HOST=//p' \
    | tail -1
)"
case "$BRIDGE_HOST" in
  ""|"0.0.0.0"|"::"|"[::]") BRIDGE_HOST="127.0.0.1" ;;
esac
BRIDGE_URL="http://${BRIDGE_HOST}:8080"

echo "===== D.6 WVC/GATEWAY VALIDATION ====="
say "release=$(readlink -f "$CURRENT")"
say "bridge_url=$BRIDGE_URL"
say "gateway_url=$GATEWAY_URL"
say "model=$MODEL"
say "analysis_use_gateway=$POLICY"

echo
echo "===== CANONICAL ANALYSIS SYSTEMD ====="
EFFECTIVE="$(systemctl cat ai-bridge-analysis.service)"
for stale in \
  '/opt/ai-bridge/src' \
  '/opt/ai-bridge/.venv/bin/ai-bridge-analyze-ventilation' \
  'AI_BRIDGE_OLLAMA_URL=http://127.0.0.1:11435/clients/ventilation'
do
  if grep -Fq "$stale" <<<"$EFFECTIVE"; then
    fail "obsolete analysis override remains: $stale"
  fi
done
systemctl show ai-bridge-analysis.service -p WorkingDirectory -p ExecStart -p DropInPaths

echo
echo "===== AI BRIDGE HEALTH + WVC INGEST CONTRACT ====="
curl -fsS "$BRIDGE_URL/health" >/dev/null
python3 - "$BRIDGE_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/openapi.json", timeout=5) as response:
    data = json.load(response)

path = "/api/v1/ventilation/telemetry/batches"
methods = data.get("paths", {}).get(path, {})
if "post" not in methods:
    raise SystemExit(f"missing POST {path}")
print(f"PASS: AI Bridge exposes POST {path}")
PY

echo
echo "===== RESOURCE MANAGER PRECHECK ====="
python3 - "$GATEWAY_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/health", timeout=5) as response:
    health = json.load(response)
if health.get("status") != "ok":
    raise SystemExit(f"gateway health failed: {health}")

with urllib.request.urlopen(base + "/status", timeout=5) as response:
    status = json.load(response)
leases = status.get("resource_leases") or {}
counts = (
    status.get("active_count"),
    status.get("queued_count"),
    leases.get("lease_count"),
)
if counts != (0, 0, 0):
    raise SystemExit(
        f"Resource Manager not idle: active={counts[0]} queued={counts[1]} leases={counts[2]}"
    )
print("PASS: Resource Manager healthy and idle 0/0/0")
PY

echo
echo "===== REAL VENTILATION -> GATEWAY -> QWEN ====="
python3 - "$GATEWAY_URL" "$MODEL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
model = sys.argv[2]
payload = json.dumps(
    {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "To test infrastruktury. Zwróć wyłącznie JSON zgodny ze schematem."
                ),
            }
        ],
        "stream": False,
        "think": False,
        "format": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "options": {"temperature": 0},
    }
).encode("utf-8")

request = urllib.request.Request(
    base + "/clients/ventilation/api/chat",
    data=payload,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-AI-Priority": "10",
        "X-AI-Source": "ventilation-d6-validation",
    },
)
with urllib.request.urlopen(request, timeout=300) as response:
    body = json.load(response)
    priority = response.headers.get("X-AI-Gateway-Priority")
    job_id = response.headers.get("X-AI-Gateway-Job-Id")
    wait_ms = response.headers.get("X-AI-Gateway-Wait-Ms")
    v2_job_id = response.headers.get("X-AI-Job-Id")
    request_id = response.headers.get("X-AI-Request-Id")

if body.get("done") is not True:
    raise SystemExit("Qwen response not complete")
if int(body.get("prompt_eval_count") or 0) <= 0:
    raise SystemExit("Qwen did not evaluate prompt")
if priority != "10":
    raise SystemExit(f"unexpected gateway priority: {priority}")
if not job_id:
    raise SystemExit("missing X-AI-Gateway-Job-Id")
if wait_ms is None:
    raise SystemExit("missing X-AI-Gateway-Wait-Ms")

with urllib.request.urlopen(base + "/status", timeout=5) as response:
    status = json.load(response)
matching = [job for job in status.get("recent_jobs", []) if job.get("job_id") == v2_job_id]
if not request_id or len(matching) != 1:
    raise SystemExit("missing D.6 WVC job correlation")
job = matching[0]
if (job.get("request_id") != request_id or job.get("domain") != "wvc"
        or job.get("capability") != "reasoning" or job.get("state") != "completed"
        or job.get("priority_class") != "infrastructure"
        or job.get("assigned_provider") != "ollama-local" or not job.get("assigned_node")):
    raise SystemExit("unexpected D.6 WVC job metadata")

print(
    "PASS: ventilation request executed through Gateway/Qwen "
    f"job={job_id} priority={priority} wait_ms={wait_ms}"
)
PY

echo
echo "===== RESOURCE MANAGER POSTCHECK ====="
python3 - "$GATEWAY_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(base + "/status", timeout=5) as response:
    status = json.load(response)
leases = status.get("resource_leases") or {}
counts = (
    status.get("active_count"),
    status.get("queued_count"),
    leases.get("lease_count"),
)
if counts != (0, 0, 0):
    raise SystemExit(
        f"Resource Manager not idle after smoke: active={counts[0]} queued={counts[1]} leases={counts[2]}"
    )
print("PASS: Resource Manager returned to idle 0/0/0")
PY

echo
echo "D.6 WVC/GATEWAY RUNTIME VALIDATION: PASS"
say "Live CM5 telemetry growth was not tested; record connected/disconnected state separately."
