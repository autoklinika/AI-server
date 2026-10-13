#!/usr/bin/env python3
"""Fail-closed, read-only attestation of an already installed cross-UID DEV stage.

May be run without sudo. Does not read credentials, start units, or alter production.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "src/ai_bridge"
DEST = Path("/opt/ai-platform/vision-rm-candidate")
BIN = Path("/usr/local/libexec/ai-platform")
MANIFEST = Path("/usr/local/share/ai-platform/vision-rm/job.json")
SERVICES = ("ai-vision-rm-dev-gateway", "ai-vision-rm-broker", "ai-vision-rm-runner")
EXPECTED_STATES = {
    "ai-vision-rm-dev-gateway": "static",
    "ai-vision-rm-broker": "disabled",
    "ai-vision-rm-runner": "disabled",
}


class StageError(Exception):
    pass


def demand(condition: bool, reason: str) -> None:
    if not condition:
        raise StageError(reason)


def sha256(path: Path) -> bytes:
    return hashlib.sha256(path.read_bytes()).digest()


def root_owned(path: Path, directory: bool = False) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise StageError(f"STAGE_MISSING={path}: {exc}") from exc
    demand(not stat.S_ISLNK(info.st_mode), f"STAGE_SYMLINK_DENIED={path}")
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    demand(kind(info.st_mode), f"STAGE_INVALID_FILE_TYPE={path}")
    demand(info.st_uid == 0 and info.st_gid == 0, f"STAGE_NOT_ROOT_OWNED={path}")
    demand(not (info.st_mode & 0o022), f"STAGE_WRITABLE_BY_NON_ROOT={path}")
    # Prevent replacement via a writable or symlinked ancestor directory.
    for parent in path.parents:
        ancestor = parent.lstat()
        demand(stat.S_ISDIR(ancestor.st_mode) and ancestor.st_uid == 0
               and ancestor.st_gid == 0 and not (ancestor.st_mode & 0o022),
               f"STAGE_UNTRUSTED_PARENT={parent}")


def same_file(source: Path, installed: Path) -> None:
    demand(source.is_file(), f"STAGE_SOURCE_MISSING={source}")
    root_owned(installed)
    demand(sha256(source) == sha256(installed), f"STAGE_CONTENT_MISMATCH={installed}")


def listing(root: Path, source: bool) -> tuple[set[str], set[str]]:
    files, dirs = set(), set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(current)
        if not source:
            root_owned(here, directory=True)
        dirs.add(str(here.relative_to(root)))
        for name in dirnames[:]:
            p = here / name
            demand(not p.is_symlink(), f"STAGE_DIRECTORY_SYMLINK_DENIED={p}")
            if source and name == "__pycache__":
                dirnames.remove(name)
        for name in filenames:
            p = here / name
            if source and name.endswith(".pyc"):
                continue
            demand(p.is_file() and not p.is_symlink(), f"STAGE_NONREGULAR_SOURCE={p}")
            if not source:
                root_owned(p)
            files.add(str(p.relative_to(root)))
    return files, dirs


def systemd_properties(service: str) -> dict[str, str]:
    cp = subprocess.run(
        ["systemctl", "show", f"{service}.service", "--no-pager",
         "-p", "UnitFileState", "-p", "ActiveState", "-p", "SubState",
         "-p", "LoadState", "-p", "FragmentPath"],
        check=False, capture_output=True, text=True, timeout=10,
    )
    demand(cp.returncode == 0, f"STAGE_SYSTEMD_UNAVAILABLE={service}")
    return dict(line.split("=", 1) for line in cp.stdout.splitlines() if "=" in line)


def check_autostart_symlinks() -> None:
    names = {s + ".service" for s in SERVICES}
    for root in (Path("/etc/systemd/system"), Path("/run/systemd/system")):
        if not root.exists():
            continue
        def bad_walk(error: OSError) -> None:
            raise StageError(f"STAGE_AUTOSTART_SCAN_DENIED={error}")
        for current, dirnames, filenames in os.walk(root, onerror=bad_walk):
            for name in dirnames + filenames:
                p = Path(current) / name
                if p.is_symlink() and (name in names or p.resolve().name in names):
                    raise StageError(f"DEV_UNIT_UNEXPECTED_AUTOSTART_LINK={p}")


def verify() -> None:
    root_owned(DEST, directory=True)
    root_owned(DEST / "src", directory=True)
    candidate = DEST / "src/ai_bridge"
    demand(SRC.is_dir(), f"STAGE_SOURCE_MISSING={SRC}")
    demand(candidate.is_dir(), f"STAGE_CANDIDATE_MISSING={candidate}")

    expected_files, expected_dirs = listing(SRC, source=True)
    installed_files, installed_dirs = listing(candidate, source=False)
    demand(expected_files == installed_files and expected_dirs == installed_dirs,
           "STAGE_SOURCE_TREE_INCOMPLETE_OR_EXTRA")
    for rel in sorted(expected_files):
        demand(sha256(SRC / rel) == sha256(candidate / rel),
               f"STAGE_SOURCE_TREE_HASH_MISMATCH={rel}")

    installed = {
        HERE / "vision_rm_runner.py": BIN / "vision-rm-runner.py",
        HERE / "vision_rm_dev_cpu_worker.py": BIN / "vision-rm-dev-cpu-worker.py",
        HERE / "vision_rm_dev_cpu_job.json": MANIFEST,
        SRC / "benchmarks/vision_worker_gate.py": BIN / "vision-worker-gate.py",
    }
    for service in SERVICES:
        installed[HERE / (service + ".service")] = Path("/etc/systemd/system") / (service + ".service")
    for source, dest in installed.items():
        same_file(source, dest)

    check_autostart_symlinks()
    for service in SERVICES:
        props = systemd_properties(service)
        demand(props.get("LoadState") == "loaded", f"STAGE_UNIT_NOT_LOADED={service}")
        demand(props.get("FragmentPath") == f"/etc/systemd/system/{service}.service",
               f"STAGE_UNIT_UNEXPECTED_FRAGMENT={service}")
        state = props.get("UnitFileState")
        demand(state == EXPECTED_STATES[service],
               f"DEV_UNIT_UNEXPECTED_STATE={service}:{state}")
        demand(props.get("ActiveState") == "inactive" and props.get("SubState") == "dead",
               f"DEV_UNIT_UNEXPECTEDLY_ACTIVE={service}:{props.get('ActiveState')}")

    print("DEV_STAGING_INTEGRITY=PASS")
    print("DEV_STAGING_UNIT_STATE=PASS static-gateway disabled-broker disabled-runner")
    print("DEV_STAGING_AUTOSTART=ABSENT")
    print("DEV_STAGING_SERVICES=INACTIVE")


if __name__ == "__main__":
    try:
        verify()
    except (StageError, OSError, subprocess.SubprocessError) as exc:
        print(f"DEV_STAGING_VERIFICATION=FAIL {exc}", file=sys.stderr)
        sys.exit(1)
    print("DEV_STAGING_VERIFICATION=PASS")
