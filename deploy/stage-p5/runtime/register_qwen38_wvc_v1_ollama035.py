#!/usr/bin/env python3
"""Register the validated WVC LoRA runtime in Ollama 0.35.x.

Ollama 0.35.x rejects new ADAPTER directives at create time, while retaining
runtime support for adapter layers already present in manifests. This tool
installs the already-converted, immutable WVC GGUF adapter without modifying
or merging the Qwen3.8 base model.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import shutil
import subprocess
import sys
import tempfile

MODEL = "qwen3.8:27b-p4-64k-gpu-wvc-v1"
SOURCE_MODEL = "qwen3.8:27b-p4-64k-gpu-p511"
SOURCE_GGUF = Path(
    "/srv/ai-data/training/p5/runtime-adapters/wvc-advisory-v1/"
    "wvc-qwen38-52356131585f-34af94cd9ab2.gguf"
)
SOURCE_ADAPTER_SHA256 = "52356131585fc3f8aafc3db33770ee0ad6559910e5844eabe49f36a1a319c48c"
RUNTIME_GGUF_SHA256 = "f84f16a32d6e0c32ea34a4362fca4d49679e8109ebd287c916255624a121d9c9"
RUNTIME_GGUF_SIZE = 233_524_416
STORE = Path("/usr/share/ollama/.ollama/models")
LIBRARY = STORE / "manifests/registry.ollama.ai/library/qwen3.8"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_copy(src: Path, dst: Path, uid: int, gid: int) -> None:
    if dst.exists():
        if sha256(dst) != RUNTIME_GGUF_SHA256:
            raise RuntimeError(f"existing blob digest mismatch: {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dst.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copyfile(src, tmp_path)
        os.chown(tmp_path, uid, gid)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, dst)
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    if os.geteuid() != 0:
        print("WVC_RUNTIME_INSTALL=BLOCKED root_required", file=sys.stderr)
        return 77
    if not SOURCE_GGUF.is_file():
        raise RuntimeError(f"missing runtime GGUF: {SOURCE_GGUF}")
    if SOURCE_GGUF.stat().st_size != RUNTIME_GGUF_SIZE:
        raise RuntimeError("runtime GGUF size mismatch")
    if sha256(SOURCE_GGUF) != RUNTIME_GGUF_SHA256:
        raise RuntimeError("runtime GGUF digest mismatch")

    uid = pwd.getpwnam("ollama").pw_uid
    gid = grp.getgrnam("ollama").gr_gid
    blob = STORE / f"blobs/sha256-{RUNTIME_GGUF_SHA256}"
    atomic_copy(SOURCE_GGUF, blob, uid, gid)

    source_manifest = LIBRARY / SOURCE_MODEL.split(":")[-1]
    if not source_manifest.is_file():
        raise RuntimeError(f"missing source manifest: {source_manifest}")
    manifest = json.loads(source_manifest.read_text())
    adapter_layers = [
        layer for layer in manifest["layers"]
        if layer.get("mediaType") == "application/vnd.ollama.image.adapter"
    ]
    if len(adapter_layers) != 1:
        raise RuntimeError("expected exactly one source adapter layer")
    layer = adapter_layers[0]
    layer["digest"] = f"sha256:{RUNTIME_GGUF_SHA256}"
    layer["size"] = RUNTIME_GGUF_SIZE
    layer["from"] = SOURCE_GGUF.name

    target_manifest = LIBRARY / MODEL.split(":")[-1]
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target_manifest.parent, delete=False
    ) as tmp:
        json.dump(manifest, tmp, separators=(",", ":"))
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.chown(tmp_path, uid, gid)
    os.chmod(tmp_path, 0o644)
    os.replace(tmp_path, target_manifest)

    shown = subprocess.check_output(
        ["ollama", "show", MODEL, "--modelfile"], text=True
    )
    expected = f"ADAPTER {STORE}/blobs/sha256-{RUNTIME_GGUF_SHA256}"
    if expected not in shown:
        raise RuntimeError("registered model does not expose expected adapter layer")

    print("WVC_RUNTIME_INSTALL=PASS")
    print(f"WVC_RUNTIME_MODEL={MODEL}")
    print(f"WVC_SOURCE_ADAPTER_SHA256={SOURCE_ADAPTER_SHA256}")
    print(f"WVC_RUNTIME_GGUF_SHA256={RUNTIME_GGUF_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
