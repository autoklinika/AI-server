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

JOB_ROOT_DEFAULT = Path("/srv/ai-data/hermes-foto-jobs")
TEXT_GENERATOR_DEFAULT = "/usr/local/bin/generate-image"
EDIT_GENERATOR_DEFAULT = "/usr/local/bin/generate-image-edit"
WORKER_TIMEOUT = 1800
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class FotoDispatchError(RuntimeError):
    pass


def routing_target(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    platform = str(env.get("HERMES_SESSION_PLATFORM") or "").strip()
    chat_id = str(env.get("HERMES_SESSION_CHAT_ID") or "").strip()
    thread_id = str(env.get("HERMES_SESSION_THREAD_ID") or "").strip()
    if not platform or not chat_id:
        raise FotoDispatchError(
            "Brak dokładnej trasy zwrotnej Hermesa (HERMES_SESSION_PLATFORM/CHAT_ID)."
        )
    target = f"{platform}:{chat_id}"
    if thread_id:
        target += f":{thread_id}"
    return target


def _hermes_bin() -> str:
    candidates = [
        shutil.which("hermes"),
        "/srv/ai-data/hermes/hermes-agent/venv/bin/hermes",
        "/srv/ai-data/hermes/hermes-agent/.venv/bin/hermes",
        str(Path.home() / ".local/bin/hermes"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FotoDispatchError("Nie znaleziono wykonywalnego Hermes CLI do wysyłki obrazu.")


def _input_image(env: dict[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    value = str(env.get("HERMES_FOTO_INPUT_IMAGE") or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise FotoDispatchError("Ścieżka zdjęcia wejściowego Hermesa nie jest absolutna.")
    if not path.is_file():
        raise FotoDispatchError(f"Zdjęcie wejściowe nie istnieje: {path}")
    return str(path)


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _possible_path(value: str) -> Path | None:
    value = value.strip().strip("\"'")
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return path if path.is_file() else None


def _extract_from_json(obj) -> list[Path]:
    found: list[Path] = []
    if isinstance(obj, dict):
        priority = ("image", "path", "output", "file", "filename")
        for key in priority:
            value = obj.get(key)
            if isinstance(value, str):
                path = _possible_path(value)
                if path:
                    found.append(path)
        for value in obj.values():
            found.extend(_extract_from_json(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_extract_from_json(value))
    return found


def extract_image_path(output: str) -> Path:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    prefixes = (
        "image:", "output:", "saved:", "file:", "path:",
        "generated image:", "generated:",
    )

    for line in reversed(lines):
        lower = line.casefold()
        for prefix in prefixes:
            if lower.startswith(prefix):
                path = _possible_path(line[len(prefix):].strip())
                if path:
                    return path

    for line in reversed(lines):
        path = _possible_path(line)
        if path:
            return path

    for line in reversed(lines):
        if line.startswith("{") or line.startswith("["):
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            found = _extract_from_json(parsed)
            if found:
                return found[-1]

    token_re = re.compile(r"(/[^\s\"']+\.(?:png|jpe?g|webp|bmp))", re.IGNORECASE)
    for line in reversed(lines):
        for match in reversed(token_re.findall(line)):
            path = _possible_path(match)
            if path:
                return path

    raise FotoDispatchError("Generator obrazu zakończył się bez rozpoznawalnej ścieżki pliku wynikowego.")


def _run_generator(request: dict, log) -> Path:
    prompt = str(request["prompt"])
    input_image = request.get("input_image")
    if input_image:
        binary = os.environ.get("HERMES_FOTO_EDIT_GENERATOR", EDIT_GENERATOR_DEFAULT)
        cmd = [binary, "--input", str(input_image), "--prompt", prompt]
    else:
        binary = os.environ.get("HERMES_FOTO_TEXT_GENERATOR", TEXT_GENERATOR_DEFAULT)
        cmd = [binary, prompt]

    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise FotoDispatchError(f"Brak generatora obrazu: {binary}")

    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=WORKER_TIMEOUT,
        check=False,
    )
    output = proc.stdout or ""
    log.write(output)
    if output and not output.endswith("\n"):
        log.write("\n")
    log.flush()
    if proc.returncode != 0:
        tail = " | ".join(output.splitlines()[-5:])[:800]
        raise FotoDispatchError(f"Generator obrazu zakończył się kodem {proc.returncode}: {tail}")
    result = extract_image_path(output)
    log.write(f"[stage28] generator_seconds={time.monotonic() - started:.3f}\n")
    log.write(f"[stage28] image={result}\n")
    log.flush()
    return result


def _send(target: str, message: str, *, timeout: int = 120) -> None:
    hermes = _hermes_bin()
    proc = subprocess.run(
        [hermes, "send", "--to", target, message],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise FotoDispatchError(
            "Hermes delivery failed: " + " | ".join((proc.stdout or "").splitlines()[-5:])[:800]
        )


def worker(job_dir: Path) -> int:
    started = time.monotonic()
    request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
    target = str(request["target"])
    mode = "edit" if request.get("input_image") else "generate"
    result: dict = {
        "ok": False,
        "target": target,
        "mode": mode,
        "prompt": request.get("prompt"),
        "input_image": request.get("input_image"),
    }

    with (job_dir / "worker.log").open("a", encoding="utf-8") as log:
        try:
            log.write(f"[stage28] mode={mode} target={target}\n")
            image = _run_generator(request, log)
            _send(target, f"MEDIA:{image}")
            result.update(
                ok=True,
                path=str(image),
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
            _write_json(job_dir / "result.json", result)
            log.write("[stage28] delivery=ok\n")
            return 0
        except Exception as exc:
            result.update(
                ok=False,
                error=str(exc),
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
            _write_json(job_dir / "result.json", result)
            log.write(f"[stage28] ERROR: {exc}\n")
            log.flush()
            try:
                _send(target, f"❌ /foto nie powiodło się: {str(exc)[:500]}")
            except Exception as send_exc:
                log.write(f"[stage28] error-notice delivery failed: {send_exc}\n")
            return 1


def dispatch(prompt: str) -> str:
    prompt = prompt.strip()
    if not prompt:
        return "Użycie: /foto <opis obrazu lub instrukcja edycji>"

    target = routing_target()
    input_image = _input_image()
    root = Path(os.environ.get("HERMES_FOTO_JOB_ROOT", str(JOB_ROOT_DEFAULT)))
    root.mkdir(parents=True, exist_ok=True)
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_dir = root / job_id
    job_dir.mkdir(mode=0o700)

    request = {
        "job_id": job_id,
        "prompt": prompt,
        "target": target,
        "input_image": input_image,
        "mode": "edit" if input_image else "generate",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _write_json(job_dir / "request.json", request)

    log_handle = (job_dir / "worker.log").open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--worker", str(job_dir)],
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    log_handle.close()
    (job_dir / "worker.pid").write_text(str(proc.pid) + "\n", encoding="utf-8")

    if input_image:
        return "🖼️ Przyjęto edycję zdjęcia. Wynik zostanie automatycznie odesłany do tego czatu."
    return "🖼️ Przyjęto generowanie obrazu. Wynik zostanie automatycznie odesłany do tego czatu."


def preflight() -> dict:
    text_bin = os.environ.get("HERMES_FOTO_TEXT_GENERATOR", TEXT_GENERATOR_DEFAULT)
    edit_bin = os.environ.get("HERMES_FOTO_EDIT_GENERATOR", EDIT_GENERATOR_DEFAULT)
    hermes_ok = True
    hermes_error = None
    try:
        hermes_path = _hermes_bin()
    except Exception as exc:
        hermes_ok = False
        hermes_path = None
        hermes_error = str(exc)
    out = {
        "ok": bool(
            os.path.isfile(text_bin) and os.access(text_bin, os.X_OK)
            and os.path.isfile(edit_bin) and os.access(edit_bin, os.X_OK)
            and hermes_ok
        ),
        "text_generator": text_bin,
        "text_generator_ok": os.path.isfile(text_bin) and os.access(text_bin, os.X_OK),
        "edit_generator": edit_bin,
        "edit_generator_ok": os.path.isfile(edit_bin) and os.access(edit_bin, os.X_OK),
        "hermes": hermes_path,
        "hermes_ok": hermes_ok,
        "hermes_error": hermes_error,
    }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic Hermes /foto dispatcher for modern Hermes")
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)

    if args.preflight:
        out = preflight()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out["ok"] else 2
    if args.worker:
        return worker(args.worker)

    try:
        print(dispatch(" ".join(args.prompt)))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
