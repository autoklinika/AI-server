from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ai_bridge.api.app import create_app
from ai_bridge.settings import Settings
from ai_bridge.storage.models import Base


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
