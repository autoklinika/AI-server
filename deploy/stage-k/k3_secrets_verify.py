#!/usr/bin/env python3
"""Offline verification of an encrypted Stage K K3 secrets bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

EXPECTED_RECIPIENT_FINGERPRINT = "SHA256:BVPwRUzB0IbP/6QVNsy9/XbIxs8MxHxbvFJ6soFNUPM"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify(directory: Path) -> dict[str, object]:
    directory = directory.resolve()
    complete = directory / "COMPLETE"
    manifest_path = directory / "manifest.json"
    checksum_path = directory / "manifest.sha256"
    recipients = directory / "recipients.txt"

    require(complete.is_file(), "COMPLETE marker missing")
    require(manifest_path.is_file(), "manifest.json missing")
    require(checksum_path.is_file(), "manifest.sha256 missing")
    require(recipients.is_file(), "recipients.txt missing")

    expected_manifest = checksum_path.read_text().split()[0]
    require(re.fullmatch(r"[0-9a-f]{64}", expected_manifest) is not None,
            "invalid manifest checksum")
    require(sha256(manifest_path) == expected_manifest, "manifest checksum mismatch")

    manifest = json.loads(manifest_path.read_text())
    require(manifest.get("status") == "COMPLETE", "manifest status mismatch")
    require(manifest.get("domain") == "PlatformSecrets", "invalid domain")
    require(complete.read_text().strip() == manifest.get("backup_id"),
            "COMPLETE marker mismatch")
    require(manifest.get("plaintext_written_to_nas") is False,
            "manifest reports plaintext on NAS")
    require(manifest.get("plaintext_temp_bundle_created") is False,
            "manifest reports plaintext temp bundle")

    encryption = manifest["encryption"]
    require(encryption.get("format") == "age", "unexpected encryption format")
    require(encryption.get("recipient_type") == "ssh-ed25519",
            "unexpected recipient type")
    require(encryption.get("private_key_stored_on_ai_server") is False,
            "private key must not be stored on AI Server")
    require(encryption.get("private_key_stored_on_nas") is False,
            "private key must not be stored on NAS")

    bundle_meta = manifest["bundle"]
    bundle = directory / str(bundle_meta["path"])
    require(bundle.resolve().parent == directory, "bundle path escapes set")
    require(bundle.is_file(), "encrypted bundle missing")
    require(bundle.stat().st_size == int(bundle_meta["bytes"]),
            "encrypted bundle size mismatch")
    require(sha256(bundle) == bundle_meta["sha256"],
            "encrypted bundle checksum mismatch")
    with bundle.open("rb") as stream:
        first_line = stream.readline().decode("ascii", errors="replace").rstrip("\n")
    require(first_line == "age-encryption.org/v1", "invalid age bundle header")

    fingerprint = subprocess.check_output(
        ["ssh-keygen", "-lf", str(recipients)], text=True
    ).strip()
    require(fingerprint == encryption["recipient_fingerprint"],
            "recipient fingerprint mismatch")
    fields = fingerprint.split()
    require(len(fields) >= 2 and fields[1] == EXPECTED_RECIPIENT_FINGERPRINT,
            "recipient is not the accepted recovery key")

    allowed = {
        "COMPLETE",
        "manifest.json",
        "manifest.sha256",
        "recipients.txt",
        "secrets.tar.gz.age",
    }
    actual = {p.name for p in directory.iterdir()}
    require(actual == allowed, f"unexpected files in secrets set: {sorted(actual - allowed)}")

    source_paths = [str(item["path"]) for item in manifest["sources"]]
    require("/etc/ai-bridge/ai-bridge.env" in source_paths,
            "ai-bridge secrets not represented")
    require("/etc/ai-gateway/ai-gateway.env" in source_paths,
            "ai-gateway secrets not represented")
    require("/srv/ai-data/hermes/.env" in source_paths,
            "Hermes env not represented")
    require("/srv/ai-data/hermes/auth.json" in source_paths,
            "Hermes auth not represented")
    require("/etc/ai-platform/stage-k/globalnas.credentials" in source_paths,
            "GlobalNAS credential not represented")

    return {
        "status": "PASS",
        "domain": manifest["domain"],
        "backup_id": manifest["backup_id"],
        "bundle_bytes": bundle.stat().st_size,
        "bundle_sha256": bundle_meta["sha256"],
        "recipient_fingerprint": fingerprint,
        "source_entries": len(source_paths),
        "private_key_on_ai_server": False,
        "private_key_on_nas": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.bundle_dir), sort_keys=True))


if __name__ == "__main__":
    main()

