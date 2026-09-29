import asyncio
import json

import httpx

from ai_bridge.platform.provider import GatewayLLMAdapter
from ai_bridge.providers.contracts import LLMRequest


def test_gateway_llm_adapter_forwards_output_token_limit():
    seen = {}

    async def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "done": True,
            "message": {"content": "{\"ok\":true}"},
            "prompt_eval_count": 10,
            "eval_count": 2,
        })

    async def run():
        async with httpx.AsyncClient(
            base_url="http://ollama",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = GatewayLLMAdapter(
                client,
                model="qwen3.6:35b",
                node_id="ai-node-01",
                health_timeout=1.0,
            )
            response = await adapter.generate(LLMRequest(
                request_id="req-output-cap",
                capability="structured-generation",
                messages=[{"role": "user", "content": "test"}],
                response_schema={"type": "object"},
                max_output_tokens=1024,
            ))
            assert response.usage.output_tokens == 2

    asyncio.run(run())
    assert seen["options"]["num_predict"] == 1024


def test_gateway_llm_adapter_keeps_think_false_for_standard_models():
    seen = {}

    async def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "done": True,
            "message": {"content": "{\"ok\":true}"},
            "prompt_eval_count": 1,
            "eval_count": 1,
        })

    async def run():
        async with httpx.AsyncClient(
            base_url="http://ollama",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = GatewayLLMAdapter(
                client, model="qwen3.6:35b",
                node_id="ai-node-01", health_timeout=1.0,
            )
            await adapter.generate(LLMRequest(
                request_id="req-qwen-think",
                capability="structured-generation",
                messages=[{"role": "user", "content": "test"}],
                response_schema={"type": "object"},
            ))

    asyncio.run(run())
    assert seen["think"] is False


def test_gateway_llm_adapter_omits_think_for_gptoss_structured_output():
    seen = {}

    async def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "done": True,
            "message": {
                "content": "{\"answer\":\"ok\"}",
                "thinking": "hidden model reasoning",
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        })

    async def run():
        async with httpx.AsyncClient(
            base_url="http://ollama",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = GatewayLLMAdapter(
                client, model="qwen3.6:35b",
                node_id="ai-node-01", health_timeout=1.0,
            )
            response = await adapter.generate_for_model(
                LLMRequest(
                    request_id="req-gptoss-think",
                    capability="structured-generation",
                    messages=[{"role": "user", "content": "test"}],
                    response_schema={"type": "object"},
                ),
                "gpt-oss:20b", num_ctx=65536, num_gpu=99,
            )
            assert response.content == "{\"answer\":\"ok\"}"

    asyncio.run(run())
    assert "think" not in seen
    assert seen["format"] == {"type": "object"}


def test_gateway_llm_adapter_omits_think_for_mistral_small4_structured_output():
    seen = {}

    async def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "done": True,
            "message": {
                "content": "{\"answer\":\"ok\"}",
                "thinking": "hidden model reasoning",
            },
            "prompt_eval_count": 1,
            "eval_count": 1,
        })

    async def run():
        async with httpx.AsyncClient(
            base_url="http://ollama",
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = GatewayLLMAdapter(
                client, model="qwen3.6:35b",
                node_id="ai-node-01", health_timeout=1.0,
            )
            response = await adapter.generate_for_model(
                LLMRequest(
                    request_id="req-mistral4-think",
                    capability="structured-generation",
                    messages=[{"role": "user", "content": "test"}],
                    response_schema={"type": "object"},
                ),
                "frob/mistral-small-4:119b-a6b-2603-ud-q4_K_M",
                num_ctx=65536, num_gpu=99,
            )
            assert response.content == "{\"answer\":\"ok\"}"

    asyncio.run(run())
    assert "think" not in seen
    assert seen["format"] == {"type": "object"}
