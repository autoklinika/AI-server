import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def test_extension_reports_models_and_flags_without_consuming_cleanup(monkeypatch):
    routes = []
    flags = {'free_memory': True}
    def get_flags(*, reset):
        assert reset is False
        return flags.copy()
    queue = SimpleNamespace(get_current_queue=lambda: ([], []), get_flags=get_flags)
    monkeypatch.setitem(sys.modules, 'server', SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(
        routes=SimpleNamespace(get=lambda path: lambda fn: routes.append((path, fn)) or fn), prompt_queue=queue))))
    memory = SimpleNamespace(current_loaded_models=[object()])
    monkeypatch.setitem(sys.modules, 'comfy', SimpleNamespace(model_management=memory))
    monkeypatch.setitem(sys.modules, 'comfy.model_management', memory)
    monkeypatch.setitem(sys.modules, 'aiohttp', SimpleNamespace(web=SimpleNamespace(json_response=lambda d: d)))
    spec = importlib.util.spec_from_file_location('comfy_extension_test', Path(__file__).parents[1] / 'deploy/comfyui/ai_platform_residency.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert routes[0][0] == '/ai-platform/residency'
    assert module.residency_snapshot(queue, memory.current_loaded_models) == {
        'schema_version': 1, 'queue_running': 0, 'queue_pending': 0,
        'loaded_models': 1, 'cleanup_pending': True}
    assert flags == {'free_memory': True}
