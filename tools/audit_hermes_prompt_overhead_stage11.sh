#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="/srv/ai-data/hermes"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_DB="${HERMES_HOME}/state.db"
HERMES_SESSIONS="${HERMES_HOME}/sessions/sessions.json"
HERMES_PYTHON="${HERMES_HOME}/hermes-agent/venv/bin/python"

say() { printf '%s\n' "$*"; }
section() { printf '\n===== %s =====\n' "$1"; }

[ -x "$HERMES_PYTHON" ] || { say "FAIL: Hermes Python missing: $HERMES_PYTHON"; exit 1; }
[ -r "$HERMES_CONFIG" ] || { say "FAIL: Hermes config missing: $HERMES_CONFIG"; exit 1; }
[ -r "$HERMES_DB" ] || { say "FAIL: Hermes state DB missing: $HERMES_DB"; exit 1; }

section "STAGE-11 HERMES PROMPT / SESSION OVERHEAD AUDIT"
say "Read-only: no service restarts, no config writes, no DB writes."
say "Hermes:  $(systemctl --user is-active hermes-gateway.service 2>/dev/null || true)"
say "Gateway: $(systemctl is-active ai-gateway.service 2>/dev/null || true)"
say "Ollama:  $(systemctl is-active ollama.service 2>/dev/null || true)"

section "CONFIG SUMMARY"
"$HERMES_PYTHON" - "$HERMES_CONFIG" <<'PY'
from pathlib import Path
import json, sys, yaml
cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
agent = cfg.get("agent") if isinstance(cfg, dict) else {}
agent = agent if isinstance(agent, dict) else {}
model = cfg.get("model") if isinstance(cfg, dict) else None
print("reasoning_effort:", repr(agent.get("reasoning_effort")))
print("model:", json.dumps(model, ensure_ascii=False) if isinstance(model, (dict,list)) else repr(model))

interesting = ("tool", "skill", "memory", "context", "prompt", "iteration", "compress", "session")
secret = ("token", "secret", "password", "api_key", "apikey", "authorization")

def walk(obj, prefix=""):
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        low = path.lower()
        if any(s in low for s in secret):
            continue
        if isinstance(value, dict):
            walk(value, path)
            continue
        if any(word in low for word in interesting):
            if isinstance(value, (str, int, float, bool)) or value is None:
                text = repr(value)
                if len(text) > 180:
                    text = text[:177] + "..."
                print(f"{path}: {text}")
            elif isinstance(value, list):
                print(f"{path}: <list len={len(value)}>")

walk(cfg)
PY

section "SESSION DB STRUCTURE + RECENT SESSION COST"
"$HERMES_PYTHON" - "$HERMES_DB" <<'PY'
from __future__ import annotations
import hashlib, sqlite3, sys
from pathlib import Path

path = Path(sys.argv[1])
uri = f"file:{path}?mode=ro"
conn = sqlite3.connect(uri, uri=True)
conn.row_factory = sqlite3.Row


def cols(table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

def sid_hash(value):
    if value is None:
        return "-"
    return hashlib.sha256(str(value).encode()).hexdigest()[:10]

tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print("tables:", ", ".join(sorted(tables)))

if "sessions" in tables:
    c = cols("sessions")
    print("sessions columns:", ", ".join(c))
    order = next((x for x in ("last_activity_at","updated_at","created_at") if x in c), None)
    selected = [x for x in ("id","source","created_at","updated_at","last_activity_at","input_tokens","output_tokens","total_tokens","prompt_tokens","completion_tokens","api_calls","system_prompt_hash") if x in c]
    sql = "SELECT " + ",".join(selected) + " FROM sessions"
    if order:
        sql += f" ORDER BY {order} DESC"
    sql += " LIMIT 10"
    print("recent sessions:")
    for row in conn.execute(sql):
        d = dict(row)
        if "id" in d:
            d["id"] = sid_hash(d["id"])
        print(d)

if "messages" in tables:
    c = cols("messages")
    print("messages columns:", ", ".join(c))
    sid_col = next((x for x in ("session_id","session") if x in c), None)
    content_col = next((x for x in ("content","text") if x in c), None)
    role_col = "role" if "role" in c else None
    if sid_col and content_col:
        order_expr = "MAX(id)" if "id" in c else "COUNT(*)"
        sql = f"SELECT {sid_col} sid, COUNT(*) n, SUM(LENGTH(COALESCE({content_col},''))) chars"
        if role_col:
            sql += f", SUM(CASE WHEN {role_col}='user' THEN 1 ELSE 0 END) user_n, SUM(CASE WHEN {role_col}='assistant' THEN 1 ELSE 0 END) assistant_n, SUM(CASE WHEN {role_col}='tool' THEN 1 ELSE 0 END) tool_n"
        sql += f" FROM messages GROUP BY {sid_col} ORDER BY {order_expr} DESC LIMIT 10"
        print("recent session message footprint (content is NOT printed):")
        for row in conn.execute(sql):
            d = dict(row); d["sid"] = sid_hash(d["sid"]); print(d)

if "system_prompts" in tables:
    c = cols("system_prompts")
    print("system_prompts columns:", ", ".join(c))
    content_col = next((x for x in ("content","prompt","system_prompt") if x in c), None)
    if content_col:
        rows = conn.execute(f"SELECT LENGTH(COALESCE({content_col},'')) n FROM system_prompts ORDER BY n DESC LIMIT 5").fetchall()
        print("largest stored system prompt char lengths:", [int(r[0] or 0) for r in rows])

if "session_model_usage" in tables:
    c = cols("session_model_usage")
    print("session_model_usage columns:", ", ".join(c))
    sid_col = next((x for x in ("session_id","session") if x in c), None)
    numeric = [x for x in c if any(k in x.lower() for k in ("token","call","cost","duration"))]
    selected = ([sid_col] if sid_col else []) + numeric
    selected = list(dict.fromkeys(x for x in selected if x))
    if selected:
        order = next((x for x in ("updated_at","created_at","id") if x in c), None)
        sql = "SELECT " + ",".join(selected) + " FROM session_model_usage"
        if order:
            sql += f" ORDER BY {order} DESC"
        sql += " LIMIT 20"
        print("recent model-usage rows:")
        for row in conn.execute(sql):
            d = dict(row)
            if sid_col and sid_col in d:
                d[sid_col] = sid_hash(d[sid_col])
            print(d)

conn.close()
PY

section "JSON SESSION SNAPSHOT FOOTPRINT"
if [ -r "$HERMES_SESSIONS" ]; then
"$HERMES_PYTHON" - "$HERMES_SESSIONS" <<'PY'
from pathlib import Path
import hashlib, json, sys
p = Path(sys.argv[1])
print("file_bytes:", p.stat().st_size)
try:
    doc = json.loads(p.read_text(encoding="utf-8"))
except Exception as exc:
    print("unreadable:", repr(exc)); raise SystemExit(0)

def sid_hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:10]

def message_stats(obj):
    candidates=[]
    if isinstance(obj, dict):
        for key,val in obj.items():
            if key in {"messages","history","conversation"} and isinstance(val,list):
                candidates.append(val)
    for msgs in candidates:
        chars=0; roles={}
        for m in msgs:
            if not isinstance(m,dict): continue
            roles[str(m.get("role","?"))]=roles.get(str(m.get("role","?")),0)+1
            content=m.get("content","")
            if isinstance(content,str): chars += len(content)
            else:
                try: chars += len(json.dumps(content, ensure_ascii=False))
                except Exception: pass
        return len(msgs), chars, roles
    return None

items=[]
if isinstance(doc,dict):
    for k,v in doc.items():
        if isinstance(v,dict): items.append((k,v))
elif isinstance(doc,list):
    items=[(i,v) for i,v in enumerate(doc) if isinstance(v,dict)]
print("top-level session-like entries:", len(items))
for key,obj in items[:20]:
    stats=message_stats(obj)
    if stats:
        print({"id":sid_hash(key),"messages":stats[0],"content_chars":stats[1],"roles":stats[2]})
PY
else
    say "sessions.json: not present/readable"
fi

section "RECENT HERMES LOG SIGNALS (METADATA ONLY)"
LOG="${HERMES_HOME}/logs/gateway.log"
if [ -r "$LOG" ]; then
    tail -n 2500 "$LOG" \
      | grep -Ei 'prompt[_ ]?tokens|completion[_ ]?tokens|total[_ ]?tokens|context|compress|usage|tool.search|tool_search' \
      | tail -n 120 \
      | sed -E 's/(token|api[_-]?key|secret|password)[=: ][^ ,]+/\1=***REDACTED***/Ig' \
      || true
else
    say "gateway.log: not present/readable"
fi

section "POSTCHECK"
"$HERMES_PYTHON" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:11435/health", timeout=2) as r:
    h=json.load(r)
assert h.get("status")=="ok" and h.get("ollama")=="ok", h
with urllib.request.urlopen("http://127.0.0.1:11435/status", timeout=2) as r:
    s=json.load(r)
assert s.get("active_count")==0 and s.get("queued_count")==0, s
print("PASS: AI Gateway healthy and idle")
PY

say "PASS: Stage-11 read-only Hermes prompt/session overhead audit completed"
