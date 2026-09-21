#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path

from ai_bridge.providers.comfyui import (
    ComfyUIAdapter,
    ComfyUIWorkflowPlan,
    MediaProviderError,
)
from ai_bridge.providers.contracts import MediaGenerationRequest

try:
    import generate_ltx23_stage29 as stage29
except ImportError:
    stage29_path = Path(__file__).with_name("generate_ltx23_stage29.py")
    spec = importlib.util.spec_from_file_location("generate_ltx23_stage29", stage29_path)
    if spec is None or spec.loader is None:
        raise
    stage29 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage29)


COMFY_INPUT_DEFAULT = Path("/opt/comfyui/data/input")
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

STAGE = 30
I2V_RESIZE_NODE = "ImageScale"
I2V_RESIZE_METHOD = "lanczos"
I2V_RESIZE_CROP = "center"
I2V_DEFAULT_COMPRESSION = 18
I2V_DEFAULT_STANDARD_STRENGTH = 0.85
I2V_DEFAULT_HQ_FIRST_STRENGTH = 0.70
I2V_DEFAULT_HQ_REINJECT_STRENGTH = 1.0

MAX_DURATION_SECONDS = stage29.MAX_DURATION_SECONDS
DEFAULT_DURATION_SECONDS = stage29.DEFAULT_DURATION_SECONDS
DEFAULT_FPS = stage29.DEFAULT_FPS


class Stage30Error(stage29.Stage29Error):
    pass


def frames_for_duration(seconds: int, fps: int = DEFAULT_FPS) -> int:
    return stage29.frames_for_duration(seconds, fps)


def _validate_i2v_tuning(
    *,
    compression: int,
    first_strength: float,
    hq_reinject_strength: float,
) -> None:
    if not isinstance(compression, int) or not 0 <= compression <= 100:
        raise ValueError("i2v compression must be an integer between 0 and 100")
    for name, value in (
        ("i2v strength", first_strength),
        ("i2v HQ reinject strength", hq_reinject_strength),
    ):
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"{name} must be between 0.0 and 1.0")


def default_first_strength(*, upscale_2x: bool) -> float:
    return (
        I2V_DEFAULT_HQ_FIRST_STRENGTH
        if upscale_2x
        else I2V_DEFAULT_STANDARD_STRENGTH
    )


def preflight_from_info(
    info: dict,
    *,
    require_upscale: bool = False,
    require_i2v: bool = False,
) -> dict:
    out = stage29.preflight_from_info(
        info,
        require_upscale=require_upscale,
        require_i2v=require_i2v,
    )
    missing_nodes = set(out.get("missing_nodes") or [])
    if require_i2v and I2V_RESIZE_NODE not in info:
        missing_nodes.add(I2V_RESIZE_NODE)

    out = dict(out)
    out["ok"] = not missing_nodes and not (out.get("missing_models") or [])
    out["missing_nodes"] = sorted(missing_nodes)
    out["stage"] = STAGE
    out["i2v_resize_node"] = I2V_RESIZE_NODE
    out["i2v_resize_method"] = I2V_RESIZE_METHOD
    out["i2v_compression_default"] = I2V_DEFAULT_COMPRESSION
    out["i2v_standard_strength_default"] = I2V_DEFAULT_STANDARD_STRENGTH
    out["i2v_hq_first_strength_default"] = I2V_DEFAULT_HQ_FIRST_STRENGTH
    out["i2v_hq_reinject_strength_default"] = I2V_DEFAULT_HQ_REINJECT_STRENGTH
    return out


def preflight(
    comfy_url: str,
    *,
    require_upscale: bool = False,
    require_i2v: bool = False,
) -> dict:
    adapter = _media_adapter(comfy_url, str(COMFY_INPUT_DEFAULT))
    return preflight_from_info(
        adapter.object_info(),
        require_upscale=require_upscale,
        require_i2v=require_i2v,
    )


def _resize_node(image_ref: list, *, width: int, height: int) -> dict:
    return {
        "class_type": I2V_RESIZE_NODE,
        "inputs": {
            "image": image_ref,
            "upscale_method": I2V_RESIZE_METHOD,
            "width": width,
            "height": height,
            "crop": I2V_RESIZE_CROP,
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
    i2v_compression: int = I2V_DEFAULT_COMPRESSION,
    i2v_strength: float | None = None,
    i2v_hq_reinject_strength: float = I2V_DEFAULT_HQ_REINJECT_STRENGTH,
) -> dict:
    first_strength = (
        default_first_strength(upscale_2x=upscale_2x)
        if i2v_strength is None
        else float(i2v_strength)
    )
    _validate_i2v_tuning(
        compression=i2v_compression,
        first_strength=first_strength,
        hq_reinject_strength=i2v_hq_reinject_strength,
    )

    # Build the proven Stage29 T2V/HQ graph first, without its I2V injection.
    # This preserves the production sampler, sigmas, Qwen/LTX models and tiled VAE.
    graph = stage29.build_prompt(
        prompt,
        width=width,
        height=height,
        frames=frames,
        fps=fps,
        seed=seed,
        negative=negative,
        upscale_2x=upscale_2x,
        staged_image_name=None,
    )
    if not staged_image_name:
        return graph

    # Stage30 fidelity-first I2V:
    # 1) deterministic Lanczos + center crop before VAE conditioning
    # 2) lower image compression (official LTX-2.3 workflows use 18)
    # 3) gentler first-stage anchor to reduce the hard first-frame -> motion transition
    graph.update(
        {
            "30": {
                "class_type": "LoadImage",
                "inputs": {"image": staged_image_name},
            },
            "31": _resize_node(["30", 0], width=width, height=height),
            "32": {
                "class_type": "LTXVPreprocess",
                "inputs": {
                    "image": ["31", 0],
                    "img_compression": i2v_compression,
                },
            },
            "33": {
                "class_type": "LTXVImgToVideoInplace",
                "inputs": {
                    "vae": ["1", 2],
                    "image": ["32", 0],
                    "latent": ["7", 0],
                    "strength": first_strength,
                    "bypass": False,
                },
            },
        }
    )
    graph["10"]["inputs"]["video_latent"] = ["33", 0]

    if upscale_2x:
        # Avoid the Stage29 implicit bilinear resize at the second I2V anchor.
        # Rebuild the reference directly at the HQ latent resolution using Lanczos,
        # preprocess it again, then use the official-like strong second anchor.
        graph.update(
            {
                "34": _resize_node(
                    ["30", 0],
                    width=width * 2,
                    height=height * 2,
                ),
                "35": {
                    "class_type": "LTXVPreprocess",
                    "inputs": {
                        "image": ["34", 0],
                        "img_compression": i2v_compression,
                    },
                },
                "36": {
                    "class_type": "LTXVImgToVideoInplace",
                    "inputs": {
                        "vae": ["1", 2],
                        "image": ["35", 0],
                        "latent": ["18", 0],
                        "strength": float(i2v_hq_reinject_strength),
                        "bypass": False,
                    },
                },
            }
        )
        graph["19"]["inputs"]["video_latent"] = ["36", 0]

    return graph


def _validate_input_image(raw: str) -> str:
    source = Path(raw).expanduser().resolve(strict=True)
    if not source.is_file():
        raise Stage30Error(f"input image is not a file: {source}")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTS:
        raise Stage30Error(f"unsupported input image extension: {suffix}")
    return str(source)


def _workflow_plan(
    request: MediaGenerationRequest,
    staged_inputs: tuple[str, ...],
) -> ComfyUIWorkflowPlan:
    params = request.parameters
    if len(staged_inputs) > 1:
        raise Stage30Error("Stage30 accepts at most one input image")

    width = int(params["width"])
    height = int(params["height"])
    frames = int(params["frames"])
    fps = int(params["fps"])
    seed = int(params["seed"])
    negative = str(params["negative"])
    upscale_2x = bool(params["upscale_2x"])
    i2v_compression = int(params["i2v_compression"])
    raw_strength = params.get("i2v_strength")
    i2v_strength = None if raw_strength is None else float(raw_strength)
    hq_reinject = float(params["i2v_hq_reinject_strength"])
    staged_name = staged_inputs[0] if staged_inputs else None

    graph = build_prompt(
        request.prompt,
        width=width,
        height=height,
        frames=frames,
        fps=fps,
        seed=seed,
        negative=negative,
        upscale_2x=upscale_2x,
        staged_image_name=staged_name,
        i2v_compression=i2v_compression,
        i2v_strength=i2v_strength,
        i2v_hq_reinject_strength=hq_reinject,
    )
    return ComfyUIWorkflowPlan(
        graph=graph,
        output_extensions=(".mp4", ".webm", ".mov", ".mkv"),
        filename_tag="ltx23-2x" if upscale_2x else "ltx23",
        media_type="video/mp4",
        metadata={
            "stage": STAGE,
            "workflow": "ltx23-stage30",
            "upscale_2x": upscale_2x,
            "frames": frames,
            "fps": fps,
            "mode": "i2v" if staged_name else "t2v",
        },
    )


def _media_adapter(comfy_url: str, comfy_input_dir: str) -> ComfyUIAdapter:
    return ComfyUIAdapter(
        base_url=comfy_url,
        workflow_resolver=_workflow_plan,
        profiles=("ltx23-stage30",),
        capabilities=("video-generation",),
        input_dir=comfy_input_dir,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Local LTX-2.3 Stage30 fidelity-first image-to-video backend"
    )
    p.add_argument("--prompt")
    p.add_argument("--negative", default=stage29.base.NEGATIVE)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=384)
    p.add_argument("--frames", type=int)
    p.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    p.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p.add_argument("--seed", type=int)
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument(
        "--comfy-url",
        default=os.environ.get("COMFYUI_URL", stage29.base.COMFY_URL_DEFAULT),
    )
    p.add_argument("--output-dir", default=str(stage29.base.OUTPUT_DIR_DEFAULT))
    p.add_argument("--comfy-input-dir", default=str(COMFY_INPUT_DEFAULT))
    p.add_argument("--input-image")
    p.add_argument("--upscale-2x", action="store_true")
    p.add_argument(
        "--i2v-compression",
        type=int,
        default=I2V_DEFAULT_COMPRESSION,
        help="LTXVPreprocess image compression (Stage30 default: 18).",
    )
    p.add_argument(
        "--i2v-strength",
        type=float,
        help=(
            "First I2V anchor strength. Default: 0.85 standard, 0.70 HQ. "
            "Use only for controlled A/B tests."
        ),
    )
    p.add_argument(
        "--i2v-hq-reinject-strength",
        type=float,
        default=I2V_DEFAULT_HQ_REINJECT_STRENGTH,
        help="Second HQ image anchor strength (default: 1.0).",
    )
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--i2v-preflight", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        adapter = _media_adapter(args.comfy_url, args.comfy_input_dir)
        if args.preflight or args.i2v_preflight:
            out = preflight_from_info(
                adapter.object_info(),
                require_upscale=args.upscale_2x,
                require_i2v=args.i2v_preflight,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out["ok"] else 2

        if not args.prompt:
            raise Stage30Error("--prompt is required")

        frames = (
            args.frames
            if args.frames is not None
            else frames_for_duration(args.duration_seconds, args.fps)
        )
        stage29.base._validate(args.width, args.height, frames)
        if (frames - 1) % 8:
            raise ValueError("LTX frame count must follow 8*n+1")

        first_strength = (
            default_first_strength(upscale_2x=args.upscale_2x)
            if args.i2v_strength is None
            else args.i2v_strength
        )
        _validate_i2v_tuning(
            compression=args.i2v_compression,
            first_strength=first_strength,
            hq_reinject_strength=args.i2v_hq_reinject_strength,
        )

        input_artifacts: tuple[str, ...] = ()
        if args.input_image:
            input_artifacts = (_validate_input_image(args.input_image),)

        seed = (
            args.seed
            if args.seed is not None
            else random.randrange(0, 2**63 - 1)
        )
        media_result = adapter.generate(
            MediaGenerationRequest(
                request_id=f"stage30-{int(time.time() * 1000)}-{seed}",
                capability="video-generation",
                profile="ltx23-stage30",
                prompt=args.prompt,
                output_dir=args.output_dir,
                timeout_seconds=float(args.timeout),
                input_artifacts=input_artifacts,
                parameters={
                    "width": args.width,
                    "height": args.height,
                    "frames": frames,
                    "fps": args.fps,
                    "seed": seed,
                    "negative": args.negative,
                    "upscale_2x": args.upscale_2x,
                    "i2v_compression": args.i2v_compression,
                    "i2v_strength": args.i2v_strength,
                    "i2v_hq_reinject_strength": args.i2v_hq_reinject_strength,
                },
                context={"domain": "shared", "source": "hermes-video-stage30"},
            )
        )
        if len(media_result.artifacts) != 1:
            raise Stage30Error(
                f"expected one generated video artifact, got {len(media_result.artifacts)}"
            )
        dst = Path(media_result.artifacts[0].uri)

        payload = {
            "ok": True,
            "stage": STAGE,
            "path": str(dst),
            "upscale_2x": args.upscale_2x,
            "frames": frames,
            "fps": args.fps,
            "duration_seconds": round((frames - 1) / args.fps, 3),
            "mode": "i2v" if args.input_image else "t2v",
            "vae_decode": stage29.TILED_VAE_NODE,
            "vae_temporal_size": stage29.TILED_VAE_TEMPORAL_SIZE,
        }
        if args.input_image:
            payload.update(
                {
                    "i2v_resize_method": I2V_RESIZE_METHOD,
                    "i2v_resize_crop": I2V_RESIZE_CROP,
                    "i2v_compression": args.i2v_compression,
                    "i2v_first_strength": first_strength,
                    "i2v_hq_reinject_strength": (
                        args.i2v_hq_reinject_strength
                        if args.upscale_2x
                        else None
                    ),
                }
            )
        print(
            json.dumps(payload, ensure_ascii=False)
            if args.json
            else dst
        )
        return 0
    except (stage29.base.LTXError, MediaProviderError, ValueError, OSError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            if args.json
            else f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
