#!/usr/bin/env python3

import argparse
import fcntl
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from ai_bridge.providers.media_admission import require_external_media_use

require_external_media_use("image-generation")

COMFY = "http://127.0.0.1:8188"
OUTPUT = Path("/srv/ai-data/comfyui-output")

parser = argparse.ArgumentParser(
    description="Generate image locally with FLUX.2 Klein"
)
parser.add_argument("prompt")
parser.add_argument("--width", type=int, default=1024)
parser.add_argument("--height", type=int, default=1024)
parser.add_argument("--seed", type=int, default=None)

args = parser.parse_args()

prompt = args.prompt
width = args.width
height = args.height
seed = args.seed if args.seed is not None else random.randrange(0, 2**63)

if width % 16 or height % 16:
    print("ERROR: width and height must be divisible by 16")
    raise SystemExit(2)


def request_json(url, data=None):
    headers = {}

    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = None

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST" if data is not None else "GET",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()

        if not raw:
            return {}

        return json.loads(raw)



workflow = {
    "1": {
        "class_type": "UNETLoader",
        "inputs": {
            "unet_name": "flux-2-klein-4b-fp8.safetensors",
            "weight_dtype": "default",
        },
    },

    "2": {
        "class_type": "CLIPLoader",
        "inputs": {
            "clip_name": "qwen_3_4b.safetensors",
            "type": "flux2",
            "device": "default",
        },
    },

    "3": {
        "class_type": "VAELoader",
        "inputs": {
            "vae_name": "flux2-vae.safetensors",
        },
    },

    "4": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": prompt,
            "clip": ["2", 0],
        },
    },

    "5": {
        "class_type": "ConditioningZeroOut",
        "inputs": {
            "conditioning": ["4", 0],
        },
    },

    "6": {
        "class_type": "CFGGuider",
        "inputs": {
            "model": ["1", 0],
            "positive": ["4", 0],
            "negative": ["5", 0],
            "cfg": 1.0,
        },
    },

    "7": {
        "class_type": "RandomNoise",
        "inputs": {
            "noise_seed": seed,
        },
    },

    "8": {
        "class_type": "KSamplerSelect",
        "inputs": {
            "sampler_name": "euler",
        },
    },

    "9": {
        "class_type": "Flux2Scheduler",
        "inputs": {
            "steps": 4,
            "width": width,
            "height": height,
        },
    },

    "10": {
        "class_type": "EmptyFlux2LatentImage",
        "inputs": {
            "width": width,
            "height": height,
            "batch_size": 1,
        },
    },

    "11": {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["7", 0],
            "guider": ["6", 0],
            "sampler": ["8", 0],
            "sigmas": ["9", 0],
            "latent_image": ["10", 0],
        },
    },

    "12": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["11", 0],
            "vae": ["3", 0],
        },
    },

    "13": {
        "class_type": "SaveImage",
        "inputs": {
            "images": ["12", 0],
            "filename_prefix": "Flux2-Klein",
        },
    },
}


lock_path = "/tmp/generate-image.lock"

with open(lock_path, "w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)

    try:
        print("===== LOCAL IMAGE GENERATION =====")
        print("Prompt :", prompt)
        print("Size   :", f"{width}x{height}")
        print("Seed   :", seed)

        print()
        print("Checking ComfyUI...")

        request_json(COMFY + "/system_stats")

        print("ComfyUI: OK")

        print()
        print("Submitting FLUX.2 job...")

        result = request_json(
            COMFY + "/prompt",
            {"prompt": workflow},
        )

        if result.get("node_errors"):
            print(
                json.dumps(
                    result["node_errors"],
                    indent=2,
                    ensure_ascii=False,
                )
            )
            raise RuntimeError("ComfyUI workflow validation failed")

        prompt_id = result["prompt_id"]

        print("Prompt ID:", prompt_id)
        print("Generating...")

        started = time.time()

        for _ in range(900):
            time.sleep(1)

            history = request_json(
                COMFY + "/history/" + prompt_id
            )

            if prompt_id not in history:
                continue

            entry = history[prompt_id]

            outputs = entry.get("outputs", {})

            for output in outputs.values():
                images = output.get("images", [])

                if not images:
                    continue

                image = images[0]

                path = (
                    OUTPUT
                    / image.get("subfolder", "")
                    / image["filename"]
                )

                elapsed = time.time() - started

                print()
                print("===== IMAGE READY =====")
                print(f"Time  : {elapsed:.1f} s")
                print("Image :", path)

                raise SystemExit(0)

            status = entry.get("status", {})

            if status.get("status_str") == "error":
                raise RuntimeError(
                    json.dumps(
                        status,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

        raise RuntimeError("Generation timeout")

    except SystemExit as exc:
        result_code = exc.code

    except Exception as exc:
        print()
        print("ERROR:", exc)
        result_code = 1

    raise SystemExit(result_code)
