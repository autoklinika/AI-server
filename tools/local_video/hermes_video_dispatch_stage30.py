#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

LOCAL_VIDEO_DIR = str(Path(__file__).resolve().parent)
if LOCAL_VIDEO_DIR not in sys.path:
    sys.path.insert(0, LOCAL_VIDEO_DIR)

try:
    import hermes_video_dispatch_base as base
except ImportError:
    import hermes_video_dispatch as base

import qwen_prompt_compiler_stage30 as qwen


DEFAULT_DURATION_SECONDS = 2
MAX_DURATION_SECONDS = 6
FPS = 24
WORKER_TIMEOUT = 7200
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

MOTION_TOKENS = {
    "motion=subtle": "subtle",
    "motion=normal": "normal",
    "motion=strong": "strong",
    "ruch=lekki": "subtle",
    "ruch=normalny": "normal",
    "ruch=mocny": "strong",
}


def _usage() -> str:
    return (
        "Użycie: /wideo [hq] [1s..6s] "
        "[motion=subtle|normal|strong] <opis filmu>"
    )


def parse_request_args(parts: list[str]) -> dict:
    raw = " ".join(str(part) for part in parts).strip()
    if not raw:
        raise base.DispatchError(_usage())

    tokens = raw.split()
    hq = False
    duration = DEFAULT_DURATION_SECONDS
    motion_level = qwen.DEFAULT_MOTION_LEVEL
    duration_seen = False
    hq_seen = False
    motion_seen = False

    while tokens:
        token = tokens[0].casefold()
        if token == "hq":
            if hq_seen:
                raise base.DispatchError(
                    "Tryb `hq` podano więcej niż raz. " + _usage()
                )
            hq = True
            hq_seen = True
            tokens.pop(0)
            continue

        match = re.fullmatch(r"(\d+)(?:s|sek|sec)", token)
        if match:
            if duration_seen:
                raise base.DispatchError(
                    "Czas filmu podano więcej niż raz. " + _usage()
                )
            duration = int(match.group(1))
            if duration < 1 or duration > MAX_DURATION_SECONDS:
                raise base.DispatchError(
                    f"Obsługiwany czas filmu to 1–{MAX_DURATION_SECONDS} s."
                )
            duration_seen = True
            tokens.pop(0)
            continue

        if token in MOTION_TOKENS:
            if motion_seen:
                raise base.DispatchError(
                    "Poziom ruchu podano więcej niż raz. " + _usage()
                )
            motion_level = MOTION_TOKENS[token]
            motion_seen = True
            tokens.pop(0)
            continue

        break

    prompt = " ".join(tokens).strip()
    if not prompt:
        raise base.DispatchError(_usage())
    return {
        "hq": hq,
        "duration_seconds": duration,
        "motion_level": motion_level,
        "prompt": prompt,
    }


def _input_image(env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    value = str(env.get("HERMES_VIDEO_INPUT_IMAGE") or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise base.DispatchError(
            "Ścieżka obrazu wejściowego dla /wideo nie jest absolutna."
        )
    path = path.resolve(strict=True)
    if not path.is_file():
        raise base.DispatchError(f"Obraz wejściowy nie istnieje: {path}")
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise base.DispatchError(
            f"Nieobsługiwany format obrazu wejściowego: {path.suffix}"
        )
    return path


def queue_job(parts: list[str]) -> str:
    parsed = parse_request_args(parts)
    target = base.routing_target(dict(os.environ))
    input_source = _input_image()

    root = base._job_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass

    job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    job_dir = root / job_id
    job_dir.mkdir(mode=0o700)

    stable_input = None
    if input_source is not None:
        stable = job_dir / f"input{input_source.suffix.lower()}"
        shutil.copy2(input_source, stable)
        stable.chmod(0o600)
        stable_input = str(stable)

    request = {
        "schema": 3,
        "stage": 30,
        "job_id": job_id,
        "created_at": time.time(),
        "target": target,
        "hq": parsed["hq"],
        "duration_seconds": parsed["duration_seconds"],
        "frames": parsed["duration_seconds"] * FPS + 1,
        "fps": FPS,
        "prompt": parsed["prompt"],
        "motion_level": parsed["motion_level"],
        "input_image": stable_input,
        "mode": "i2v" if stable_input else "t2v",
        "render_strategy": "single_tiled_vae_stage30_fidelity",
    }
    request_path = job_dir / "request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    request_path.chmod(0o600)

    log_path = job_dir / "worker.log"
    python_bin = os.environ.get(
        "HERMES_VIDEO_PYTHON",
        sys.executable or "/usr/bin/python3",
    )
    with log_path.open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            [python_bin, str(Path(__file__).resolve()), "--worker", str(request_path)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=os.environ.copy(),
        )
    (job_dir / "worker.pid").write_text(f"{proc.pid}\n", encoding="ascii")

    quality = "HQ 1280×768" if parsed["hq"] else "standard 640×384"
    source = " z obrazu" if stable_input else ""
    motion = (
        f", ruch={parsed['motion_level']}"
        if stable_input
        else ""
    )
    return (
        f"🎬 Stage30: przyjęto render {quality}, "
        f"{parsed['duration_seconds']} s{source}{motion}. "
        "Gotowy film zostanie automatycznie odesłany do tego czatu."
    )


def run_worker(request_path: Path) -> int:
    job_dir = request_path.parent
    request = json.loads(request_path.read_text(encoding="utf-8"))
    target = str(request.get("target") or "").strip()
    original = str(request.get("prompt") or "").strip()
    hq = bool(request.get("hq"))
    duration = int(request.get("duration_seconds") or DEFAULT_DURATION_SECONDS)
    input_image = str(request.get("input_image") or "").strip() or None
    motion_level = str(
        request.get("motion_level") or qwen.DEFAULT_MOTION_LEVEL
    ).strip().casefold()

    if request.get("schema") != 3 or request.get("stage") != 30:
        base._write_result(
            job_dir,
            {"ok": False, "error": "Niepoprawny request Stage30."},
        )
        return 1
    if not target or not original:
        base._write_result(
            job_dir,
            {"ok": False, "error": "Niekompletny request Stage30."},
        )
        return 1
    if duration < 1 or duration > MAX_DURATION_SECONDS:
        base._write_result(
            job_dir,
            {"ok": False, "error": "Niepoprawny czas filmu Stage30."},
        )
        return 1
    try:
        motion_level = qwen.normalize_motion_level(motion_level)
    except ValueError as exc:
        base._write_result(
            job_dir,
            {"ok": False, "error": str(exc)},
        )
        return 1
    if input_image and not Path(input_image).is_file():
        base._write_result(
            job_dir,
            {
                "ok": False,
                "error": "Brak stabilnej kopii obrazu wejściowego Stage30.",
            },
        )
        return 1

    effective, used, reason, qwen_elapsed = qwen.compile_prompt(
        original,
        duration_seconds=duration,
        has_input_image=bool(input_image),
        motion_level=motion_level,
    )
    print(f"stage: 30", flush=True)
    print(f"qwen_used: {str(used).lower()}", flush=True)
    print(f"qwen_elapsed_seconds: {qwen_elapsed:.3f}", flush=True)
    print(f"duration_seconds: {duration}", flush=True)
    print(f"mode: {'i2v' if input_image else 't2v'}", flush=True)
    print(f"motion_level: {motion_level}", flush=True)
    print("render_strategy: single_tiled_vae_stage30_fidelity", flush=True)
    print(f"original_prompt: {original}", flush=True)
    print(f"effective_prompt: {effective}", flush=True)
    if reason:
        print(f"qwen_failure_reason: {reason}", flush=True)

    meta = {
        "stage": 30,
        "qwen_used": used,
        "original_prompt": original,
        "effective_prompt": effective,
        "qwen_failure_reason": reason,
        "qwen_elapsed_seconds": round(qwen_elapsed, 3),
        "duration_seconds": duration,
        "frames": duration * FPS + 1,
        "fps": FPS,
        "input_image": input_image,
        "mode": "i2v" if input_image else "t2v",
        "motion_level": motion_level,
        "hq": hq,
        "target": target,
        "render_strategy": "single_tiled_vae_stage30_fidelity",
    }

    if not used:
        try:
            base._send(target, qwen.fallback_notice(reason))
        except Exception as exc:
            meta.update(
                {
                    "ok": False,
                    "error": (
                        "Nie wysłano ostrzeżenia o pominięciu Qwen: "
                        f"{exc}"
                    ),
                }
            )
            base._write_result(job_dir, meta)
            return 1

    ltx = os.environ.get(
        "HERMES_LTX_VIDEO_BIN",
        "/usr/local/bin/generate-video-ltx23",
    )
    if not (Path(ltx).is_file() and os.access(ltx, os.X_OK)):
        meta.update(
            {"ok": False, "error": f"Generator LTX nie jest wykonywalny: {ltx}"}
        )
        base._write_result(job_dir, meta)
        return 1

    cmd = [ltx, "--duration-seconds", str(duration)]
    if hq:
        cmd.append("--upscale-2x")
    if input_image:
        cmd += ["--input-image", input_image]
    cmd += ["--prompt", effective]

    started = time.monotonic()
    try:
        render = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(
                os.environ.get(
                    "HERMES_VIDEO_RENDER_TIMEOUT",
                    WORKER_TIMEOUT,
                )
            ),
            check=False,
        )
        elapsed = time.monotonic() - started
        if render.returncode != 0:
            raise base.DispatchError(
                f"LTX zakończył się kodem {render.returncode}: "
                f"{render.stdout[-1800:]}"
            )
        mp4 = base._extract_mp4(render.stdout)
        base._send(target, f"MEDIA:{mp4}")
        meta.update(
            {
                "ok": True,
                "path": str(mp4),
                "elapsed_seconds": round(elapsed, 3),
            }
        )
        base._write_result(job_dir, meta)
        print(f"DELIVERED {mp4}", flush=True)
        return 0
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        meta.update(
            {
                "ok": False,
                "error": message[:4000],
                "elapsed_seconds": round(
                    time.monotonic() - started,
                    3,
                ),
            }
        )
        base._write_result(job_dir, meta)
        try:
            base._send(
                target,
                f"❌ Generowanie wideo Stage30 nie powiodło się: "
                f"{message[:700]}",
            )
        except Exception as send_exc:
            print(
                f"ERROR delivery failure: {send_exc}",
                file=sys.stderr,
                flush=True,
            )
        print(f"ERROR {message}", file=sys.stderr, flush=True)
        return 1


def qwen_preflight() -> int:
    sample = (
        "Robot ze zdjęcia wykonuje jeden naturalny krok do przodu. "
        "Kamera pozostaje nieruchoma."
    )
    effective, used, reason, elapsed = qwen.compile_prompt(
        sample,
        duration_seconds=4,
        has_input_image=True,
        motion_level="normal",
    )
    print(
        json.dumps(
            {
                "ok": used,
                "stage": 30,
                "qwen_used": used,
                "qwen_failure_reason": reason,
                "qwen_elapsed_seconds": round(elapsed, 3),
                "effective_prompt": effective if used else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if used else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Hermes /wideo Stage30 fidelity-first I2V"
    )
    p.add_argument("--worker", type=Path)
    p.add_argument("--qwen-preflight", action="store_true")
    p.add_argument("parts", nargs="*")
    args = p.parse_args(argv)

    if args.qwen_preflight:
        return qwen_preflight()
    if args.worker:
        return run_worker(args.worker)
    try:
        print(queue_job(args.parts), flush=True)
        return 0
    except (base.DispatchError, OSError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
