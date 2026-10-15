#!/usr/bin/env -S python3 -I -B -S
"""Offline prerequisite CHECK for one release; never an acceptance authority.

No apply implementation, production probes, gate imports, commands or writes.
Optional evidence directory contains untrusted copies, NOT authenticated originals.
Even a structurally valid copy cannot establish E_safe or authorize recovery.
Run directly or with python -I -B -S; no arguments only prints prerequisites.
These interpreter flags prevent startup bytecode/site hooks BEFORE this file runs.
"""
import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import stat
import time

SOURCE = "5e104ea69d0bfa342209acdc8dc88145b34ae72e"
RELEASE = "stage-o-" + SOURCE[:12]
SCHEMA = "0005_crt_projection"
NAMES = (
    "baseline", "installed", "20_cutover", "candidate-smoke",
    "rollback", "rollback-smoke", "reactivate", "final-smoke",
)
CLIENTS = {
    "/usr/local/bin/hermes-foto-dispatch",
    "/usr/local/libexec/ai-server/hermes_resource_queue.py",
    "/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py",
    "/usr/local/libexec/ai-server/hermes_video_dispatch.py",
    "/usr/local/libexec/ai-server/qwen_prompt_compiler.py",
}
# These are obligations, not inputs that can be satisfied by supplying PASS JSON.
BLOCKERS = {
    "CONFIG_REFERENCE_UNAVAILABLE": "Independent pre-reboot approved snapshot of all env, effective units/drop-ins, ExecStart, A/B routing, model/LoRA/adapter and preload script is missing; baseline records only one preload unit, clients and service states.",
    "ORIGINALS_UNAUTHENTICATED": "Require exactly eight original write-once artifacts, root owner/group, 0600 files/0700 directory, provenance, full content and timestamps; copied bytes and mtimes cannot prove immutability.",
    "RELEASE_NOT_VERIFIED": "Require current symlink identity, RELEASE/manifest contracts, installed checksum binding, complete payload checksums and both services' tracked bytes/modes/symlinks from trusted pinned Git source.",
    "ROLLBACK_NOT_VERIFIED": "Require rollback metadata/checksums/source and authentic accepted evidence for its own contract.",
    "RUNTIME_NOT_VERIFIED": "Require fresh Gateway/Bridge/Control Center health, actual process paths/effective units/NeedDaemonReload, Hermes/timer, idle/leases, identical clients digest/mode/owner, unchanged preload/model/adapter and A/B.",
    "BACKUP_NOT_VERIFIED": "Require fresh Stage K monitor/daily/weekly PASS with nested restore validation, no issues, valid non-future times (daily <=36h, weekly <=192h), and current NAS identity/mount/status.",
    "BOOT_CONTINUITY_NOT_PROVEN": "Historical PID/InvocationID is not current post-reboot continuity; record new boot ID and independent E_safe evidence. Health and hashes do not prove E_safe.",
    "TRANSACTION_NOT_IMPLEMENTED": "No apply/auth/lock path. Future implementation needs owner approval bound to full SHA/evidence, shared Stage O executor.lock, revalidation under lock and protection against every mutable input race.",
    "FINALIZE_NEVER_COMPLETED": "Never impersonate original finalize: any future recovery needs separate dated immutable recovery-attestation.json with evidence digest/boot ID, write-once atomic fsync, then accepted.json last, no overwrite.",
}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def exact(value, keys):
    return type(value) is dict and set(value) == set(keys.split())


def digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def positive(value):
    return type(value) is int and value > 0


def validate_structure(documents, now):
    """Pure structural diagnostics only. Does not trust values or return PASS."""
    require(type(documents) is dict and set(documents) == set(NAMES), "ARTIFACT_SET")
    b = documents["baseline"]
    require(exact(b, "rollback rollback_sha rollback_stage candidate source_sha clients comfy hermes_active analysis_timer_active preload_unit rollback_checksums schema"), "BASELINE_KEYS")
    require(b["source_sha"] == SOURCE and b["candidate"] == RELEASE and b["schema"] == SCHEMA, "BASELINE_IDENTITY")
    require(type(b["rollback_sha"]) is str and re.fullmatch(r"[0-9a-f]{40}", b["rollback_sha"]) is not None, "ROLLBACK_SHA")
    require(b["rollback_stage"] in ("M", "O") and b["rollback"] == "stage-" + b["rollback_stage"].lower() + "-" + b["rollback_sha"][:12] and b["rollback"] != RELEASE, "ROLLBACK_IDENTITY")
    require(digest(b["rollback_checksums"]), "ROLLBACK_CHECKSUM")
    require(type(b["preload_unit"]) is str and bool(b["preload_unit"].strip()), "PRELOAD_EMPTY")
    require(b["hermes_active"] in ("active", "inactive") and b["analysis_timer_active"] in ("active", "inactive"), "SERVICE_STATES")
    c = b["comfy"]
    require(type(c) is list and len(c) == 2 and type(c[0]) is str and re.fullmatch(r"[1-9][0-9]*", c[0]) is not None and type(c[1]) is str and re.fullmatch(r"[0-9a-f]{32}", c[1]) is not None, "HISTORICAL_COMFY_IDENTITY")
    require(type(b["clients"]) is dict and set(b["clients"]) == CLIENTS, "CLIENT_SET")
    for entry in b["clients"].values():
        require(type(entry) is list and len(entry) == 4 and digest(entry[0]) and all(type(n) is int for n in entry[1:]) and 0 <= entry[1] <= 0o7777 and all(n >= 0 for n in entry[2:]), "CLIENT_RECORD")
    i = documents["installed"]
    require(exact(i, "candidate source_sha checksums") and i["candidate"] == RELEASE and i["source_sha"] == SOURCE and digest(i["checksums"]), "INSTALLED_IDENTITY")
    for name, target in (("20_cutover", RELEASE), ("rollback", b["rollback"]), ("reactivate", RELEASE)):
        require(documents[name] == {"release_id": target}, "SWITCH_IDENTITY_" + name)
    times = []
    for name, target in (("candidate-smoke", RELEASE), ("rollback-smoke", b["rollback"]), ("final-smoke", RELEASE)):
        s = documents[name]
        require(exact(s, "release_id schema control_center benchmarks time") and s["release_id"] == target and s["schema"] == SCHEMA, "SMOKE_IDENTITY_" + name)
        require(positive(s["time"]) and s["time"] <= now, "SMOKE_TIME_" + name)
        times.append(s["time"])
        cc, bm = s["control_center"], s["benchmarks"]
        rollback = name == "rollback-smoke"
        if rollback and b["rollback_stage"] == "M":
            require(cc == {"status": "ABSENT"}, "ROLLBACK_CC")
        else:
            require(exact(cc, "status apps knowledge_results") and cc["status"] == "PASS" and positive(cc["knowledge_results"]), "SMOKE_CC_" + name)
            apps = ["knowledge", "benchmarks", "ers", "observability", "system-map", "incidents"]
            require(cc["apps"] in [apps[:n] for n in range(3, 7)] if rollback else cc["apps"] == apps, "SMOKE_APPS_" + name)
        if rollback:
            require(bm == {"status": "ROLLBACK_NOT_REQUIRED"}, "ROLLBACK_BENCHMARK")
        else:
            require(exact(bm, "status suite_case_counts raw_results reranked_results") and bm["status"] == "PASS" and positive(bm["raw_results"]) and positive(bm["reranked_results"]), "SMOKE_BENCHMARK_" + name)
            counts = bm["suite_case_counts"]
            expected = {"automotive-reasoning": 58, "decision-models": 51, "rag-knowledge": 61}
            require(type(counts) is dict and set(counts) == set(expected) and all(type(counts[k]) is int and counts[k] >= v for k, v in expected.items()), "BENCHMARK_COUNTS_" + name)
    require(times == sorted(times), "SMOKE_SEQUENCE")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def snapshot(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def read_copies(directory):
    """Linux read-only, no atime writes; reject symlinks in every path component.

    Rechecking detects ordinary concurrent changes, NOT an authenticated snapshot
    or a solution to adversarial TOCTOU. Thus all authority blockers remain.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NOATIME | os.O_NONBLOCK
    traversal = os.O_PATH | os.O_NOFOLLOW | os.O_DIRECTORY
    fd = os.open("/", traversal)
    try:
        for part in os.path.abspath(directory).split("/")[1:]:
            nxt = os.open(part, traversal, dir_fd=fd)
            os.close(fd)
            fd = nxt
        nxt = os.open(".", flags | os.O_DIRECTORY, dir_fd=fd)
        os.close(fd)
        fd = nxt
        before = snapshot(os.fstat(fd))
        require(set(os.listdir(fd)) == {n + ".json" for n in NAMES}, "ARTIFACT_SET")
        documents, fingerprints, hashes, mtimes = {}, {}, {}, []
        for name in NAMES:
            leaf = name + ".json"
            item = os.open(leaf, flags, dir_fd=fd)
            try:
                st = os.fstat(item)
                require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and 0 < st.st_size <= 1024 * 1024, "COPY_FILE_TYPE_SIZE")
                raw = bytearray()
                while len(raw) <= 1024 * 1024:
                    chunk = os.read(item, 65536)
                    if not chunk:
                        break
                    raw.extend(chunk)
                require(len(raw) == st.st_size and snapshot(st) == snapshot(os.fstat(item)), "COPY_CHANGED")
                documents[name] = json.loads(raw, object_pairs_hook=unique_object,
                                             parse_constant=lambda _: require(False, "JSON_CONSTANT"))
                hashes[name] = hashlib.sha256(raw).hexdigest()
                fingerprints[leaf] = snapshot(st)
                mtimes.append(st.st_mtime_ns)
            finally:
                os.close(item)
        require(mtimes == sorted(mtimes), "COPY_MTIME_SEQUENCE")
        require(before == snapshot(os.fstat(fd)), "DIRECTORY_CHANGED")
        for leaf, fingerprint in fingerprints.items():
            require(snapshot(os.stat(leaf, dir_fd=fd, follow_symlinks=False)) == fingerprint, "COPY_CHANGED")
        return documents, hashes
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--expected-source", help="must be the full pinned SHA for optional copy inspection")
    parser.add_argument("--evidence-dir", help="offline directory of exactly eight untrusted JSON copies")
    args = parser.parse_args(argv)  # --apply/approval/lock options deliberately do not exist.
    report = {"mode": "CHECK", "status": "NO_GO", "source_sha": SOURCE,
              "apply_available": False, "e_safe": "NOT_ESTABLISHED",
              "copy_structure": "NOT_CHECKED", "blockers": BLOCKERS,
              "diagnostics": []}
    if args.expected_source != SOURCE:
        report["diagnostics"].append("EXPECTED_FULL_SOURCE_REQUIRED")
    elif args.evidence_dir:
        try:
            documents, hashes = read_copies(args.evidence_dir)
            validate_structure(documents, int(time.time()))
            report["copy_structure"] = "CONSISTENT_UNAUTHENTICATED"
            report["copy_sha256"] = hashes
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            # Never echo contents, paths, env, preload secrets or exception text.
            report["copy_structure"] = "REJECTED"
            report["diagnostics"].append("COPY_READ_OR_STRUCTURE_REJECTED")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
