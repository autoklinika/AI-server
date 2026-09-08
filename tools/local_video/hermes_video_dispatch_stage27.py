#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import hermes_video_dispatch_stage26 as base
except ImportError:
    import hermes_video_dispatch as base

import qwen_prompt_compiler as qwen


def queue_job(parts: list[str]) -> str:
    # Stage-26 queue_job is already proven on Telegram. It chooses the worker
    # from its module __file__, so point that lookup at this Stage-27 wrapper.
    old_file = base.__file__
    base.__file__ = __file__
    try:
        return base.queue_job(parts)
    finally:
        base.__file__ = old_file


def _augment_result(job_dir: Path, meta: dict) -> None:
    path = job_dir / "result.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    payload.update(meta)
    base._write_result(job_dir, payload)


def run_worker(request_path: Path) -> int:
    job_dir = request_path.parent
    request = json.loads(request_path.read_text(encoding="utf-8"))
    target = str(request.get("target") or "").strip()
    original = str(request.get("prompt") or "").strip()
    if request.get("schema") != 1 or not target or not original:
        return base.run_worker(request_path)

    effective, used, reason, qwen_elapsed = qwen.compile_prompt(original)
    print(f"qwen_used: {str(used).lower()}", flush=True)
    print(f"qwen_elapsed_seconds: {qwen_elapsed:.3f}", flush=True)
    print(f"original_prompt: {original}", flush=True)
    print(f"effective_prompt: {effective}", flush=True)
    if reason:
        print(f"qwen_failure_reason: {reason}", flush=True)

    meta = {
        "qwen_used": used,
        "original_prompt": original,
        "effective_prompt": effective,
        "qwen_failure_reason": reason,
        "qwen_elapsed_seconds": round(qwen_elapsed, 3),
    }

    if not used:
        # Silent fallback is forbidden. Failure to deliver this warning aborts
        # before the LTX worker is called.
        try:
            base._send(target, qwen.fallback_notice(reason))
        except Exception as exc:
            meta.update({"ok": False, "error": f"Nie wysłano ostrzeżenia o pominięciu Qwen: {exc}"})
            base._write_result(job_dir, meta)
            print(meta["error"], file=sys.stderr, flush=True)
            return 1

    staged = job_dir / "request.stage27.json"
    staged_doc = dict(request)
    staged_doc["prompt"] = effective
    staged.write_text(json.dumps(staged_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        staged.chmod(0o600)
    except OSError:
        pass

    try:
        rc = base.run_worker(staged)
    finally:
        try:
            staged.unlink()
        except FileNotFoundError:
            pass

    _augment_result(job_dir, meta)
    return rc


def qwen_preflight() -> int:
    sample = "Mały czerwony robot stoi na stole elektronika i macha prawą ręką do kamery."
    effective, used, reason, elapsed = qwen.compile_prompt(sample)
    print(json.dumps({
        "ok": used,
        "qwen_used": used,
        "qwen_failure_reason": reason,
        "qwen_elapsed_seconds": round(elapsed, 3),
        "effective_prompt": effective if used else None,
    }, ensure_ascii=False, indent=2))
    return 0 if used else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Hermes /wideo Stage 27 local Qwen prompt compiler")
    p.add_argument("--worker", type=Path)
    p.add_argument("--qwen-preflight", action="store_true")
    p.add_argument("parts", nargs="*")
    args = p.parse_args(argv)
    if args.qwen_preflight:
        return qwen_preflight()
    if args.worker:
        return run_worker(args.worker)
    try:
        print(queue_job(args.parts), flush=True)
        return 0
    except base.DispatchError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
