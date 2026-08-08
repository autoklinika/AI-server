from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import EventIn, HistoryPoint, Recommendation, TelemetryBatch


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class Storage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS telemetry_batches (
                    batch_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    timestamp_start TEXT NOT NULL,
                    timestamp_end TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS ux_batch_source_sequence
                    ON telemetry_batches(source, device_id, sequence);

                CREATE TABLE IF NOT EXISTS telemetry_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    measurements_json TEXT NOT NULL,
                    states_json TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES telemetry_batches(batch_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_samples_timestamp
                    ON telemetry_samples(timestamp);

                CREATE TABLE IF NOT EXISTS telemetry_measurements (
                    sample_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    value REAL NOT NULL,
                    FOREIGN KEY(sample_id) REFERENCES telemetry_samples(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS ix_measurements_lookup
                    ON telemetry_measurements(source, metric, timestamp);

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    analysis_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    details_json TEXT NOT NULL
                );
                """
            )

    def store_batch(self, batch: TelemetryBatch) -> tuple[bool, int]:
        received_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM telemetry_batches WHERE batch_id = ?",
                (batch.batch_id,),
            ).fetchone()
            if exists:
                return True, 0

            conn.execute(
                """
                INSERT INTO telemetry_batches (
                    batch_id, schema_version, source, device_id, sequence,
                    timestamp_start, timestamp_end, received_at, sample_count, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch.batch_id,
                    batch.schema_version,
                    batch.source,
                    batch.device_id,
                    batch.sequence,
                    _iso(batch.timestamp_start),
                    _iso(batch.timestamp_end),
                    _iso(received_at),
                    len(batch.samples),
                    batch.model_dump_json(),
                ),
            )

            for sample in batch.samples:
                cursor = conn.execute(
                    """
                    INSERT INTO telemetry_samples (
                        batch_id, timestamp, measurements_json, states_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        batch.batch_id,
                        _iso(sample.timestamp),
                        json.dumps(sample.measurements, separators=(",", ":"), sort_keys=True),
                        json.dumps(sample.states, separators=(",", ":"), sort_keys=True),
                    ),
                )
                sample_id = int(cursor.lastrowid)
                conn.executemany(
                    """
                    INSERT INTO telemetry_measurements (
                        sample_id, source, device_id, timestamp, metric, value
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            sample_id,
                            batch.source,
                            batch.device_id,
                            _iso(sample.timestamp),
                            metric,
                            float(value),
                        )
                        for metric, value in sample.measurements.items()
                    ],
                )

        return False, len(batch.samples)

    def store_event(self, event: EventIn) -> bool:
        received_at = datetime.now(timezone.utc)
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if exists:
                return True
            conn.execute(
                """
                INSERT INTO events (
                    event_id, schema_version, source, device_id, timestamp,
                    severity, event_type, payload_json, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.schema_version,
                    event.source,
                    event.device_id,
                    _iso(event.timestamp),
                    event.severity,
                    event.event_type,
                    json.dumps(event.payload, separators=(",", ":"), sort_keys=True),
                    _iso(received_at),
                ),
            )
        return False

    def history(
        self,
        *,
        metric: str,
        source: str | None,
        device_id: str | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
        limit: int,
    ) -> list[HistoryPoint]:
        clauses = ["metric = ?"]
        params: list[object] = [metric]
        if source:
            clauses.append("source = ?")
            params.append(source)
        if device_id:
            clauses.append("device_id = ?")
            params.append(device_id)
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(_iso(from_ts))
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(_iso(to_ts))
        params.append(limit)

        query = f"""
            SELECT timestamp, source, device_id, metric, value
            FROM telemetry_measurements
            WHERE {' AND '.join(clauses)}
            ORDER BY timestamp ASC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            HistoryPoint(
                timestamp=datetime.fromisoformat(row["timestamp"]),
                source=row["source"],
                device_id=row["device_id"],
                metric=row["metric"],
                value=row["value"],
            )
            for row in rows
        ]

    def latest_recommendation(self, source: str) -> Recommendation | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT analysis_id, source, created_at, summary, confidence, details_json
                FROM recommendations
                WHERE source = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (source,),
            ).fetchone()
        if row is None:
            return None
        return Recommendation(
            analysis_id=row["analysis_id"],
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
            summary=row["summary"],
            confidence=row["confidence"],
            details=json.loads(row["details_json"]),
        )
