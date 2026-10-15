#!/usr/bin/env -S python3 -I -B -S
"""Pinned original-evidence preflight. Always NO_GO; no apply implementation.

Run with -I -B -S (or directly). Never imports the operational gate. No HTTP,
commands, inference, secret reads, directory creation, or evidence writes.
"""
import sys
sys.dont_write_bytecode = True

import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import time

spec = importlib.util.spec_from_file_location(
    "recovery_structure", Path(__file__).with_name("recover_acceptance_once.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

ROOT_UID = ROOT_GID = 0
STATE = "/var/lib/ai-platform/stage-o"
CURRENT = "/opt/ai-platform/current"
RELEASE = "/opt/ai-platform/releases/" + h.RELEASE
DECISION = "STAGE-O-2026-10-15-DECISION-1"
ENV_IDENTITIES = ("/etc/ai-bridge/ai-bridge.env", "/etc/ai-gateway/ai-gateway.env")
# These cannot be cleared by operator-provided PASS flags or JSON.
MISSING = {
    "SOURCE_RELEASE_ROLLBACK": "Authenticated pinned Git/archive bytes, complete release metadata/checksums/payload and independent accepted rollback not actively verified.",
    "CLIENTS_RUNTIME_CONFIG": "Historical client digest/mode/uid/gid, effective systemd identities/cwd, preload/model/LoRA, Bridge/Control/GUI/Gateway not actively verified.",
    "QUIESCENCE": "No active change/handoff, queue, leases and idle not actively verified; executor.lock alone does not freeze other actors.",
    "STAGE_K": "Fresh monitor/daily<=36h/weekly<=192h, nested restore, NAS identity, current config snapshots and encrypted archive/manifest hashes not actively verified.",
    "ENV_EXCEPTION": "Owner approved only historical byte-identity risk for exactly two env files; authenticated manifests, size/mode/times and operator record bound to decision still required. CONTENT NOT VERIFIED.",
    "WRITE_CONTRACT": "Separate recovery authorization, single-use token, trusted boot evidence, race-safe revalidation and immutable attestation/accepted commit not implemented. Stop; no apply command exists.",
}


def trusted(st, mode=None):
    h.require(st.st_uid == ROOT_UID and st.st_gid == ROOT_GID and not st.st_mode & 0o022,
              "OWNER_OR_MODE")
    if mode is not None:
        h.require(stat.S_IMODE(st.st_mode) == mode, "MODE")


def directory(path):
    """Open all components without symlink traversal, requiring trusted parents."""
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        trusted(os.fstat(fd))
        for part in path.split("/")[1:]:
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
            trusted(os.fstat(fd))
        return fd
    except BaseException:
        os.close(fd)
        raise


def original_transaction():
    """Limited observation under existing shared lock, never acceptance proof."""
    h.require(os.geteuid() == 0, "ROOT_REQUIRED")
    parent = directory(STATE)
    lock = None
    try:
        lock = os.open("executor.lock", os.O_RDONLY | os.O_NOFOLLOW |
                       os.O_NOATIME | os.O_NONBLOCK, dir_fd=parent)
        ls = os.fstat(lock)
        trusted(ls)
        h.require(stat.S_ISREG(ls.st_mode) and ls.st_nlink == 1, "LOCK_TYPE")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence = directory(STATE + "/" + h.SOURCE)
        current_parent = None
        try:
            trusted(os.fstat(evidence), 0o700)
            before = {}
            for name in h.NAMES:
                st = os.stat(name + ".json", dir_fd=evidence, follow_symlinks=False)
                trusted(st, 0o600)
                h.require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "ARTIFACT_TYPE")
                before[name] = h.snapshot(st)
            current_parent = directory(os.path.dirname(CURRENT))
            leaf = os.path.basename(CURRENT)
            cs = os.stat(leaf, dir_fd=current_parent, follow_symlinks=False)
            h.require(stat.S_ISLNK(cs.st_mode) and cs.st_uid == ROOT_UID and cs.st_gid == ROOT_GID,
                      "CURRENT_IDENTITY")
            h.require(os.readlink(leaf, dir_fd=current_parent) == RELEASE, "CURRENT_TARGET")
            # Exact eight-file set also rejects accepted, partial attestation and markers.
            documents, hashes = h.read_copies(STATE + "/" + h.SOURCE)
            h.validate_structure(documents, int(time.time()))
            for name, fingerprint in before.items():
                h.require(h.snapshot(os.stat(name + ".json", dir_fd=evidence,
                          follow_symlinks=False)) == fingerprint, "ARTIFACT_CHANGED")
            h.require(h.snapshot(os.stat(leaf, dir_fd=current_parent,
                      follow_symlinks=False)) == h.snapshot(cs), "CURRENT_CHANGED")
            h.require(h.snapshot(os.stat("executor.lock", dir_fd=parent,
                      follow_symlinks=False)) == h.snapshot(ls), "LOCK_CHANGED")
            return hashes
        finally:
            if current_parent is not None:
                os.close(current_parent)
            os.close(evidence)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--check", action="store_true", help="read-only default")
    parser.add_argument("--expected-source", required=True, choices=[h.SOURCE])
    parser.parse_args(argv)
    report = dict(mode="CHECK", status="NO_GO", apply_available=False,
                  source_sha=h.SOURCE, decision_id=DECISION,
                  env_exception_identities=ENV_IDENTITIES,
                  historical_env_contents="NOT_VERIFIED", e_safe="NOT_VERIFIED",
                  missing_proof=MISSING, original_transaction="REJECTED")
    try:
        report["artifact_sha256"] = original_transaction()
        report["original_transaction"] = "STRUCTURE_OBSERVED_UNDER_LOCK"
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        report["diagnostic"] = "ORIGINAL_PREFLIGHT_REJECTED"
    print(json.dumps(report, sort_keys=True, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
