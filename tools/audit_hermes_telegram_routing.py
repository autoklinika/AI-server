#!/usr/bin/env python3
"""Read-only Stage29 routing audit. Never prints credentials, prompts or raw IDs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

BASELINE = "8ea1da072298ef6753bc41f36f04c1d8a1b4f3c7"
MARKERS = ("STAGE26_WIDEO_QUICK_ARGS", "STAGE26_WIDEO_ROUTE_ENV",
           "STAGE28_FOTO_MEDIA_ENV", "STAGE29_WIDEO_MEDIA_ENV")
EXPECTED = {"foto": "/usr/local/bin/hermes-foto-dispatch",
            "wideo": "/usr/local/bin/hermes-video-dispatch"}
ROUTE_KEYS = ("HERMES_SESSION_PLATFORM", "HERMES_SESSION_CHAT_ID",
              "HERMES_SESSION_THREAD_ID", "HERMES_SESSION_USER_ID",
              "TELEGRAM_HOME_CHANNEL", "TELEGRAM_ALLOWED_USERS")


def command(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=12, check=False,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class Labels:
    """Per-report aliases, shared by allowlists, home channel and job destinations."""
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def identity(self, value: object) -> str:
        text = str(value or "").strip()
        if not re.fullmatch(r"-?[1-9][0-9]*", text):
            return "unset" if not text else "non_numeric_redacted"
        if text not in self.values:
            self.values[text] = f"ID_{len(self.values) + 1}"
        return self.values[text]

    def target(self, value: object) -> str:
        text = str(value or "").strip()
        match = re.fullmatch(r"telegram:(-?[1-9][0-9]*)(?::([1-9][0-9]*))?", text)
        if not match:
            return "unset" if not text else "invalid_or_non_telegram_redacted"
        return "telegram:" + self.identity(match[1]) + (":topic_present" if match[2] else "")


def env_assignments(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and match[1] in ROUTE_KEYS:
            out[match[1]] = match[2].strip().strip("\"'")
    return out


def safe_env(values: dict, labels: Labels) -> dict:
    out = {}
    for key in ROUTE_KEYS:
        if key not in values:
            continue
        value = str(values[key] or "").strip()
        if key.endswith("PLATFORM"):
            out[key] = value if value in {"", "telegram"} else "other_redacted"
        elif key.endswith("ALLOWED_USERS"):
            ids = re.findall(r"(?<![\w])-?[1-9][0-9]*(?![\w])", value)
            out[key] = [labels.identity(item) for item in ids]
            if value and not ids:
                out[key] = "configured_non_numeric_redacted"
        elif key.endswith("THREAD_ID"):
            out[key] = "set" if value else "unset"
        else:
            out[key] = labels.identity(value)
    return out


def safe_config(path: Path, labels: Labels) -> dict:
    try:
        import yaml
        config = yaml.safe_load(read_text(path)) or {}
    except ImportError:
        return {"status": "yaml_unavailable_use_hermes_venv_python"}
    except Exception:
        return {"status": "unreadable_or_invalid_yaml"}
    if not path.is_file() or not isinstance(config, dict):
        return {"status": "missing_or_not_mapping"}
    quick = config.get("quick_commands") or {}
    if not isinstance(quick, dict):
        quick = {}
    out: dict = {"status": "read", "top_level_routing": safe_env(config, labels), "quick_commands": {}}
    for name, expected in EXPECTED.items():
        entry = quick.get(name)
        if not isinstance(entry, dict):
            out["quick_commands"][name] = {"present": entry is not None, "valid_mapping": False}
            continue
        cmd = str(entry.get("command") or "").strip()
        typ = entry.get("type")
        out["quick_commands"][name] = {
            "type": typ if isinstance(typ, str) and typ in {"exec", "alias"} else "other_redacted",
            "exact_expected_wrapper": cmd == expected,
            "mentions_session_override": "HERMES_SESSION_" in cmd,
            "mentions_home_channel": "HOME_CHANNEL" in cmd,
            "command_sha256": hashlib.sha256(cmd.encode()).hexdigest(),
        }
    return out


def safe_jobs(root: Path, labels: Labels, limit: int) -> list[dict]:
    rows = []
    try:
        paths = sorted(root.glob("*/request.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return [{"status": "unreadable_job_root"}]
    for index, path in enumerate(paths, 1):
        row: dict = {"newest_index": index}
        try:
            req = json.loads(read_text(path))
            result_path = path.parent / "result.json"
            res = json.loads(read_text(result_path)) if result_path.is_file() else {}
            if not isinstance(req, dict) or not isinstance(res, dict):
                raise ValueError("non-object record")
            row["target"] = labels.target(req.get("target"))
            row["result_present"] = result_path.is_file()
            row["ok"] = res.get("ok") if type(res.get("ok")) is bool else None
            row["result_target"] = labels.target(res.get("target"))
            row["target_mismatch"] = bool(res.get("target") and req.get("target") != res.get("target"))
            mode = req.get("mode")
            row["mode"] = mode if isinstance(mode, str) and mode in {"edit", "generate", "i2v", "t2v"} else "unspecified"
            row["has_input_image"] = bool(req.get("input_image"))
            row["has_error"] = bool(res.get("error"))
            # Explicitly no prompt, raw error, path, user name, ID, token, or media content.
        except (ValueError, TypeError, OSError):
            row["status"] = "unreadable_or_invalid_record"
        rows.append(row)
    return rows


def compare_installed(path: Path, repo: Path, relative: str) -> dict:
    baseline = command(["git", "-C", str(repo), "show", f"{BASELINE}:{relative}"])
    current = read_text(path)
    return {"present": path.is_file(), "baseline_available": bool(baseline),
            "matches_production_baseline": current.strip() == baseline.strip() if baseline and current else None,
            "sha256": hashlib.sha256(current.encode()).hexdigest() if current else None}


def report(home: Path, repo: Path, libexec: Path, jobs: Path, limit: int) -> dict:
    labels = Labels()
    out: dict = {"audit": "telegram_multiuser_read_only_v1", "production_baseline": BASELINE,
                 "notice": "IDs are anonymous per-report aliases; no prompts or credentials included."}
    out["dotenv_routing"] = safe_env(env_assignments(read_text(home / ".env")), labels)
    out["configuration"] = safe_config(home / "config.yaml", labels)
    hermes_source = home / "hermes-agent"
    sha = command(["git", "-C", str(hermes_source), "rev-parse", "HEAD"])
    out["hermes_commit"] = sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "unavailable"
    gateway = read_text(hermes_source / "gateway/run_inbound.py")
    out["gateway"] = {"present": bool(gateway), "markers": {m: gateway.count(m) for m in MARKERS},
                      "uses_source_chat_id": "source.chat_id" in gateway,
                      "uses_build_subprocess_env": "build_subprocess_env" in gateway}
    state = command(["systemctl", "--user", "is-active", "hermes-gateway.service"])
    out["service_active"] = state == "active"
    pid = command(["systemctl", "--user", "show", "hermes-gateway.service", "--property=MainPID", "--value"])
    if pid.isdigit() and int(pid) > 0:
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", errors="replace")
            env = dict(item.split("=", 1) for item in raw.split("\0") if "=" in item)
            out["service_initial_routing_env"] = safe_env(env, labels)
            out["service_initial_home_matches"] = env.get("HERMES_HOME") == str(home)
            out["service_initial_home_present"] = "HERMES_HOME" in env
        except OSError:
            out["service_initial_routing_env"] = "unreadable"
    out["installed"] = {
        "foto": compare_installed(libexec / "hermes_foto_dispatch.py", repo, "tools/local_image/hermes_foto_dispatch.py"),
        "video": compare_installed(libexec / "hermes_video_dispatch.py", repo, "tools/local_video/hermes_video_dispatch_stage29.py"),
        "video_base": compare_installed(libexec / "hermes_video_dispatch_stage26.py", repo, "tools/local_video/hermes_video_dispatch.py"),
    }
    out["foto_jobs"] = safe_jobs(jobs / "hermes-foto-jobs", labels, limit)
    out["video_jobs"] = safe_jobs(jobs / "hermes-video-jobs", labels, limit)
    out["distinct_numeric_identities"] = len(labels.values)
    out["limitations"] = ["Markers are not a behavioral proof.",
        "/proc environment describes process startup, not task-local ContextVars.",
        "A saved target is not proof of the initiating user's identity or Telegram delivery."]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path("/srv/ai-data/hermes"))
    parser.add_argument("--repo", type=Path, default=Path.home() / "AI-server")
    parser.add_argument("--libexec", type=Path, default=Path("/usr/local/libexec/ai-server"))
    parser.add_argument("--jobs", type=Path, default=Path("/srv/ai-data"))
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error("--limit must be between 1 and 50")
    print(json.dumps(report(args.home, args.repo, args.libexec, args.jobs, args.limit), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
