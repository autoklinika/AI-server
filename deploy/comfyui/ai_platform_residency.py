"""Read-only RM evidence via ComfyUI's supported custom-node route extension.

No inference, model mutation, monkeypatching, or allocator work occurs here.
"""
from aiohttp import web
from server import PromptServer
import comfy.model_management as memory

NODE_CLASS_MAPPINGS = {}


def residency_snapshot(queue, loaded_models):
    running, pending = queue.get_current_queue()
    flags = queue.get_flags(reset=False)
    return {"schema_version": 1, "queue_running": len(running),
            "queue_pending": len(pending), "loaded_models": len(loaded_models),
            "cleanup_pending": bool(flags.get("unload_models") or flags.get("free_memory"))}


@PromptServer.instance.routes.get('/ai-platform/residency')
async def residency(request):
    return web.json_response(residency_snapshot(
        PromptServer.instance.prompt_queue, list(memory.current_loaded_models)))
