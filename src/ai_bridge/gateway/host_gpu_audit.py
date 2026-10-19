"""Metadata-only DEV audit. Never opens devices or grants GPU admission."""
from __future__ import annotations

import grp
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess

if __package__:
    from .os_gpu_boundary import Boundary, GPU, SERVICE_UNITS, TIMER_UNITS, _command
else:  # Direct stdlib-only entry point; avoid Gateway runtime dependencies.
    from os_gpu_boundary import Boundary, GPU, SERVICE_UNITS, TIMER_UNITS, _command

USERS = ("harrypotter", "ollama", "ai-vision")
# card0 has video-group DAC and is an alternative DRM entry point; not
# equivalent to a render node, but it must be included in the host audit.
DEVICE_NODES = GPU + ("/dev/dri/card0",)
UNITS = SERVICE_UNITS + TIMER_UNITS + (
    "ai-vision-execution@rm-gpu-probe.service", "ai-vision-gpu-observer.service",
    "gdm.service", "docker.service", "docker.socket", "ssh.service",
    "tailscaled.service",
)
FIELDS = ("LoadState", "ActiveState", "UnitFileState", "Restart", "MainPID",
          "DevicePolicy", "DeviceAllow", "User", "SupplementaryGroups")


def unknown():
    return {"inspection": "UNKNOWN"}


def device(path, command=_command):
    # lstat deliberately rejects symlink aliases. No open/access probe.
    s = Path(path).lstat()
    result = {"uid": s.st_uid, "gid": s.st_gid,
              "owner": pwd.getpwuid(s.st_uid).pw_name,
              "group": grp.getgrgid(s.st_gid).gr_name,
              "mode": format(stat.S_IMODE(s.st_mode), "04o"),
              "character_device": stat.S_ISCHR(s.st_mode)}
    if stat.S_ISCHR(s.st_mode):
        result["major_minor"] = [os.major(s.st_rdev), os.minor(s.st_rdev)]
    try:
        acl = command("getfacl", "--absolute-names", "--numeric", "--", str(path))
        result["acl"] = acl.stdout if acl.returncode == 0 and acl.stdout.strip() else "UNKNOWN"
    except (OSError, subprocess.TimeoutExpired):
        result["acl"] = "UNKNOWN"
    expected_group = "video" if str(path) == "/dev/dri/card0" else "render"
    result["expected_dac"] = (result["owner"] == "root" and
                              result["group"] == expected_group and
                              result["mode"] == "0660" and
                              result["character_device"])
    return result


def membership(name):
    user = pwd.getpwnam(name)
    gids = sorted(set(os.getgrouplist(name, user.pw_gid)))
    return {"uid": user.pw_uid, "primary_gid": user.pw_gid, "gids": gids,
            "groups": [grp.getgrgid(gid).gr_name for gid in gids]}


def processes(proc=Path("/proc")):
    targets = {grp.getgrnam(name).gr_gid for name in ("render", "video")}
    matches, unreadable = [], 0
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = dict(line.split(":", 1) for line in
                          (entry / "status").read_text().splitlines() if ":" in line)
            gids = {int(x) for x in fields["Groups"].split()}
            gids.update(int(x) for x in fields["Gid"].split())
            uids = [int(x) for x in fields["Uid"].split()]
            if targets & gids:
                matches.append({"pid": int(entry.name), "uids": uids,
                                "gpu_gids": sorted(targets & gids)})
        except (OSError, ValueError, KeyError):
            unreadable += 1
    return {"matches": matches, "unreadable_or_raced": unreadable,
            "coverage": "UNVERIFIED_PROC_NAMESPACE_AND_PERMISSIONS"}


def unit(name, command=_command):
    p = command("systemctl", "--system", "show", name, "--no-pager",
                "--property=" + ",".join(FIELDS))
    if p.returncode:
        return unknown()
    values = {}
    for line in p.stdout.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key in values or key not in FIELDS:
            return unknown()
        values[key] = value
    # systemd normally omits properties that are unset (notably DeviceAllow,
    # and service-only properties for socket/timer units). Do not discard known
    # ActiveState and UnitFileState because an optional property was absent.
    mandatory = {"LoadState", "ActiveState", "UnitFileState"}
    if not mandatory <= values.keys():
        return unknown()
    values["property_coverage"] = ("COMPLETE" if set(values) == set(FIELDS)
                                   else "PARTIAL_UNREPORTED_FIELDS")
    values["unreported_fields"] = sorted(set(FIELDS) - values.keys())
    return values


def observe(call, *args):
    try:
        return call(*args)
    except Exception:
        # Do not emit exception text, command lines, environments or secrets.
        return unknown()


def audit(*, device_reader=device, user_reader=membership,
          process_reader=processes, unit_reader=unit):
    checks = {
        "devices": {p: observe(device_reader, p) for p in DEVICE_NODES},
        "nss": {u: observe(user_reader, u) for u in USERS},
        "inherited_gpu_groups": observe(process_reader),
        "units": {u: observe(unit_reader, u) for u in UNITS},
        "scope": "FIXED_NODES_AND_KNOWN_SYSTEM_UNITS_ONLY",
        "unverified": ["host proc visibility", "alternative nodes and ACL grants",
                       "user units, cron and other autostart", "containers and Docker access",
                       "trusted system-manager positive/negative acceptance"],
    }
    return Boundary(1, "BLOCKED", "UNVERIFIED", "NOT_VERIFIED", checks)


def main():
    print(json.dumps(audit().as_dict(), indent=2, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
