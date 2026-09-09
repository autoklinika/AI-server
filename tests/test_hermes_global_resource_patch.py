from pathlib import Path
import importlib.util,pytest
ROOT=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location("global_resource_patcher",ROOT/"tools/patch_hermes_global_resource_queue.py");assert spec and spec.loader;mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
def fixture():return '''def _set_extra_header(api_kwargs, key, value):\n    api_kwargs[key]=value\n\ndef build_api_request(agent, api_kwargs):\n    logger = type("L", (), {"warning": lambda *a, **k: None})()\n    # Private to the in-process MoA facade; added after middleware/hooks/debug dumps so\n    return api_kwargs\n'''
def test_patch_is_idempotent_and_sets_releasing_lease_headers():
    original=fixture();assert mod.check_text(original)=="patchable";patched=mod.patch_text(original);assert patched.count(mod.MARKER)==1;assert "X-AI-Resource-Lease" in patched;assert "X-AI-Resource-Lease-Release" in patched;assert "telegram-chat" in patched;assert mod.check_text(patched)=="patched";assert mod.patch_text(patched)==patched;compile(patched,"fixture.py","exec")
def test_patch_refuses_unknown_layout():
    with pytest.raises(mod.PatchError):mod.patch_text("def unrelated():\n    pass\n")
