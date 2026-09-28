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
