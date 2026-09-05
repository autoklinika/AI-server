#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

JOB_ROOT_DEFAULT = Path("/srv/ai-data/hermes-video-jobs")
LTX_BIN_DEFAULT = "/usr/local/bin/generate-video-ltx23"
HERMES_BIN_DEFAULT = "hermes"
WORKER_TIMEOUT = 7200


class DispatchError(RuntimeError):
    pass


def parse_request_args(parts: list[str]) -> tuple[bool, str]:
    """Parse quick-command argv.

    Hermes Stage-26 patches gateway exec quick_commands to append the whole
    user argument string as ONE shell-quoted argv item. Accept multiple argv
    items as well so the dispatcher is convenient to run manually/tests.
    """
    raw = " ".join(str(part) for part in parts).strip()
    if not raw:
        raise DispatchError("Użycie: /wideo [hq] <opis filmu>")

    first, sep, rest = raw.partition(" ")
    hq = first.casefold() == "hq"
    prompt = rest.strip() if hq and sep else raw
    if not prompt:
        raise DispatchError("Użycie: /wideo [hq] <opis filmu>")
    return hq, prompt


def routing_target(env: dict[str, str]) -> str:
    platform = str(env.get("HERMES_SESSION_PLATFORM", "")).strip()
    chat_id = str(env.get("HERMES_SESSION_CHAT_ID", "")).strip()
    thread_id = str(env.get("HERMES_SESSION_THREAD_ID", "")).strip()
    if not platform or not chat_id:
        raise DispatchError(
            "Brak kontekstu czatu Hermesa (HERMES_SESSION_PLATFORM/CHAT_ID); "
            "nie uruchamiam renderu bez pewnej trasy zwrotnej."
        )
    target = f"{platform}:{chat_id}"
    if thread_id:
        target += f":{thread_id}"
    return target


def _job_root() -> Path:
    return Path(os.environ.get("HERMES_VIDEO_JOB_ROOT", str(JOB_ROOT_DEFAULT)))


def queue_job(parts: list[str]) -> str:
    hq, prompt = parse_request_args(parts)
    target = routing_target(dict(os.environ))

    root = _job_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass

    job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    job_dir = root / job_id
    job_dir.mkdir(mode=0o700)
    request_path = job_dir / "request.json"
    request = {
        "schema": 1,
        "job_id": job_id,
        "created_at": time.time(),
        "target": target,
        "hq": hq,
        "prompt": prompt,
    }
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    request_path.chmod(0o600)

    log_path = job_dir / "worker.log"
    worker_script = Path(__file__).resolve()
    python_bin = os.environ.get("HERMES_VIDEO_PYTHON", sys.executable or "/usr/bin/python3")
    with log_path.open("ab", buffering=0) as log:
        proc = subprocess.Popen(
            [python_bin, str(worker_script), "--worker", str(request_path)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=os.environ.copy(),
        )
    (job_dir / "worker.pid").write_text(f"{proc.pid}\n", encoding="ascii")

    mode = "HQ 1280×768" if hq else "standard 640×384"
    return f"🎬 Przyjęto render {mode}. Gotowy film zostanie automatycznie odesłany do tego czatu."


def _resolve_hermes_bin() -> str:
    configured = os.environ.get("HERMES_CLI_BIN", "").strip()
    if configured:
        return configured
    found = shutil.which(HERMES_BIN_DEFAULT)
    if found:
        return found
    candidates = (
        "/srv/ai-data/hermes/hermes-agent/venv/bin/hermes",
        "/srv/ai-data/hermes/hermes-agent/.venv/bin/hermes",
        str(Path.home() / ".local/bin/hermes"),
    )
    for candidate in candidates:
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise DispatchError("Nie znaleziono CLI `hermes` potrzebnego do odesłania filmu.")


def _send(target: str, message: str) -> None:
    hermes = _resolve_hermes_bin()
    proc = subprocess.run(
        [hermes, "send", "--to", target, message],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise DispatchError(f"hermes send failed rc={proc.returncode}: {proc.stdout[-1200:]}")


def _extract_mp4(stdout: str) -> Path:
    candidates = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(candidates):
        if line.startswith("/") and line.lower().endswith(".mp4"):
            path = Path(line)
            if path.is_file() and path.stat().st_size > 0:
                return path
    raise DispatchError("Generator zakończył się bez poprawnej ścieżki do niepustego MP4.")


def _write_result(job_dir: Path, payload: dict) -> None:
    path = job_dir / "result.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def run_worker(request_path: Path) -> int:
    job_dir = request_path.parent
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("schema") != 1:
            raise DispatchError("Nieobsługiwany schema requestu wideo.")
        target = str(request.get("target") or "").strip()
        prompt = str(request.get("prompt") or "").strip()
        hq = bool(request.get("hq"))
        if not target or not prompt:
            raise DispatchError("Niekompletny request wideo.")

        ltx = os.environ.get("HERMES_LTX_VIDEO_BIN", LTX_BIN_DEFAULT)
        if not (Path(ltx).is_file() and os.access(ltx, os.X_OK)):
            raise DispatchError(f"Generator LTX nie jest wykonywalny: {ltx}")

        cmd = [ltx]
        if hq:
            cmd.append("--upscale-2x")
        cmd += ["--prompt", prompt]

        started = time.monotonic()
        render = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(os.environ.get("HERMES_VIDEO_RENDER_TIMEOUT", WORKER_TIMEOUT)),
            check=False,
        )
        elapsed = time.monotonic() - started
        if render.returncode != 0:
            raise DispatchError(
                f"LTX zakończył się kodem {render.returncode}: {render.stdout[-1600:]}"
            )
        mp4 = _extract_mp4(render.stdout)

        # Native media delivery, independent of the LLM/agent final response.
        # `hermes send` on the pinned Hermes build explicitly supports MEDIA:<path>.
        _send(target, f"MEDIA:{mp4}")
        _write_result(
            job_dir,
            {
                "ok": True,
                "path": str(mp4),
                "target": target,
                "hq": hq,
                "elapsed_seconds": round(elapsed, 3),
            },
        )
        print(f"DELIVERED {mp4}", flush=True)
        return 0
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
            target = str(request.get("target") or "").strip()
            if target:
                _send(target, f"❌ Generowanie wideo nie powiodło się: {message[:700]}")
        except Exception as send_exc:
            print(f"ERROR delivery failure: {send_exc}", file=sys.stderr, flush=True)
        _write_result(job_dir, {"ok": False, "error": message[:4000]})
        print(f"ERROR {message}", file=sys.stderr, flush=True)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Direct Hermes /wideo dispatcher with async chat delivery")
    p.add_argument("--worker", type=Path)
    p.add_argument("parts", nargs="*")
    args = p.parse_args(argv)
    if args.worker:
        return run_worker(args.worker)
    try:
        print(queue_job(args.parts), flush=True)
        return 0
    except DispatchError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
