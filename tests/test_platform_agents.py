from pathlib import Path
import os
import time

from ai_bridge.platform.agents import agents_snapshot


def test_agents_snapshot_is_bounded_and_parses_known_statuses(tmp_path: Path):
    root = tmp_path
    (root / "stage-eh/stage-E").mkdir(parents=True)
    (root / "stage-i").mkdir()
    (root / "stage-j-production").mkdir()

    (root / "stage-eh/stage-E/status").write_text(
        "BLOCKED_ROLLED_BACK 2026-09-22T22:43:39+02:00\nsecret prompt must not leak\n",
        encoding="utf-8",
    )
    (root / "stage-i/status").write_text("COMPLETE\n", encoding="utf-8")
    (root / "stage-j-production/progress").write_text("90_finalize.sh\n", encoding="utf-8")

    snapshot = agents_snapshot(root)
    rows = {item["agent_id"]: item for item in snapshot["agents"]}

    assert rows["stage-e"]["state"] == "BLOCKED_ROLLED_BACK"
    assert rows["stage-e"]["terminal"] is True
    assert rows["stage-i"]["state"] == "COMPLETE"
    assert rows["stage-i"]["terminal"] is True
    assert rows["stage-j-production"]["state"] == "LAST_STEP"
    assert rows["stage-j-production"]["step"] == "90_finalize.sh"
    assert "secret" not in str(snapshot)
    assert snapshot["retention"]["raw_logs_exposed"] is False


def test_agents_snapshot_marks_old_status_historical(tmp_path: Path):
    (tmp_path / "stage-i").mkdir()
    status = tmp_path / "stage-i/status"
    status.write_text("COMPLETE\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(status, (old, old))

    snapshot = agents_snapshot(tmp_path)
    assert snapshot["agents"][0]["freshness"] == "historical"
