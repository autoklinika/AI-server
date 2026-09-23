import httpx

from ai_bridge.ollama.client import OllamaClient


def _success_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen3.6:35b",
            "message": {"role": "assistant", "content": '{"status":"ok"}'},
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration": 123,
        },
        request=httpx.Request("POST", "http://gateway/api/chat"),
    )


def test_gateway_metadata_is_sent_as_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaClient(
        base_url="http://127.0.0.1:11435",
        request_source="ventilation",
        request_priority=10,
    )
    result = client.chat_structured(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "object"},
    )

    assert result.content == '{"status":"ok"}'
    assert captured["headers"] == {
        "X-AI-Source": "ventilation",
        "X-AI-Priority": "10",
    }


def test_direct_ollama_client_does_not_add_gateway_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaClient(base_url="http://127.0.0.1:11434")
    client.chat_structured(
        model="qwen3.6:35b",
        messages=[{"role": "user", "content": "test"}],
        response_schema={"type": "object"},
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"


def test_embedding_request_uses_gateway_headers_and_validates_vectors(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(
            200,
            json={
                "model": "qwen3-embedding:0.6b",
                "embeddings": [[0.1, 0.2, 0.3]],
                "prompt_eval_count": 4,
                "total_duration": 2_000_000,
            },
            request=httpx.Request("POST", "http://gateway/api/embed"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = OllamaClient(
        base_url="http://127.0.0.1:11435",
        request_source="knowledge-embedding",
        request_priority=100,
    )
    result = client.embed(
        model="qwen3-embedding:0.6b",
        inputs=("SPN 107",),
        keep_alive="5m",
    )

    assert captured["url"] == "http://127.0.0.1:11435/api/embed"
    assert captured["headers"] == {
        "X-AI-Source": "knowledge-embedding",
        "X-AI-Priority": "100",
    }
    assert captured["json"] == {
        "model": "qwen3-embedding:0.6b",
        "input": ["SPN 107"],
        "truncate": True,
        "keep_alive": "5m",
    }
    assert result.embeddings == ((0.1, 0.2, 0.3),)
