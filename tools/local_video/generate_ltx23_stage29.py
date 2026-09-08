#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import shutil
import sys
import time
import uuid
from pathlib import Path

try:
    import generate_ltx23_base as base
except ImportError:
    base_path = Path(__file__).with_name("generate_ltx23.py")
    spec = importlib.util.spec_from_file_location("generate_ltx23_base", base_path)
    if spec is None or spec.loader is None:
        raise
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)


COMFY_INPUT_DEFAULT = Path("/opt/comfyui/data/input")
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
I2V_NODES = {"LoadImage", "LTXVPreprocess", "LTXVImgToVideoInplace"}
HQ_NODES = {"LatentUpscaleModelLoader", "LTXVLatentUpsampler"}
TILED_VAE_NODE = "VAEDecodeTiled"
TILED_VAE_TILE_SIZE = 512
TILED_VAE_OVERLAP = 64
# The host already succeeds with 49-frame normal VAE decode but OOM-killed at 97 frames.
# Decode at most 32 frames per temporal tile to keep VAE peak below the known-good 49-frame load.
TILED_VAE_TEMPORAL_SIZE = 32
TILED_VAE_TEMPORAL_OVERLAP = 8
MAX_DURATION_SECONDS = 6
DEFAULT_DURATION_SECONDS = 2
DEFAULT_FPS = 24


class Stage29Error(base.LTXError):
    pass


def frames_for_duration(seconds: int, fps: int = DEFAULT_FPS) -> int:
    if not isinstance(seconds, int):
        raise ValueError("duration must be an integer number of seconds")
    if seconds < 1 or seconds > MAX_DURATION_SECONDS:
        raise ValueError(f"duration must be between 1 and {MAX_DURATION_SECONDS} seconds")
    if fps <= 0:
        raise ValueError("fps must be > 0")
    frames = seconds * fps + 1
    if (frames - 1) % 8:
        raise ValueError("LTX frame count must follow 8*n+1")
    return frames


def validate_frames(frames: int) -> None:
    base._validate(640, 384, frames)
    if (frames - 1) % 8:
        raise ValueError("LTX frame count must follow 8*n+1")


def preflight(comfy_url: str, *, require_upscale: bool = False, require_i2v: bool = False) -> dict:
    # Stage29 deliberately uses ComfyUI core VAEDecodeTiled for both standard and HQ output.
    # This is the official LTX-2.3 blueprint decoder and avoids decoding the entire temporal
    # latent in one VAE pass on the 128 GiB UMA host.
    out = base.preflight(comfy_url, require_upscale=False)
    missing_nodes = set(out.get("missing_nodes") or [])
    missing_models = set(out.get("missing_models") or [])
    info = base.req_json(comfy_url, "/object_info", timeout=60)

    if TILED_VAE_NODE not in info:
        missing_nodes.add(TILED_VAE_NODE)

    if require_upscale:
        missing_nodes |= HQ_NODES - set(info)
        opts = base._options(info, "LatentUpscaleModelLoader", "model_name")
        if opts and base.UPSCALER not in opts:
            missing_models.add(base.UPSCALER)

    if require_i2v:
        missing_nodes |= I2V_NODES - set(info)

    return {
        "ok": not missing_nodes and not missing_models,
        "missing_nodes": sorted(missing_nodes),
        "missing_models": sorted(missing_models),
        "i2v_required": bool(require_i2v),
        "vae_decode": TILED_VAE_NODE,
        "vae_tile_size": TILED_VAE_TILE_SIZE,
        "vae_temporal_size": TILED_VAE_TEMPORAL_SIZE,
    }


def _apply_tiled_vae_decode(graph: dict, *, upscale_2x: bool) -> None:
    node_id = "26" if upscale_2x else "17"
    samples = ["25", 0] if upscale_2x else ["16", 0]
    node = graph.get(node_id)
    if not isinstance(node, dict):
        raise Stage29Error(f"graph is missing VAE decode node {node_id}")
    graph[node_id] = {
        "class_type": TILED_VAE_NODE,
        "inputs": {
            "samples": samples,
            "vae": ["1", 2],
            "tile_size": TILED_VAE_TILE_SIZE,
            "overlap": TILED_VAE_OVERLAP,
            "temporal_size": TILED_VAE_TEMPORAL_SIZE,
            "temporal_overlap": TILED_VAE_TEMPORAL_OVERLAP,
        },
    }


def build_prompt(
    prompt: str,
    *,
    width: int,
    height: int,
    frames: int,
    fps: int,
    seed: int,
    negative: str,
    upscale_2x: bool = False,
    staged_image_name: str | None = None,
) -> dict:
    base._validate(width, height, frames)
    if (frames - 1) % 8:
        raise ValueError("LTX frame count must follow 8*n+1")

    graph = base.build_prompt(
        prompt,
        width=width,
        height=height,
        frames=frames,
        fps=fps,
        seed=seed,
        negative=negative,
        upscale_2x=upscale_2x,
    )
    _apply_tiled_vae_decode(graph, upscale_2x=upscale_2x)

    if not staged_image_name:
        return graph

    graph.update({
        "30": {"class_type": "LoadImage", "inputs": {"image": staged_image_name}},
        "31": {"class_type": "LTXVPreprocess", "inputs": {"image": ["30", 0], "img_compression": 25}},
        "32": {
            "class_type": "LTXVImgToVideoInplace",
            "inputs": {"vae": ["1", 2], "image": ["31", 0], "latent": ["7", 0], "strength": 1.0},
        },
    })
    graph["10"]["inputs"]["video_latent"] = ["32", 0]

    if upscale_2x:
        graph["33"] = {
            "class_type": "LTXVImgToVideoInplace",
            "inputs": {"vae": ["1", 2], "image": ["31", 0], "latent": ["18", 0], "strength": 1.0},
        }
        graph["19"]["inputs"]["video_latent"] = ["33", 0]
    return graph


def _stage_input_image(raw: str, comfy_input_dir: Path) -> tuple[Path, str]:
    source = Path(raw).expanduser().resolve(strict=True)
    if not source.is_file():
        raise Stage29Error(f"input image is not a file: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTS:
        raise Stage29Error(f"unsupported input image extension: {suffix}")
    comfy_input_dir.mkdir(parents=True, exist_ok=True)
    staged_name = f"stage29_i2v_{uuid.uuid4().hex}{suffix}"
    staged = comfy_input_dir / staged_name
    shutil.copy2(source, staged)
    return staged, staged_name


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local LTX-2.3 Stage29 text/image-to-video backend")
    p.add_argument("--prompt")
    p.add_argument("--negative", default=base.NEGATIVE)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=384)
    p.add_argument("--frames", type=int)
    p.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--seed", type=int)
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--comfy-url", default=os.environ.get("COMFYUI_URL", base.COMFY_URL_DEFAULT))
    p.add_argument("--output-dir", default=str(base.OUTPUT_DIR_DEFAULT))
    p.add_argument("--comfy-input-dir", default=str(COMFY_INPUT_DEFAULT))
    p.add_argument("--input-image")
    p.add_argument("--upscale-2x", action="store_true")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--i2v-preflight", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    staged_path: Path | None = None
    try:
        if args.preflight or args.i2v_preflight:
            out = preflight(
                args.comfy_url,
                require_upscale=args.upscale_2x,
                require_i2v=args.i2v_preflight,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out["ok"] else 2

        if not args.prompt:
            raise Stage29Error("--prompt is required")

        frames = args.frames if args.frames is not None else frames_for_duration(args.duration_seconds, args.fps)
        base._validate(args.width, args.height, frames)
        if (frames - 1) % 8:
            raise ValueError("LTX frame count must follow 8*n+1")

        staged_name = None
        if args.input_image:
            staged_path, staged_name = _stage_input_image(args.input_image, Path(args.comfy_input_dir))

        seed = args.seed if args.seed is not None else random.randrange(0, 2**63 - 1)
        graph = build_prompt(
            args.prompt,
            width=args.width,
            height=args.height,
            frames=frames,
            fps=args.fps,
            seed=seed,
            negative=args.negative,
            upscale_2x=args.upscale_2x,
            staged_image_name=staged_name,
        )
        submitted = base.req_json(
            args.comfy_url,
            "/prompt",
            method="POST",
            payload={"prompt": graph, "client_id": uuid.uuid4().hex},
            timeout=60,
        )
        pid = str(submitted.get("prompt_id") or "")
        if not pid:
            raise Stage29Error("ComfyUI rejected prompt: " + json.dumps(submitted, ensure_ascii=False))
        rec = base.wait_result(args.comfy_url, pid, args.timeout)
        dst = base.download_output(
            args.comfy_url,
            rec,
            Path(args.output_dir),
            pid,
            upscale_2x=args.upscale_2x,
        )
        base.free_memory(args.comfy_url)
        payload = {
            "ok": True,
            "path": str(dst),
            "upscale_2x": args.upscale_2x,
            "frames": frames,
            "fps": args.fps,
            "duration_seconds": round((frames - 1) / args.fps, 3),
            "mode": "i2v" if args.input_image else "t2v",
            "vae_decode": TILED_VAE_NODE,
            "vae_temporal_size": TILED_VAE_TEMPORAL_SIZE,
        }
        print(json.dumps(payload, ensure_ascii=False) if args.json else dst)
        return 0
    except (base.LTXError, ValueError, OSError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            if args.json else f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if staged_path is not None:
            try:
                staged_path.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
