from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
STAGE_K = ROOT / "deploy" / "stage-k"
sys.path.insert(0, str(STAGE_K))

import k3_recipients as recipients


def test_active_yubikey_recipient_metadata(tmp_path: Path) -> None:
    path = tmp_path / "recipients.txt"
    path.write_text(recipients.ACTIVE_YUBIKEY_RECIPIENTS[0] + "\n")

    metadata = recipients.yubikey_metadata(path, require_active=True)

    assert metadata["recipient_type"] == "age-plugin-yubikey"
    assert metadata["recipient_count"] == 1
    assert metadata["recipients"] == list(recipients.ACTIVE_YUBIKEY_RECIPIENTS)
    assert len(metadata["recipients_sha256"]) == 64


def test_unknown_yubikey_recipient_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "recipients.txt"
    path.write_text("age1yubikey1unknown\n")

    with pytest.raises(recipients.RecipientError, match="unaccepted"):
        recipients.yubikey_metadata(path)


def test_duplicate_recipient_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "recipients.txt"
    recipient = recipients.ACTIVE_YUBIKEY_RECIPIENTS[0]
    path.write_text(f"{recipient}\n{recipient}\n")

    with pytest.raises(recipients.RecipientError, match="duplicates"):
        recipients.recipient_lines(path)


def test_future_multi_recipient_digest_is_order_independent() -> None:
    a = "age1yubikey1alpha"
    b = "age1yubikey1beta"
    assert recipients.recipient_set_sha256([a, b]) == recipients.recipient_set_sha256([b, a])
