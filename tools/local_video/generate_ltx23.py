#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

COMFY_URL_DEFAULT = "http://127.0.0.1:8188"
OUTPUT_DIR_DEFAULT = Path("/srv/ai-data/hermes-media/video")

CHECKPOINT = "ltx-2.3-22b-dev-fp8.safetensors"
TEXT_ENCODER = "gemma_3_12B_it_fp4_mixed.safetensors"
DISTILLED_LORA = "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors"
UPSCALER = "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"

NEGATIVE = "pc game, console game, video game, cartoon, childish, ugly, blurry, low quality, watermark, subtitles"
DISTILLED_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
UPSCALE_SIGMAS = "0.85, 0.7250, 0.4219, 0.0"

REQUIRED_NODES = {
    "CheckpointLoaderSimple", "LoraLoaderModelOnly", "LTXAVTextEncoderLoader", "CLIPTextEncode",
    "LTXVConditioning", "EmptyLTXVLatentVideo", "LTXVAudioVAELoader", "LTXVEmptyLatentAudio",
    "LTXVConcatAVLatent", "CFGGuider", "RandomNoise", "KSamplerSelect", "ManualSigmas",
    "SamplerCustomAdvanced", "LTXVSeparateAVLatent", "VAEDecode", "LTXVAudioVAEDecode",
    "CreateVideo", "SaveVideo",
}
UPSCALE_NODES = {"LatentUpscaleModelLoader", "LTXVLatentUpsampler", "LTXVTiledVAEDecode"}


class LTXError(RuntimeError):
    pass


def req_json(base: str, path: str, *, method="GET", payload=None, timeout=30):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = Request(base.rstrip("/") + "/" + path.lstrip("/"), data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise LTXError(f"HTTP {e.code} for {path}: {body[:4000]}") from e
    except URLError as e:
        raise LTXError(f"Cannot reach ComfyUI: {e}") from e
    return json.loads(raw.decode()) if raw else {}


def req_bytes(base: str, path: str, timeout=300) -> bytes:
    try:
        with urlopen(base.rstrip("/") + "/" + path.lstrip("/"), timeout=timeout) as r:
            return r.read()
    except (HTTPError, URLError) as e:
        raise LTXError(f"Cannot download generated file: {e}") from e


def _options(info: dict, node: str, input_name: str) -> set[str]:
    data = info.get(node) or {}
    inputs = data.get("input") or {}
    for section in ("required", "optional"):
        spec = (inputs.get(section) or {}).get(input_name)
        if isinstance(spec, list) and spec and isinstance(spec[0], list):
            return {str(v) for v in spec[0]}
    return set()


def preflight(base: str, *, require_upscale: bool = False) -> dict:
    info = req_json(base, "/object_info", timeout=60)
    required = set(REQUIRED_NODES)
    if require_upscale:
        required |= UPSCALE_NODES
    missing_nodes = sorted(required - set(info))
    missing_models = []
    for node, inp, name in (
        ("CheckpointLoaderSimple", "ckpt_name", CHECKPOINT),
        ("LTXAVTextEncoderLoader", "text_encoder", TEXT_ENCODER),
        ("LoraLoaderModelOnly", "lora_name", DISTILLED_LORA),
    ):
        opts = _options(info, node, inp)
        if opts and name not in opts:
            missing_models.append(name)
    if require_upscale:
        opts = _options(info, "LatentUpscaleModelLoader", "model_name")
        if opts and UPSCALER not in opts:
            missing_models.append(UPSCALER)
    return {"ok": not missing_nodes and not missing_models, "missing_nodes": missing_nodes, "missing_models": missing_models}


def _validate(width: int, height: int, frames: int) -> None:
    if width % 32 or height % 32:
        raise ValueError("LTX width and height must be divisible by 32")
    if frames < 9:
        raise ValueError("frames must be >= 9")


def build_prompt(prompt: str, *, width: int, height: int, frames: int, fps: int, seed: int, negative: str, upscale_2x: bool = False) -> dict:
    _validate(width, height, frames)
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINT}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": DISTILLED_LORA, "strength_model": 0.5}},
        "3": {"class_type": "LTXAVTextEncoderLoader", "inputs": {"text_encoder": TEXT_ENCODER, "ckpt_name": CHECKPOINT, "device": "default"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": negative}},
        "6": {"class_type": "LTXVConditioning", "inputs": {"positive": ["4", 0], "negative": ["5", 0], "frame_rate": float(fps)}},
        "7": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1}},
        "8": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": CHECKPOINT}},
        "9": {"class_type": "LTXVEmptyLatentAudio", "inputs": {"audio_vae": ["8", 0], "frames_number": frames, "frame_rate": fps, "batch_size": 1}},
        "10": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["7", 0], "audio_latent": ["9", 0]}},
        "11": {"class_type": "CFGGuider", "inputs": {"model": ["2", 0], "positive": ["6", 0], "negative": ["6", 1], "cfg": 1.0}},
        "12": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "13": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral_cfg_pp"}},
        "14": {"class_type": "ManualSigmas", "inputs": {"sigmas": DISTILLED_SIGMAS}},
        "15": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["12", 0], "guider": ["11", 0], "sampler": ["13", 0], "sigmas": ["14", 0], "latent_image": ["10", 0]}},
        "16": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["15", 0]}},
    }
    if not upscale_2x:
        g.update({
            "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["1", 2]}},
            "18": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["16", 1], "audio_vae": ["8", 0]}},
            "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "audio": ["18", 0], "fps": float(fps)}},
            "20": {"class_type": "SaveVideo", "inputs": {"video": ["19", 0], "filename_prefix": "hermes-video/LTX23", "format": "mp4", "codec": "h264"}},
        })
        return g

    g.update({
        "17": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": UPSCALER}},
        "18": {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": ["16", 0], "upscale_model": ["17", 0], "vae": ["1", 2]}},
        "19": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["18", 0], "audio_latent": ["16", 1]}},
        "20": {"class_type": "CFGGuider", "inputs": {"model": ["2", 0], "positive": ["6", 0], "negative": ["6", 1], "cfg": 1.0}},
        "21": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "22": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_cfg_pp"}},
        "23": {"class_type": "ManualSigmas", "inputs": {"sigmas": UPSCALE_SIGMAS}},
        "24": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["21", 0], "guider": ["20", 0], "sampler": ["22", 0], "sigmas": ["23", 0], "latent_image": ["19", 0]}},
        "25": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["24", 0]}},
        "26": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["1", 2], "latents": ["25", 0], "horizontal_tiles": 2, "vertical_tiles": 2, "overlap": 6, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "27": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["25", 1], "audio_vae": ["8", 0]}},
        "28": {"class_type": "CreateVideo", "inputs": {"images": ["26", 0], "audio": ["27", 0], "fps": float(fps)}},
        "29": {"class_type": "SaveVideo", "inputs": {"video": ["28", 0], "filename_prefix": "hermes-video/LTX23-2X", "format": "mp4", "codec": "h264"}},
    })
    return g


def find_video(entry: dict) -> dict | None:
    for node in (entry.get("outputs") or {}).values():
        if not isinstance(node, dict):
            continue
        for items in node.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and str(item.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                    return item
    return None


def wait_result(base: str, prompt_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = req_json(base, f"/history/{prompt_id}", timeout=15)
        entry = h.get(prompt_id) if isinstance(h, dict) else None
        if isinstance(entry, dict):
            status = entry.get("status") or {}
            for msg in status.get("messages") or []:
                if isinstance(msg, list) and msg and msg[0] == "execution_error":
                    raise LTXError("ComfyUI execution error: " + json.dumps(msg[1], ensure_ascii=False)[:6000])
            rec = find_video(entry)
            if rec:
                return rec
        time.sleep(3)
    raise LTXError("Timed out waiting for LTX-2.3 render")


def download_output(base: str, rec: dict, output_dir: Path, prompt_id: str, *, upscale_2x: bool = False) -> Path:
    params = urlencode({"filename": rec.get("filename", ""), "subfolder": rec.get("subfolder", ""), "type": rec.get("type", "output")})
    data = req_bytes(base, "/view?" + params)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(str(rec.get("filename") or "out.mp4")).suffix or ".mp4"
    tag = "ltx23-2x" if upscale_2x else "ltx23"
    dst = output_dir / f"{tag}-{time.strftime('%Y%m%d-%H%M%S')}-{prompt_id[:8]}{suffix}"
    dst.write_bytes(data)
    if not dst.stat().st_size:
        raise LTXError("Generated file is empty")
    return dst


def free_memory(base: str) -> None:
    try:
        req_json(base, "/free", method="POST", payload={"unload_models": True, "free_memory": True}, timeout=20)
    except Exception:
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Local LTX-2.3 22B distilled benchmark via ComfyUI")
    p.add_argument("--prompt")
    p.add_argument("--negative", default=NEGATIVE)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=384)
    p.add_argument("--frames", type=int, default=49)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--seed", type=int)
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--comfy-url", default=os.environ.get("COMFYUI_URL", COMFY_URL_DEFAULT))
    p.add_argument("--output-dir", default=str(OUTPUT_DIR_DEFAULT))
    p.add_argument("--upscale-2x", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.preflight:
            out = preflight(args.comfy_url, require_upscale=args.upscale_2x)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out["ok"] else 2
        if not args.prompt:
            raise LTXError("--prompt is required")
        seed = args.seed if args.seed is not None else random.randrange(0, 2**63 - 1)
        graph = build_prompt(args.prompt, width=args.width, height=args.height, frames=args.frames, fps=args.fps, seed=seed, negative=args.negative, upscale_2x=args.upscale_2x)
        submitted = req_json(args.comfy_url, "/prompt", method="POST", payload={"prompt": graph, "client_id": uuid.uuid4().hex}, timeout=60)
        pid = str(submitted.get("prompt_id") or "")
        if not pid:
            raise LTXError("ComfyUI rejected prompt: " + json.dumps(submitted, ensure_ascii=False))
        rec = wait_result(args.comfy_url, pid, args.timeout)
        dst = download_output(args.comfy_url, rec, Path(args.output_dir), pid, upscale_2x=args.upscale_2x)
        free_memory(args.comfy_url)
        print(json.dumps({"ok": True, "path": str(dst), "upscale_2x": args.upscale_2x}, ensure_ascii=False) if args.json else dst)
        return 0
    except (LTXError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False) if args.json else f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
