"""Content-free production history/freshness evidence. Never fabricates live data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import select, func
from ai_bridge.settings import Settings
from ai_bridge.storage.database import Database
from ai_bridge.storage.models import TelemetryBatchRecord, TelemetrySampleRecord, VentilationAnalysisRunRecord


def inventory(db, prior=None):
    tables = {}
    with db.session() as session:
        for model in (TelemetryBatchRecord, TelemetrySampleRecord, VentilationAnalysisRunRecord):
            table = model.__table__
            maximum = session.scalar(select(func.max(table.c.id))) or 0
            count = session.scalar(select(func.count()).select_from(table))
            bound = prior[table.name]['max_id'] if prior else maximum
            digest = hashlib.sha256()
            for row in session.execute(select(table).where(table.c.id <= bound).order_by(table.c.id)).mappings():
                digest.update(json.dumps(dict(row), sort_keys=True, default=str, separators=(',', ':')).encode())
                digest.update(b'\n')
            tables[table.name] = {'count': count, 'max_id': maximum, 'historical_sha256': digest.hexdigest(), 'bound': bound}
            if prior:
                assert count >= prior[table.name]['count'] and digest.hexdigest() == prior[table.name]['historical_sha256']
        latest = session.scalar(select(func.max(TelemetrySampleRecord.captured_at)))
    return {'tables': tables, 'latest_captured_at': str(latest), 'history': 'PRESERVED' if prior else 'BASELINE'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--freshness', action='store_true')
    args = parser.parse_args()
    settings = Settings(_env_file='/etc/ai-bridge/ai-bridge.env')
    database = Database(settings.database_url)
    try:
        prior = json.loads(sys.stdin.read() if str(args.baseline) == '-' else args.baseline.read_text())['tables'] if args.baseline else None
        evidence = inventory(database, prior)
        if args.freshness:
            from ai_bridge.domains.wvc.analysis.service import aligned_window
            from ai_bridge.domains.wvc.analysis.service_v12_2 import VentilationAnalysisServiceV122
            from ai_bridge.domains.wvc.profiles.analysis_v12_2 import ANALYSIS_THINK
            from ai_bridge.domains.wvc.storage.analysis_repository import VentilationAnalysisRepository
            from ai_bridge.domains.wvc.policy import WVCAnalysisPolicy
            from ai_bridge.providers.ollama import OllamaAdapter
            repository = VentilationAnalysisRepository(database)
            # Always admitted, including this operational probe.
            endpoint = settings.gateway_url.rstrip('/')
            if not endpoint.endswith('/clients/ventilation'):
                endpoint += '/clients/ventilation'
            llm = OllamaAdapter.from_endpoint(base_url=endpoint, default_model=settings.ollama_model,
                timeout_seconds=settings.ollama_analysis_timeout_seconds, request_source='ventilation',
                request_priority=settings.gateway_priority_ventilation, node_id=settings.node_id)
            service = VentilationAnalysisServiceV122(repository=repository, llm=llm, model=settings.ollama_model,
                think=ANALYSIS_THINK, temperature=settings.analysis_temperature, min_samples=settings.analysis_min_samples)
            start, end = aligned_window(datetime.now(timezone.utc), settings.analysis_window_minutes)
            result = WVCAnalysisPolicy(repository, service).run_window(source_id=settings.ventilation_source_id,
                window_start=start, window_end=end)
            evidence['freshness'] = {'status': result.status, 'reason': result.reason,
                'window_start': start.isoformat(), 'window_end': end.isoformat(),
                'advisory_only': True, 'control_actions_supported': False,
                'physical_reconnect': 'NOT TESTED: no physical-device claim'}
        print(json.dumps(evidence, sort_keys=True))
    finally:
        database.dispose()


if __name__ == '__main__':
    main()
