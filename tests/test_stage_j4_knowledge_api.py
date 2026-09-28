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
        self.rerank_flags = []

    def search(self, query, *, rerank=True):
        self.queries.append(query)
        self.rerank_flags.append(rerank)
        return KnowledgeSearchResult(
            request_id=query.request_id,
            results=self.results[:query.limit],
            backend="knowledge-primary",
            duration_ms=4.2,
            backend_metadata={"reranker": "technical-evidence-v2"},
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
            "rerank": {
                "method": "technical-evidence-v2",
                "evidence_token_coverage": 1.0,
                "source_token_coverage": 0.0,
                "identifier_coverage": 1.0,
                "phrase_match": False,
                "source_phrase_match": False,
            },
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


def test_ask_history_keeps_last_ten_and_reopens_full_response(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, _runtimes, provider, _snapshot):
            for index in range(12):
                response = await http.post("/api/v1/knowledge/ask", json={
                    "query": f"Pytanie historyczne {index}",
                    "mode": "hybrid",
                    "context": {"domain": "ecu-repair"},
                })
                assert response.status_code == 200, response.text

            history = await http.get("/api/v1/knowledge/history")
            assert history.status_code == 200, history.text
            payload = history.json()
            assert payload["retention"] == {
                "persistent": False,
                "limit": 10,
                "scope": "platform-runtime",
            }
            assert len(payload["history"]) == 10
            assert payload["history"][0]["query"] == "Pytanie historyczne 11"
            assert payload["history"][-1]["query"] == "Pytanie historyczne 2"
            assert payload["history"][0]["citation_count"] == 1
            assert payload["history"][0]["domain"] == "ecu-repair"

            history_id = payload["history"][0]["history_id"]
            detail = await http.get(f"/api/v1/knowledge/history/{history_id}")
            assert detail.status_code == 200, detail.text
            item = detail.json()["item"]
            assert item["query"] == "Pytanie historyczne 11"
            assert item["response"]["answer"] == "Przyczyną był uszkodzony przewód."
            assert item["response"]["citations"][0]["ref"] == "S1"

            missing = await http.get("/api/v1/knowledge/history/kh_missing")
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "not_found"

            traces = (await http.get("/api/v1/traces")).json()["traces"]
            assert all(item["route"] not in {
                "/knowledge/history",
                "/knowledge/history/{history_id}",
            } for item in traces)
            assert len(provider.calls) == 12

    asyncio.run(run())


def test_document_original_and_provenance_are_openable_inline(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, _runtimes, _provider, snapshot):
            doc_id = snapshot.document.document_id

            provenance = await http.get(
                f"/api/v1/knowledge/documents/{doc_id}/provenance"
            )
            assert provenance.status_code == 200, provenance.text
            source = provenance.json()["provenance"]
            assert source["document_id"] == doc_id
            assert source["direct_original"]["relationship"] == "exact_knowledge_document"
            assert source["direct_original"]["media_kind"] == "text"
            assert source["related_originals"] == []
            assert source["provenance_policy"]["exact_relationships_only"] is True

            original = await http.get(
                f"/api/v1/knowledge/documents/{doc_id}/original"
            )
            assert original.status_code == 200, original.text
            assert original.content.startswith(b"# Case")
            assert original.headers["content-type"].startswith("text/markdown")
            assert original.headers["content-disposition"].startswith("inline;")
            assert original.headers["cache-control"] == "private, no-store"

    asyncio.run(run())


def test_technical_conversation_turn_owns_session_context(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, runtimes, _provider, _snapshot):
            first = await http.post("/api/v1/conversation/turn", json={
                "message": "Co było przyczyną SPN 107 FMI 3?",
                "client_id": "discord",
                "context": {"domain": "ecu-repair"},
            })
            assert first.status_code == 200, first.text
            data = first.json()
            conversation_id = data["conversation_id"]
            assert conversation_id.startswith("conv_")
            assert data["client_id"] == "discord"
            assert data["contextualized"] is False
            assert data["answer"] == "Przyczyną był uszkodzony przewód."

            second = await http.post("/api/v1/conversation/turn", json={
                "conversation_id": conversation_id,
                "message": "A gdzie dokładnie?",
                "client_id": "stackchan",
                "context": {"domain": "ecu-repair"},
            })
            assert second.status_code == 200, second.text
            assert second.json()["conversation_id"] == conversation_id
            assert second.json()["contextualized"] is True
            assert "Kontekst poprzedniego pytania" in runtimes[-1].queries[-1].query
            assert "SPN 107 FMI 3" in runtimes[-1].queries[-1].query

            history = await http.get(f"/api/v1/conversation/{conversation_id}")
            assert history.status_code == 200
            turns = history.json()["conversation"]["turns"]
            assert [turn["role"] for turn in turns] == [
                "user", "assistant", "user", "assistant"
            ]
            assert turns[0]["client_id"] == "discord"
            assert turns[2]["client_id"] == "stackchan"
            assert history.json()["retention"]["scope"] == "platform-runtime"

            conflict = await http.post("/api/v1/conversation/turn", json={
                "conversation_id": conversation_id,
                "message": "Konflikt",
                "context": {"domain": "ecu-repair", "session_id": "other_session"},
            })
            assert conflict.status_code == 400
            assert conflict.json()["error"]["code"] == "invalid_request"

    asyncio.run(run())


def test_technical_conversation_rejects_unrelated_retrieval_before_llm(tmp_path):
    unrelated = KnowledgeResult(
        result_id="noise",
        text="Ogólna notatka warsztatowa bez odpowiedzi na pytanie.",
        source=KnowledgeSource(
            type="github",
            uri="repo://docs/noise.md",
            title="Notatki warsztatowe",
        ),
        score=0.9,
        metadata={
            "chunk_id": "noise",
            "document_id": "kdoc_noise",
            "rerank": {
                "method": "technical-evidence-v2",
                "evidence_token_coverage": 0.0,
                "source_token_coverage": 0.0,
                "identifier_coverage": 0.0,
                "phrase_match": False,
                "source_phrase_match": False,
            },
        },
    )

    async def run():
        provider = FakeProvider()
        async with api_client(
            tmp_path,
            provider=provider,
            results=(unrelated,),
        ) as (http, _runtimes, _provider, _snapshot):
            result = await http.post("/api/v1/conversation/turn", json={
                "message": "Jaka jest stolica Francji?",
                "client_id": "discord",
                "context": {"domain": "ecu-repair"},
            })
            assert result.status_code == 200, result.text
            data = result.json()
            assert data["insufficient_context"] is True
            assert data["citations"] == []
            assert data["execution"] is None
            assert data["retrieval"]["grounding_guard"] == "rejected"
            assert provider.calls == []

    asyncio.run(run())


def test_search_can_disable_reranker_for_benchmark_track(tmp_path):
    async def run():
        async with api_client(tmp_path) as (http, runtimes, provider, _snapshot):
            response = await http.post("/api/v1/knowledge/search", json={
                "query": "0 281 007 439",
                "mode": "hybrid",
                "rerank": False,
                "context": {
                    "domain": "ecu-repair",
                    "request_id": "req_raw_retrieval",
                },
            })
            assert response.status_code == 200, response.text
            assert provider.calls == []
            assert runtimes[-1].rerank_flags == [False]

            response = await http.post("/api/v1/knowledge/search", json={
                "query": "0 281 007 439",
                "mode": "hybrid",
                "context": {
                    "domain": "ecu-repair",
                    "request_id": "req_reranked_retrieval",
                },
            })
            assert response.status_code == 200, response.text
            assert runtimes[-1].rerank_flags == [True]
    asyncio.run(run())
