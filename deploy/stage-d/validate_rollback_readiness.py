#!/usr/bin/env python3
"""Verify candidate + preserved rollback artifacts offline; never activate them."""
import argparse
import hashlib
from pathlib import Path
import re

from validate_release_metadata import validate


def verify_checksums(root):
    root = root.resolve()
    entries = (root / "metadata/SHA256SUMS").read_text().splitlines()
    seen = set()
    for entry in entries:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", entry)
        if not match:
            raise ValueError("invalid checksum entry")
        expected, name = match.groups()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path in seen:
            raise ValueError("unsafe or duplicate checksum entry")
        seen.add(path)
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("checksum mismatch")
    for name in ("RELEASE", "metadata/release-manifest.yaml"):
        if (root / name).resolve() not in seen:
            raise ValueError("required metadata missing from checksums")


def verify_pair(candidate, rollback):
    if candidate.resolve() == rollback.resolve():
        raise ValueError("candidate and rollback must differ")
    validate(candidate)
    verify_checksums(candidate)
    verify_checksums(rollback)
    lines = (rollback / "RELEASE").read_text().splitlines()
    if not any(line in ("stage=C", "stage=D") for line in lines):
        raise ValueError("rollback must be Stage C/D")
    # Historical D.0/C contracts intentionally remain valid rollback artifacts.
    for root in (candidate, rollback):
        for service in ("ai-bridge", "ai-gateway"):
            if not (root / "services" / service / "src/ai_bridge").is_dir():
                raise ValueError("release source missing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("rollback", type=Path)
    args = parser.parse_args()
    try:
        verify_pair(args.candidate, args.rollback)
    except (OSError, ValueError):
        raise SystemExit("FAIL: rollback artifacts invalid or unreadable") from None
    print("ROLLBACK ARTIFACT READINESS: PASS; live rollback remains NOT RUN")
