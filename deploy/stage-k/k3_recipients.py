#!/usr/bin/env python3
"""Recipient policy helpers for Stage K encrypted secrets backups."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

LEGACY_SSH_RECIPIENT_FINGERPRINT = (
    "SHA256:BVPwRUzB0IbP/6QVNsy9/XbIxs8MxHxbvFJ6soFNUPM"
)
YUBIKEY_RECIPIENT_PREFIX = "age1yubikey1"

# Accepted historical/current YubiKey recipients. Never remove an entry while
# backups encrypted to it remain inside the supported retention/recovery set.
ACCEPTED_YUBIKEY_RECIPIENTS = frozenset({
    "age1yubikey1q2elzda6tkh22ls78d7e54c7tfhgcfrnjpqw5mdmfynhnph4ywam6sd9f06",
})

# Exact recipient set used for newly-created backups.
ACTIVE_YUBIKEY_RECIPIENTS = tuple(sorted(ACCEPTED_YUBIKEY_RECIPIENTS))


class RecipientError(RuntimeError):
    pass
def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipientError(message)


def recipient_lines(path: Path) -> list[str]:
    lines = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    require(bool(lines), "recipient file has no recipients")
    require(len(lines) == len(set(lines)), "recipient file contains duplicates")
    return lines


def canonical_recipient_text(lines: list[str]) -> str:
    return "\n".join(sorted(lines)) + "\n"


def recipient_set_sha256(lines: list[str]) -> str:
    return hashlib.sha256(canonical_recipient_text(lines).encode()).hexdigest()


def validate_yubikey_recipients(
    lines: list[str], *, require_active: bool = False
) -> list[str]:
    require(
        all(line.startswith(YUBIKEY_RECIPIENT_PREFIX) for line in lines),
        "non-YubiKey recipient found",
    )
    unsupported = set(lines) - ACCEPTED_YUBIKEY_RECIPIENTS
    require(not unsupported, f"unaccepted YubiKey recipient(s): {sorted(unsupported)}")
    if require_active:
        require(
            set(lines) == set(ACTIVE_YUBIKEY_RECIPIENTS),
            "recipient set does not match active Stage K recovery policy",
        )
    return sorted(lines)


def yubikey_metadata(path: Path, *, require_active: bool = False) -> dict[str, object]:
    lines = validate_yubikey_recipients(
        recipient_lines(path), require_active=require_active
    )
    return {
        "recipient_type": "age-plugin-yubikey",
        "recipient_count": len(lines),
        "recipients": lines,
        "recipients_sha256": recipient_set_sha256(lines),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("validate-active", "inspect"))
    parser.add_argument("recipient_file", type=Path)
    args = parser.parse_args()
    try:
        metadata = yubikey_metadata(
            args.recipient_file, require_active=args.action == "validate-active"
        )
    except (OSError, RecipientError) as exc:
        raise SystemExit(f"recipient validation failed: {exc}") from exc
    print(json.dumps(metadata, sort_keys=True))


if __name__ == "__main__":
    main()
