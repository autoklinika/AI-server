import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.knowledge.canonical import (
    chunk_record,
    document_record,
    document_version_record,
    sha256_text,
    source_record,
)
from ai_bridge.knowledge.storage.repository import KnowledgeDocumentSnapshot
from ai_bridge.providers.contracts import (
    KnowledgeResult,
    KnowledgeSearchResult,
    KnowledgeSource,
    LLMResponse,
)
from ai_bridge.settings import Settings


class FakeRuntime:
    def __init__(self, snapshot, results):
        self.snapshot = snapshot
        self.results = results
        self.closed = False
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=self.results[:query.limit],
            backend="knowledge-primary",
            duration_ms=4.2,
            backend_metadata={"reranker": "technical-evidence-v1"},
        )

    def get_document(self, document_id):
        if document_id != self.snapshot.document.document_id:
            raise KeyError(document_id)
        return self.snapshot

    def close(self):
        self.closed = True


class FakeProvider:
    provider_id = "ollama-local"
    node_id = "ai-node-01"

    def __init__(self, content=None):
        self.content = content or json.dumps({
            "claims": [{
                "text": "Przyczyną był uszkodzony przewód.",
                "source_refs": ["S1"],
            }],
            "insufficient_context": False,
            "insufficiency_reason": None,
        })
        self.calls = []

    async def generate(self, request):
        self.calls.append(request)
        return LLMResponse(request_id=request.request_id, content=self.content)

    async def ready(self):
        return True


def fixture_data(tmp_path: Path):
    root = tmp_path / "objects"
    root.mkdir(exist_ok=True)
    raw = b"# Case\n\nSPN 107 FMI 3 - uszkodzony przewod."
    digest = sha256_text(raw.decode())
    object_path = root / "sha256" / digest[:2] / digest
    object_path.parent.mkdir(parents=True, exist_ok=True)
    object_path.write_bytes(raw)

    source = source_record(
        domain="ecu-repair",
        namespace="ecu-repair",
        source_type="documentation",
        uri="github://autoklinika/EcuRepairService",
        title="EcuRepairService",
    )
    document = document_record(
        source,
        uri="github://autoklinika/EcuRepairService/case.md",
        title="CASE-0001",
        media_type="text/markdown",
    )
    version = document_version_record(
        document,
        content_sha256=digest,
        byte_size=len(raw),
        storage_uri=object_path.as_uri(),
        source_revision="abc123",
    )
    chunk = chunk_record(
        version,
        ordinal=0,
        text="SPN 107 FMI 3. Root cause: uszkodzony przewód.",
        chunk_profile="md-heading-2400-v1",
        locator={"section": "Root cause"},
    )
    snapshot = KnowledgeDocumentSnapshot(
        source=source,
        document=document,
        version=version,
        chunks=(chunk,),
    )
    result = KnowledgeResult(
        result_id=chunk.chunk_id,
        text=chunk.text,
        source=KnowledgeSource(
            type="documentation",
            uri=document.uri,
            title=document.title,
        ),
        score=0.99,
        metadata={
            "source_id": source.source_id,
            "document_id": document.document_id,
            "version_id": version.version_id,
            "chunk_id": chunk.chunk_id,
            "section": "Root cause",
            "rerank": {"method": "technical-evidence-v1"},
        },
    )
    return root, snapshot, (result,)


@asynccontextmanager
async def api_client(tmp_path, provider=None, results=None):
    root, snapshot, default_results = fixture_data(tmp_path)
    runtimes = []

    def factory():
        runtime = FakeRuntime(snapshot, default_results if results is None else results)
        runtimes.append(runtime)
        return runtime

    resolved_provider = provider or FakeProvider()
    settings = Settings(
        ollama_model="private-model",
        knowledge_object_store_dir=root,
    )
    app = create_gateway_app(
        settings,
        upstream_transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"models": [{"name": "private-model"}]}
                if request.url.path == "/api/tags"
                else {"done": True, "message": {"content": "unused"}},
            )
        ),
        platform_provider=resolved_provider,
        knowledge_runtime_factory=factory,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, client=("127.0.0.1", 123)),
            base_url="http://platform",
        ) as http:
            yield http, runtimes, resolved_provider, snapshot


def test_search_is_raw_retrieval_and_ask_is_cited_rag(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, runtimes, provider, snapshot):
            search = await http.post("/api/v1/knowledge/search", json={
                "query": "SPN 107 FMI 3",
                "mode": "hybrid",
                "context": {"domain": "ecu-repair", "request_id": "req_search"},
            })
            assert search.status_code == 200, search.text
            data = search.json()
            assert data["request_id"] == "req_search"
            assert data["backend"] == "knowledge-primary"
            assert data["results"][0]["metadata"]["document_id"] == snapshot.document.document_id
            assert provider.calls == []
            assert "ollama" not in search.text and "qdrant" not in search.text

            ask = await http.post("/api/v1/knowledge/ask", json={
                "query": "Co było przyczyną SPN 107 FMI 3?",
                "mode": "hybrid",
                "context": {"domain": "ecu-repair", "request_id": "req_ask"},
            })
            assert ask.status_code == 200, ask.text
            answer = ask.json()
            assert answer["answer"] == "Przyczyną był uszkodzony przewód."
            assert answer["claims"][0]["source_refs"] == ["S1"]
            assert answer["citations"][0]["ref"] == "S1"
            assert answer["citations"][0]["document_id"] == snapshot.document.document_id
            assert answer["execution"]["model"] == "reasoning-main"
            assert "ollama-local" not in ask.text and "private-model" not in ask.text
            assert len(provider.calls) == 1
            assert provider.calls[0].capability == "structured-generation"
            assert "Use ONLY" in provider.calls[0].messages[0]["content"]
            assert all(runtime.closed for runtime in runtimes)
    asyncio.run(run())


def test_document_metadata_and_content_are_openable(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, _runtimes, _provider, snapshot):
            doc_id = snapshot.document.document_id
            meta = await http.get(f"/api/v1/knowledge/documents/{doc_id}")
            assert meta.status_code == 200
            data = meta.json()
            assert data["document"]["title"] == "CASE-0001"
            assert data["chunks"][0]["locator"]["section"] == "Root cause"

            content = await http.get(f"/api/v1/knowledge/documents/{doc_id}/content")
            assert content.status_code == 200
            assert content.content.startswith(b"# Case")
            assert "storage_uri" not in meta.text
    asyncio.run(run())


def test_ask_rejects_unknown_citation_and_skips_llm_when_no_sources(tmp_path):
    async def run():
        bad_provider = FakeProvider(json.dumps({
            "claims": [{"text": "Invented", "source_refs": ["S99"]}],
            "insufficient_context": False,
            "insufficiency_reason": None,
        }))
        async with api_client(tmp_path, provider=bad_provider) as (http, _r, _p, _s):
            bad = await http.post("/api/v1/knowledge/ask", json={
                "query": "Question",
                "context": {"domain": "ecu-repair"},
            })
            assert bad.status_code == 502
            assert bad.json()["error"]["code"] == "rag_invalid_response"

        provider = FakeProvider()
        async with api_client(tmp_path, provider=provider, results=()) as (http, _r, _p, _s):
            empty = await http.post("/api/v1/knowledge/ask", json={
                "query": "Unknown",
                "context": {"domain": "ecu-repair"},
            })
            assert empty.status_code == 200
            assert empty.json()["insufficient_context"] is True
            assert empty.json()["citations"] == []
            assert provider.calls == []
    asyncio.run(run())
