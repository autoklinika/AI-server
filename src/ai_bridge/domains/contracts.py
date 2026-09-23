"""Platform composition contract; domain policy stays behind the adapter."""
from typing import Protocol
from fastapi import FastAPI
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database


class DomainAdapter(Protocol):
    domain_id: str

    def install(self, app: FastAPI, settings: Settings, database: Database) -> None: ...
