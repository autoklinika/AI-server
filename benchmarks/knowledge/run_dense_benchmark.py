from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from ai_bridge.knowledge import KnowledgeService
from ai_bridge.knowledge.backends import QdrantKnowledgeBackend
from ai_bridge.providers.contracts import KnowledgeQuery


ECU_ROOT = Path(os.environ.get(
    "ECU_REPAIR_KNOWLEDGE_ROOT",
    "/srv/ai-data/knowledge/source-cache/EcuRepairService",
))
AI_ROOT = Path(__file__).resolve().parents[2]
GATEWAY = os.environ.get("AI_GATEWAY_URL", "http://127.0.0.1:11435")
QDRANT = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_uri: str
    title: str
    text: str
    section: str
    chunk_index: int


@dataclass(frozen=True)
class QueryCase:
    id: str
    query: str
    evidence_groups: tuple[tuple[str, ...], ...]
    kind: str


QUERIES = (
    QueryCase("ecu-spn107-root-cause", "Co było rzeczywistą przyczyną SPN 107 FMI 3 w CASE-0001?", (("uszkodzony przewód",),), "semantic"),
    QueryCase("ecu-spn107-component", "Jaki czujnik i numer Bosch był związany z błędem SPN 107 FMI 3?", (("SPN 107",), ("0 281 007 439",)), "mixed"),
    QueryCase("ecu-afdps-pins", "Na które piny ECU C81 trafiają 5 V, sygnał i masa czujnika AFDPS?", (("K23",), ("K82",), ("K85",)), "semantic"),
    QueryCase("ecu-k82", "Co jest podłączone do pinu K82 sterownika EDC17C81?", (("K82",), ("signal", "sygnał")), "exact"),
    QueryCase("ecu-x6-pinout", "Podaj funkcje pinów 1-4 złącza diagnostycznego X6 Hatz C81.", (("X6",), ("CAN1", "CAN 1"), ("Ground", "GND", "B-")), "mixed"),
    QueryCase("ecu-can-topology", "Czym różni się CAN0 customer-CAN od CAN1 diagnostic CAN w C81?", (("CAN0",), ("CAN1",)), "semantic"),
    QueryCase("ecu-derate", "Po awarii maszyna miała około 1300 rpm zamiast 2400 rpm. Jaki przypadek to opisuje?", (("1300",), ("2400",)), "semantic"),
    QueryCase("ecu-bosch-number", "0 281 007 439", (("0 281 007 439",),), "exact"),
    QueryCase("ecu-clear-dtc", "Gdzie należy szukać warstwy kasowania DTC w Hatz C81 i czego nie wolno zgadywać?", (("CAN1",), ("kasowania DTC", "Clear DTC", "fault memory")), "semantic"),
    QueryCase("ecu-crosslang", "Which bus should be used for service diagnostics on the Hatz C81 instead of the customer J1939 bus?", (("CAN1",), ("diagnostic", "diagnostycz")), "cross-language"),
    QueryCase("wvc-advisory", "Czy WVC może bezpośrednio sterować wentylatorami lub innymi actuatorami?", (("advisory-only",), ("actuator",)), "semantic"),
    QueryCase("wvc-freshness", "Co ma się stać, gdy bieżące okno telemetrii wentylacji nie zawiera świeżych próbek?", (("no_fresh_data",),), "semantic"),
    QueryCase("wvc-replay", "Czy --end-at oznacza aktualną łączność urządzenia czy tylko historyczny replay?", (("--end-at",), ("historical",)), "mixed"),
)


def git_head(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def assert_ecu_cache_clean() -> None:
    origin = subprocess.check_output(
        ["git", "-C", str(ECU_ROOT), "remote", "get-url", "origin"], text=True,
    ).strip()
    if "github.com/autoklinika/EcuRepairService" not in origin:
        raise RuntimeError(f"unexpected ECU benchmark origin: {origin}")
    dirty = subprocess.check_output(
        ["git", "-C", str(ECU_ROOT), "status", "--porcelain"], text=True,
    ).strip()
    if dirty:
        raise RuntimeError("ECU benchmark source cache must remain read-only and clean")


def source_files() -> list[tuple[Path, str]]:
    ecu_head = git_head(ECU_ROOT)
    items: list[tuple[Path, str]] = []
    for path in sorted(ECU_ROOT.rglob("*.md")):
        rel = path.relative_to(ECU_ROOT).as_posix()
        items.append((path, f"github://autoklinika/EcuRepairService@{ecu_head}/{rel}"))

    wvc = AI_ROOT / "docs/architecture/WVC_DOMAIN.md"
    items.append((wvc, "repo://AI-server/docs/architecture/WVC_DOMAIN.md"))
    return items


def _split_large_unit(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        candidate = "\n".join(buffer + [line])
        if buffer and len(candidate) > max_chars:
            pieces.append("\n".join(buffer).strip())
            buffer = [line]
        elif len(line) > max_chars:
            if buffer:
                pieces.append("\n".join(buffer).strip())
                buffer = []
            for start in range(0, len(line), max_chars):
                pieces.append(line[start:start + max_chars].strip())
        else:
            buffer.append(line)
    if buffer:
        pieces.append("\n".join(buffer).strip())
    return [piece for piece in pieces if piece]


def split_markdown(path: Path, uri: str, max_chars: int) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), path.name)
    heading = title
    units: list[tuple[str, str]] = []

    for block in (part.strip() for part in raw.split("\n\n")):
        if not block:
            continue
        first = block.splitlines()[0]
        if first.startswith("#"):
            heading = first.lstrip("# ").strip() or title
        labelled = f"Document: {title}\nSection: {heading}\n\n{block}"
        for piece in _split_large_unit(labelled, max_chars):
            units.append((heading, piece))

    chunks: list[Chunk] = []
    index = 0
    buffer: list[tuple[str, str]] = []

    def flush(items: list[tuple[str, str]]) -> None:
        nonlocal index
        if not items:
            return
        text = "\n\n".join(item[1] for item in items).strip()
        section = items[-1][0]
        digest = hashlib.sha256(f"{uri}\0{index}\0{text}".encode()).hexdigest()[:24]
        chunks.append(Chunk(digest, uri, title, text, section, index))
        index += 1

    for unit in units:
        candidate = "\n\n".join([item[1] for item in buffer] + [unit[1]])
        if buffer and len(candidate) > max_chars:
            previous = buffer[-1] if len(buffer[-1][1]) <= max_chars // 4 else None
            flush(buffer)
            buffer = ([previous] if previous else []) + [unit]
        else:
            buffer.append(unit)
    flush(buffer)
    return chunks


def build_corpus(max_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, uri in source_files():
        chunks.extend(split_markdown(path, uri, max_chars))
    return chunks


QWEN_QUERY_INSTRUCTION = (
    "Given a technical service query, retrieve relevant passages from ECU and "
    "ventilation documentation that answer the query."
)


def query_inputs(model: str, cases: tuple[QueryCase, ...]) -> list[str]:
    if model.startswith("qwen3-embedding"):
        return [
            f"Instruct: {QWEN_QUERY_INSTRUCTION}\nQuery: {case.query}"
            for case in cases
        ]
    return [case.query for case in cases]


def embed(client: httpx.Client, model: str, texts: list[str]) -> tuple[list[list[float]], float]:
    started = time.perf_counter()
    response = client.post(
        "/api/embed",
        json={"model": model, "input": texts, "truncate": True, "keep_alive": "5m"},
    )
    response.raise_for_status()
    data = response.json()
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError(f"invalid embedding response for {model}")
    return vectors, (time.perf_counter() - started) * 1000.0


def qdrant_create(client: httpx.Client, collection: str, dims: int) -> None:
    response = client.put(
        f"/collections/{collection}",
        json={"vectors": {"dense": {"size": dims, "distance": "Cosine"}}},
    )
    response.raise_for_status()


def qdrant_upsert(client: httpx.Client, collection: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        point_id = str(uuid.UUID(hashlib.md5(chunk.chunk_id.encode()).hexdigest()))
        points.append({
            "id": point_id,
            "vector": {"dense": vector},
            "payload": {
                "text": chunk.text,
                "domain": "wvc" if chunk.source_uri.endswith("WVC_DOMAIN.md") else "ecu-repair",
                "namespace": "wvc" if chunk.source_uri.endswith("WVC_DOMAIN.md") else "ecu-repair",
                "source_type": "documentation",
                "source_uri": chunk.source_uri,
                "source_title": chunk.title,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index,
                "benchmark_chunk_id": chunk.chunk_id,
            },
        })
    for start in range(0, len(points), 64):
        response = client.put(
            f"/collections/{collection}/points?wait=true",
            json={"points": points[start:start + 64]},
        )
        response.raise_for_status()


def contains_evidence(text: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    folded = text.casefold()
    return all(any(term.casefold() in folded for term in alternatives) for alternatives in groups)


def score_ranks(ranks: list[int | None]) -> dict[str, float]:
    total = len(ranks)
    return {
        "recall_at_1": sum(rank == 1 for rank in ranks) / total,
        "recall_at_3": sum(rank is not None and rank <= 3 for rank in ranks) / total,
        "recall_at_5": sum(rank is not None and rank <= 5 for rank in ranks) / total,
        "mrr": sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / total,
    }


def run_one(model: str, max_chars: int) -> dict:
    chunks = build_corpus(max_chars)
    collection = "stage_j2_" + hashlib.sha1(f"{model}:{max_chars}".encode()).hexdigest()[:12]

    with httpx.Client(base_url=GATEWAY, timeout=600, trust_env=False) as gateway, \
         httpx.Client(base_url=QDRANT, timeout=60, trust_env=False) as qdrant:
        all_vectors: list[list[float]] = []
        corpus_embed_ms = 0.0
        for start in range(0, len(chunks), 32):
            vectors, elapsed = embed(gateway, model, [c.text for c in chunks[start:start + 32]])
            all_vectors.extend(vectors)
            corpus_embed_ms += elapsed

        dims = len(all_vectors[0])
        qdrant_create(qdrant, collection, dims)
        try:
            qdrant_upsert(qdrant, collection, chunks, all_vectors)
            query_vectors, query_embed_ms = embed(gateway, model, query_inputs(model, QUERIES))
            backend = QdrantKnowledgeBackend(url=QDRANT, collection=collection)
            service = KnowledgeService(backend)
            ranks: list[int | None] = []
            details: list[dict] = []
            search_ms = 0.0
            try:
                for case, vector in zip(QUERIES, query_vectors, strict=True):
                    domain = "wvc" if case.id.startswith("wvc-") else "ecu-repair"
                    started = time.perf_counter()
                    result = service.search(KnowledgeQuery(
                        request_id=f"benchmark-{case.id}",
                        domain=domain,
                        query=case.query,
                        mode="semantic",
                        namespaces=(domain,),
                        source_types=("documentation",),
                        limit=10,
                        query_embedding=tuple(vector),
                    ))
                    elapsed = (time.perf_counter() - started) * 1000.0
                    search_ms += elapsed
                    rank = next(
                        (idx for idx, hit in enumerate(result.results, start=1)
                         if contains_evidence(hit.text, case.evidence_groups)),
                        None,
                    )
                    ranks.append(rank)
                    details.append({
                        "id": case.id,
                        "kind": case.kind,
                        "query": case.query,
                        "rank": rank,
                        "top_sources": [hit.source.uri for hit in result.results[:5]],
                        "top_scores": [round(hit.score, 6) for hit in result.results[:5]],
                    })
            finally:
                backend.close()

            by_kind = {}
            for kind in sorted({case.kind for case in QUERIES}):
                kind_ranks = [rank for rank, case in zip(ranks, QUERIES, strict=True) if case.kind == kind]
                by_kind[kind] = score_ranks(kind_ranks)

            return {
                "model": model,
                "chunk_max_chars": max_chars,
                "documents": len(source_files()),
                "chunks": len(chunks),
                "dimensions": dims,
                "metrics": score_ranks(ranks),
                "metrics_by_kind": by_kind,
                "latency_ms": {
                    "corpus_embedding_total": round(corpus_embed_ms, 3),
                    "query_embedding_total": round(query_embed_ms, 3),
                    "search_total": round(search_ms, 3),
                    "search_avg": round(search_ms / len(QUERIES), 3),
                },
                "queries": details,
            }
        finally:
            qdrant.delete(f"/collections/{collection}").raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=[
        "qwen3-embedding:0.6b",
        "qwen3-embedding:4b",
        "qwen3-embedding:8b",
        "bge-m3",
    ])
    parser.add_argument("--chunk-chars", nargs="+", type=int, default=[1200, 2400])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    assert_ecu_cache_clean()
    started = time.time()
    results = []
    for model in args.models:
        try:
            for chars in args.chunk_chars:
                print(f"BENCH model={model} chunk_chars={chars}", flush=True)
                result = run_one(model, chars)
                results.append(result)
                print(json.dumps({
                    "model": model,
                    "chunk_chars": chars,
                    "dimensions": result["dimensions"],
                    **result["metrics"],
                    **result["latency_ms"],
                }, ensure_ascii=False), flush=True)
        finally:
            subprocess.run(["ollama", "stop", model], check=False, capture_output=True, text=True)

    payload = {
        "schema_version": 1,
        "ecu_source_commit": git_head(ECU_ROOT),
        "ai_server_commit": git_head(AI_ROOT),
        "queries": len(QUERIES),
        "started_unix": started,
        "duration_seconds": round(time.time() - started, 3),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE {args.output}", flush=True)


if __name__ == "__main__":
    main()
