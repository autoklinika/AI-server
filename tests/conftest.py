from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_bridge.api.app import create_app
from ai_bridge.settings import Settings
from ai_bridge.storage.models import Base


@pytest.fixture(autouse=True)
def isolated_gpu_marker(monkeypatch, tmp_path):
    # Offline Gateway tests must never inherit or clear an operator's real latch.
    monkeypatch.setenv("AI_BRIDGE_GATEWAY_GPU_MARKER", str(tmp_path / "gpu.blocked"))


@pytest.fixture
def client():
    application = create_app(
        Settings(
            database_url="sqlite+pysqlite://",
            telemetry_max_body_bytes=1_048_576,
        )
    )
    with TestClient(application) as test_client:
        Base.metadata.create_all(application.state.database.engine)
        yield test_client
