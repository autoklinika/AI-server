"""Read-only benchmark catalog and historical-result projection.

Benchmark execution is deliberately not implemented here. Runs that consume AI
resources must later enter the shared Resource Manager/job lifecycle.
"""
from __future__ import annotations

import json
from pathlib import Path


class BenchmarkCatalog:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[3] / "benchmarks"

    def list_suites(self) -> list[dict]:
        knowledge_runs = self._knowledge_files()
        ventilation = self.root / "qwen_ventilation"
        validation_count = len(list(ventilation.glob("VALIDATION_*.md"))) if ventilation.is_dir() else 0
        return [
            {
                "suite_id": "knowledge-retrieval",
                "name": "Knowledge Retrieval",
                "category": "Knowledge / Embeddings",
                "status": "ready",
                "run_count": len(knowledge_runs),
                "capabilities": ["historical-results", "retrieval-metrics"],
            },
            {
                "suite_id": "qwen-ventilation",
                "name": "Qwen Ventilation",
                "category": "Domain LLM",
                "status": "legacy-results",
                "run_count": validation_count,
                "capabilities": ["historical-artifacts"],
            },
            {
                "suite_id": "decision-models",
                "name": "Decision Models",
                "category": "Routers / Policy",
                "status": "planned",
                "run_count": 0,
                "capabilities": ["routing", "tool-selection", "multilingual-pl"],
            },
            {
                "suite_id": "vision",
                "name": "Vision",
                "category": "Vision",
                "status": "planned",
                "run_count": 0,
                "capabilities": ["image-analysis"],
            },
            {
                "suite_id": "automotive-reasoning",
                "name": "Automotive Reasoning",
                "category": "Automotive",
                "status": "planned",
                "run_count": 0,
                "capabilities": ["ecu-reasoning"],
            },
            {
                "suite_id": "rag-knowledge",
                "name": "RAG / Knowledge",
                "category": "RAG",
                "status": "planned",
                "run_count": 0,
                "capabilities": ["rag-quality", "citations"],
            },
        ]

    def list_runs(self, suite_id: str) -> list[dict]:
        if suite_id == "knowledge-retrieval":
            return [self._knowledge_summary(path) for path in reversed(self._knowledge_files())]
        if suite_id == "qwen-ventilation":
            directory = self.root / "qwen_ventilation"
            if not directory.is_dir():
                return []
            return [
                {
                    "run_id": path.stem.lower().replace("_", "-"),
                    "artifact": path.name,
                    "format": "markdown",
                    "status": "historical",
                }
                for path in sorted(directory.glob("VALIDATION_*.md"), reverse=True)
            ]
        if suite_id in {"decision-models", "vision", "automotive-reasoning", "rag-knowledge"}:
            return []
        raise KeyError(suite_id)

    def get_run(self, suite_id: str, run_id: str) -> dict:
        for run in self.list_runs(suite_id):
            if run["run_id"] == run_id:
                if suite_id != "knowledge-retrieval":
                    return run
                path = self.root / "knowledge" / "results" / run["artifact"]
                payload = self._read_json(path)
                variants = []
                for item in payload.get("results", []):
                    metrics = item.get("metrics") or {}
                    latency = item.get("latency_ms") or {}
                    variants.append({
                        "model": item.get("model"),
                        "chunk_max_chars": item.get("chunk_max_chars"),
                        "documents": item.get("documents"),
                        "chunks": item.get("chunks"),
                        "dimensions": item.get("dimensions"),
                        "metrics": {
                            key: metrics.get(key)
                            for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr")
                        },
                        "latency_ms": {
                            "search_avg": latency.get("search_avg"),
                            "query_embedding_total": latency.get("query_embedding_total"),
                        },
                    })
                return {**run, "variants": variants}
        raise KeyError(run_id)

    def _knowledge_files(self) -> list[Path]:
        directory = self.root / "knowledge" / "results"
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("*.json") if path.is_file())

    def _knowledge_summary(self, path: Path) -> dict:
        payload = self._read_json(path)
        return {
            "run_id": path.stem.lower().replace("_", "-"),
            "artifact": path.name,
            "format": "json",
            "status": "historical",
            "queries": payload.get("queries"),
            "duration_seconds": payload.get("duration_seconds"),
            "variant_count": len(payload.get("results") or []),
            "ecu_source_commit": payload.get("ecu_source_commit"),
            "ai_server_commit": payload.get("ai_server_commit"),
        }

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.is_file() or path.suffix != ".json":
            raise KeyError(path.name)
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not isinstance(value.get("results"), list):
            raise ValueError("unsupported benchmark result")
        return value
