"""Narrow process-program attestation for a queued local Vision worker.

This checks immutable deployment inputs, not privilege isolation: different
service UID and protected files remain necessary at the production boundary.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def _digest(path: Path) -> str | None:
    try:
        h=hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError,ValueError):
        return None


def attest_worker(pid: int, script_allowlist: dict[str,str],
                  checkpoint_allowlist: dict[str,str], gate_sha256: str,
                  gate_path: Path | None = None) -> bool:
    """Confirm trusted gate + explicitly pinned program/checkpoint SHA-256."""
    if type(pid) is not int or pid <= 1 or not script_allowlist:
        return False
    try:
        raw=Path(f"/proc/{pid}/cmdline").read_bytes()
        args=[b.decode("utf-8") for b in raw.rstrip(b"\x00").split(b"\x00")]
        if len(args)<10 or len(args)>100:
            return False
        gate=(gate_path if gate_path is not None else
              Path(__file__).resolve().parents[1]/"benchmarks"/"vision_worker_gate.py")
        if Path(args[1]).resolve(strict=True)!=gate:
            return False
        if _digest(gate) != gate_sha256:
            return False
        if args.count("--script")!=1 or args.count("--python")!=1:
            return False
        script=Path(args[args.index("--script")+1]).resolve(strict=True)
        exe=Path(args[args.index("--python")+1]).resolve(strict=True)
        process_exe=Path(f"/proc/{pid}/exe").resolve(strict=True)
        if process_exe!=exe:
            return False
        if script_allowlist.get(str(script))!=_digest(script):
            return False
        # Explicit --checkpoint must be approved and content-pinned.
        if "--checkpoint" in args:
            if args.count("--checkpoint")!=1:
                return False
            ckpt=Path(args[args.index("--checkpoint")+1]).resolve(strict=True)
            if checkpoint_allowlist.get(str(ckpt))!=_digest(ckpt):
                return False
        return True
    except (OSError,UnicodeError,ValueError,IndexError):
        return False
