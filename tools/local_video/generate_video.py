#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import random
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_GATEWAY_URL = "http://127.0.0.1:11435"
DEFAULT_OUTPUT_DIR = Path("/srv/ai-data/hermes-media/video")

MODEL_NAME = "wan2.2_ti2v_5B_fp16.safetensors"
TEXT_ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE_NAME = "wan2.2_vae.safetensors"

NEGATIVE_PROMPT = (
    "oversaturated, overexposed, static, blurry details, subtitles, watermark, "
    "worst quality, low quality, jpeg artifacts, ugly, deformed hands, deformed face, "
    "malformed limbs, fused fingers, extra limbs, frozen frame, cluttered background"
)

PRESETS = {
    "smoke": {"width": 512, "height": 288, "frames": 17, "steps": 4, "cfg": 5.0},
    "fast": {"width": 640, "height": 352, "frames": 49, "steps": 10, "cfg": 5.0},
    "balanced": {"width": 832, "height": 480, "frames": 81, "steps": 20, "cfg": 5.0},
    "quality": {"width": 1280, "height": 704, "frames": 121, "steps": 20, "cfg": 5.0},
}

REQUIRED_NODES = {
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "CLIPTextEncode",
    "ModelSamplingSD3",
    "Wan22ImageToVideoLatent",
    "KSampler",
    "VAEDecode",
    "CreateVideo",
    "SaveVideo",
}


class VideoError(RuntimeError):
    pass


def _base(url: str) -> str:
    return url.rstrip("/") + "/"


def _request_json(base_url: str, path: str, *, method: str = "GET", payload=None, timeout: float = 30.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(urljoin(_base(base_url), path.lstrip("/")), data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise VideoError(f"HTTP {exc.code} for {path}: {body[:1000]}") from exc
    except URLError as exc:
        raise VideoError(f"Cannot reach {base_url}: {exc}") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VideoError(f"Invalid JSON from {path}") from exc


def _request_bytes(base_url: str, path: str, *, timeout: float = 120.0) -> bytes:
    req = Request(urljoin(_base(base_url), path.lstrip("/")), method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (HTTPError, URLError) as exc:
        raise VideoError(f"Failed to download ComfyUI output: {exc}") from exc


def _multipart_upload(base_url: str, image_path: Path, *, timeout: float = 120.0) -> dict:
    boundary = f"----hermeswan{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode(),
            b"\r\n",
        ])

    parts.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        image_path.read_bytes(),
        b"\r\n",
    ])
    field("type", "input")
    field("overwrite", "true")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = Request(
        urljoin(_base(base_url), "upload/image"),
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as exc:
        raise VideoError(f"Image upload failed: {exc}") from exc


def _extract_options(node_info: dict, node_name: str, input_name: str) -> set[str]:
    node = node_info.get(node_name) or {}
    input_map = node.get("input") or {}
    for section in ("required", "optional"):
        spec = (input_map.get(section) or {}).get(input_name)
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return {str(x) for x in spec[0]}
    return set()


def preflight(comfy_url: str) -> dict:
    stats = _request_json(comfy_url, "/system_stats", timeout=10)
    nodes = _request_json(comfy_url, "/object_info", timeout=30)
    missing_nodes = sorted(REQUIRED_NODES - set(nodes))
    available_models = _extract_options(nodes, "UNETLoader", "unet_name")
    available_clips = _extract_options(nodes, "CLIPLoader", "clip_name")
    available_vaes = _extract_options(nodes, "VAELoader", "vae_name")
    missing_models = [
        name
        for name, options in (
            (MODEL_NAME, available_models),
            (TEXT_ENCODER, available_clips),
            (VAE_NAME, available_vaes),
        )
        if options and name not in options
    ]
    return {
        "ok": not missing_nodes and not missing_models,
        "missing_nodes": missing_nodes,
        "missing_models": missing_models,
        "system_stats": stats,
    }


def wait_for_gateway_idle(gateway_url: str, timeout: float) -> None:
    if timeout <= 0:
        return
    deadline = time.monotonic() + timeout
    stable_since = None
    while time.monotonic() < deadline:
        try:
            status = _request_json(gateway_url, "/status", timeout=3)
        except VideoError:
            return
        active = int(status.get("active_count") or 0)
        queued = int(status.get("queued_count") or 0)
        if active == 0 and queued == 0:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= 2.0:
                return
        else:
            stable_since = None
        time.sleep(1.0)
    raise VideoError("AI Gateway did not become idle before local video generation")


def build_prompt(
    prompt: str,
    *,
    width: int,
    height: int,
    frames: int,
    steps: int,
    cfg: float,
    fps: float,
    seed: int,
    negative_prompt: str,
    image_name: str | None = None,
    filename_prefix: str = "hermes-video/Wan22",
) -> dict:
    if width % 16 or height % 16:
        raise ValueError("width and height must be divisible by 16")
    if frames < 1 or (frames - 1) % 4:
        raise ValueError("frames must be 1 mod 4 (e.g. 49, 81, 121)")
    graph = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": MODEL_NAME, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": TEXT_ENCODER, "type": "wan", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VAE_NAME},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["2", 0]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["2", 0]},
        },
        "6": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["1", 0], "shift": 8.0},
        },
        "7": {
            "class_type": "Wan22ImageToVideoLatent",
            "inputs": {
                "vae": ["3", 0],
                "width": width,
                "height": height,
                "length": frames,
                "batch_size": 1,
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["6", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["7", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["3", 0]},
        },
        "10": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["9", 0], "fps": fps},
        },
        "11": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["10", 0],
                "filename_prefix": filename_prefix,
                "format": "mp4",
                "codec": "h264",
            },
        },
    }
    if image_name:
        graph["12"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        }
        graph["7"]["inputs"]["start_image"] = ["12", 0]
    return graph


def _history_error(entry: dict) -> str | None:
    status = entry.get("status") or {}
    messages = status.get("messages") or []
    failures = []
    for item in messages:
        if not isinstance(item, list) or len(item) < 2:
            continue
        kind, data = item[0], item[1]
        if kind in {"execution_error", "execution_interrupted"}:
            failures.append(json.dumps(data, ensure_ascii=False))
    return "\n".join(failures) if failures else None


def _find_video_record(entry: dict) -> dict | None:
    outputs = entry.get("outputs") or {}
    candidates = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for value in node_output.values():
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "")
                if Path(filename).suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
                    candidates.append(item)
    return candidates[-1] if candidates else None


def wait_for_result(comfy_url: str, prompt_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = _request_json(comfy_url, f"/history/{prompt_id}", timeout=10)
        entry = history.get(prompt_id) if isinstance(history, dict) else None
        if isinstance(entry, dict):
            error = _history_error(entry)
            if error:
                raise VideoError(f"ComfyUI generation failed: {error}")
            status = entry.get("status") or {}
            if status.get("completed") is True or status.get("status_str") in {"success", "error"}:
                record = _find_video_record(entry)
                if record:
                    return record
                if status.get("status_str") == "error":
                    raise VideoError("ComfyUI reported an error without details")
        time.sleep(2.0)
    raise VideoError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def download_result(comfy_url: str, record: dict, output_dir: Path, prompt_id: str) -> Path:
    filename = str(record.get("filename") or "")
    subfolder = str(record.get("subfolder") or "")
    file_type = str(record.get("type") or "output")
    if not filename:
        raise VideoError("ComfyUI output record has no filename")
    params = urlencode({"filename": filename, "subfolder": subfolder, "type": file_type})
    content = _request_bytes(comfy_url, f"/view?{params}", timeout=300)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".mp4"
    target = output_dir / f"wan22-{time.strftime('%Y%m%d-%H%M%S')}-{prompt_id[:8]}{suffix}"
    target.write_bytes(content)
    if target.stat().st_size == 0:
        raise VideoError("Downloaded video is empty")
    return target


def free_comfy_memory(comfy_url: str) -> None:
    try:
        _request_json(
            comfy_url,
            "/free",
            method="POST",
            payload={"unload_models": True, "free_memory": True},
            timeout=10,
        )
    except VideoError:
        pass


def generate(args) -> Path:
    cfg = PRESETS[args.preset].copy()
    for key in ("width", "height", "frames", "steps", "cfg"):
        value = getattr(args, key, None)
        if value is not None:
            cfg[key] = value
    wait_for_gateway_idle(args.gateway_url, args.gateway_idle_timeout)

    image_name = None
    if args.image:
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.is_file():
            raise VideoError(f"Input image does not exist: {image_path}")
        upload = _multipart_upload(args.comfy_url, image_path)
        image_name = str(upload.get("name") or "")
        subfolder = str(upload.get("subfolder") or "")
        if not image_name:
            raise VideoError(f"ComfyUI upload returned no image name: {upload}")
        if subfolder:
            image_name = f"{subfolder.rstrip('/')}/{image_name}"

    seed = args.seed if args.seed is not None else random.randrange(0, 2**63 - 1)
    graph = build_prompt(
        args.prompt,
        width=int(cfg["width"]),
        height=int(cfg["height"]),
        frames=int(cfg["frames"]),
        steps=int(cfg["steps"]),
        cfg=float(cfg["cfg"]),
        fps=float(args.fps),
        seed=seed,
        negative_prompt=args.negative_prompt,
        image_name=image_name,
    )
    response = _request_json(
        args.comfy_url,
        "/prompt",
        method="POST",
        payload={"prompt": graph, "client_id": uuid.uuid4().hex},
        timeout=30,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise VideoError(f"ComfyUI rejected prompt: {json.dumps(response, ensure_ascii=False)}")
    record = wait_for_result(args.comfy_url, prompt_id, args.timeout)
    path = download_result(args.comfy_url, record, Path(args.output_dir), prompt_id)
    if args.free_memory:
        free_comfy_memory(args.comfy_url)
    return path


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local Wan2.2 TI2V-5B video generator through ComfyUI")
    p.add_argument("--prompt", help="Text prompt for the video")
    p.add_argument("--image", help="Optional local image path for image-to-video")
    p.add_argument("--preset", choices=sorted(PRESETS), default="fast")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--frames", type=int)
    p.add_argument("--steps", type=int)
    p.add_argument("--cfg", type=float)
    p.add_argument("--fps", type=float, default=24.0)
    p.add_argument("--seed", type=int)
    p.add_argument("--negative-prompt", default=NEGATIVE_PROMPT)
    p.add_argument("--comfy-url", default=os.environ.get("COMFYUI_URL", DEFAULT_COMFY_URL))
    p.add_argument("--gateway-url", default=os.environ.get("AI_GATEWAY_URL", DEFAULT_GATEWAY_URL))
    p.add_argument("--gateway-idle-timeout", type=float, default=60.0)
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p.add_argument("--no-free-memory", dest="free_memory", action="store_false")
    p.set_defaults(free_memory=True)
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.preflight:
            result = preflight(args.comfy_url)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 2
        if not args.prompt:
            raise VideoError("--prompt is required unless --preflight is used")
        path = generate(args)
        if args.json:
            print(json.dumps({"ok": True, "path": str(path)}, ensure_ascii=False))
        else:
            print(path)
        return 0
    except (VideoError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
