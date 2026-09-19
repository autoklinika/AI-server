#!/usr/bin/env python3
"""Read-only routing detail audit: no Hermes imports, sends, renders or service changes."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

BASELINE = "92ceea7bc4bc2b2af30da313b22108e9d686c265"
ROUTE_MARKER = "STAGE26_WIDEO_ROUTE_ENV"
RETURN = "return True, await self._hm_run_exec_quick_command(command, exec_cmd), command"
SAFE_STRINGS = {"", " ", "telegram", "HERMES_SESSION_PLATFORM=", "HERMES_SESSION_CHAT_ID=",
                "HERMES_SESSION_THREAD_ID=", "foto", "wideo"}


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def run(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def compare(path: Path, repo: Path, relative: str) -> dict:
    current = read(path)
    baseline = run(["git", "-C", str(repo), "show", f"{BASELINE}:{relative}"])
    return {"present": path.is_file(), "readable": bool(current),
            "baseline_available": bool(baseline),
            "matches_main_stage30": current == baseline if baseline and current else None}


class Redact(ast.NodeTransformer):
    def visit_Constant(self, node):
        value = node.value
        if value is None or type(value) is bool or (isinstance(value, str) and value in SAFE_STRINGS):
            return node
        return ast.copy_location(ast.Constant(value="<literal_redacted>"), node)


def route_fragment(text: str) -> str:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if f"# {ROUTE_MARKER}" in line]
    if len(starts) != 1:
        raise ValueError("route marker not unique")
    start = starts[0]
    ends = [i for i in range(start + 1, min(start + 100, len(lines)))
            if RETURN in lines[i] or re.search(r"# STAGE(?:28|29)_", lines[i])]
    if not ends:
        raise ValueError("route boundary missing")
    return textwrap.dedent("\n".join(lines[start:ends[0]]))


def validate_probe(tree: ast.AST) -> bool:
    """Permit only the small Stage26 string-construction grammar, never arbitrary runtime code."""
    allowed = (ast.Module, ast.Assign, ast.If, ast.Name, ast.Load, ast.Store, ast.Attribute,
               ast.IfExp, ast.BoolOp, ast.Or, ast.And, ast.Constant, ast.Call, ast.Tuple,
               ast.BinOp, ast.Add, ast.JoinedStr, ast.FormattedValue)
    writable = {"exec_cmd", "_stage26_platform", "_stage26_chat_id", "_stage26_thread_id", "_stage26_route_env"}
    names = writable | {"source", "str", "_stage26_shlex"}
    attrs = {"source.platform", "source.platform.value", "source.chat_id", "source.thread_id",
             "_stage26_shlex.quote", "' '.join"}
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Name) and (node.id not in names or
                (isinstance(node.ctx, ast.Store) and node.id not in writable)):
            return False
        if isinstance(node, ast.Attribute) and ast.unparse(node) not in attrs:
            return False
        if isinstance(node, ast.Call) and (ast.unparse(node.func) not in
                {"str", "_stage26_shlex.quote", "' '.join"} or node.keywords):
            return False
        if isinstance(node, ast.Assign) and any(not isinstance(t, ast.Name) for t in node.targets):
            return False
        if isinstance(node, ast.Constant) and (not isinstance(node.value, str) or len(node.value) > 1000):
            return False
    return True


def route_detail(text: str) -> dict:
    try:
        fragment = route_fragment(text)
        tree = ast.parse(fragment)
    except (ValueError, SyntaxError):
        return {"status": "unrecognized_route_block", "probe_executed": False}
    result = {"status": "read", "redacted_code": ast.unparse(Redact().visit(ast.parse(fragment))).splitlines(),
              "probe_executed": False}
    if not validate_probe(tree):
        result["status"] = "nonstandard_block_probe_refused"
        return result
    code = compile(tree, "<isolated-route-string-probe>", "exec")
    results = {}
    for label, chat, thread in (("A", "11001", ""), ("B", "22002", ""),
                                 ("B_topic", "22002", "77"), ("missing", "", "")):
        namespace = {"__builtins__": {}, "str": str, "_stage26_shlex": shlex,
                     "source": SimpleNamespace(platform=SimpleNamespace(value="telegram"),
                                               chat_id=chat, thread_id=thread),
                     "exec_cmd": "/usr/local/bin/hermes-foto-dispatch 'audit payload'"}
        try:
            exec(code, namespace)
            tokens = shlex.split(namespace["exec_cmd"])
            env = {}
            for token in tokens:
                if not re.match(r"^[A-Z_][A-Z_0-9]*=", token):
                    break
                key, value = token.split("=", 1)
                env[key] = value
            results[label] = {"explicit_chat_prefix": bool(env.get("HERMES_SESSION_CHAT_ID")),
                              "correct_source_route": bool(chat) and env.get("HERMES_SESSION_PLATFORM") == "telegram"
                                  and env.get("HERMES_SESSION_CHAT_ID") == chat
                                  and env.get("HERMES_SESSION_THREAD_ID") == thread}
        except Exception:
            return {**result, "status": "isolated_probe_failed"}
    result.update(probe_executed=True, synthetic_cases=results)
    result["scope"] = "String construction only; no subprocess, actual event, authorization, live gateway or delivery tested."
    return result


def method_summary(text: str, name: str) -> dict:
    try:
        tree = ast.parse(text)
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        if len(nodes) != 1:
            return {"status": "not_unique_or_absent"}
        node = nodes[0]
        # Drop annotations, docstrings and user-defined literals before displaying code.
        node.returns = None
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            arg.annotation = None
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            node.body.pop(0)
        return {"status": "read", "redacted_code": ast.unparse(Redact().visit(node)).splitlines()[:75]}
    except SyntaxError:
        return {"status": "not_python_or_invalid"}


def report(repo: Path, home: Path, bindir: Path, libexec: Path) -> dict:
    gateway_path = home / "hermes-agent/gateway/run_inbound.py"
    gateway = read(gateway_path)
    paths = {
        "foto_actual_entrypoint": (bindir / "hermes-foto-dispatch", "tools/local_image/hermes_foto_dispatch.py"),
        "video_wrapper": (bindir / "hermes-video-dispatch", "tools/local_video/hermes-video-dispatch"),
        "video_stage30": (libexec / "hermes_video_dispatch.py", "tools/local_video/hermes_video_dispatch_stage30.py"),
        "video_active_base_stage30": (libexec / "hermes_video_dispatch_base.py", "tools/local_video/hermes_video_dispatch.py"),
    }
    files = {name: compare(path, repo, relative) for name, (path, relative) in paths.items()}
    for name in ("foto_actual_entrypoint", "video_stage30", "video_active_base_stage30"):
        if files[name]["matches_main_stage30"] is False:
            text = read(paths[name][0])
            files[name]["routing_target"] = method_summary(text, "routing_target")
            files[name]["send"] = method_summary(text, "_send")
    pid = run(["systemctl", "--user", "show", "hermes-gateway.service", "--property=MainPID", "--value"]).strip()
    newer = None
    if pid.isdigit() and int(pid) > 0:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime "))
            process_started = boot + int(stat[19]) / os.sysconf("SC_CLK_TCK")
            newer = gateway_path.stat().st_mtime > process_started + 2
        except (OSError, ValueError, IndexError, StopIteration):
            pass
    return {"audit": "telegram_routing_detail_v2", "baseline": BASELINE,
            "installed": files, "gateway_file_newer_than_service_process": newer,
            "gateway_route": route_detail(gateway),
            "exec_runner": method_summary(gateway, "_hm_run_exec_quick_command"),
            "limitations": ["Disk source is not proof of the code loaded by the running process.",
                            "Missing source prefix does not prove inherited routing survives environment sanitization."]}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.home() / "AI-server")
    p.add_argument("--home", type=Path, default=Path("/srv/ai-data/hermes"))
    p.add_argument("--bindir", type=Path, default=Path("/usr/local/bin"))
    p.add_argument("--libexec", type=Path, default=Path("/usr/local/libexec/ai-server"))
    args = p.parse_args()
    print(json.dumps(report(args.repo, args.home, args.bindir, args.libexec), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
