#!/usr/bin/env python3
"""Download the official VisA archive to an isolated NVMe path with resumable ranges.

No third-party dependencies. Never writes to production model or runtime paths.
Downloaded archive is not automatically considered licensed for every purpose.
"""
from __future__ import annotations
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import time
from urllib.request import Request, urlopen

SOURCE = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
BLOCK = 8 * 1024 * 1024
ARCHIVE_SHA256 = "2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def metadata(url: str) -> dict:
    with urlopen(Request(url, method="HEAD"), timeout=30) as response:
        size = int(response.headers["Content-Length"])
        etag = response.headers.get("ETag")
        if response.status != 200 or not etag or size < 1000000:
            raise RuntimeError("invalid S3 origin metadata")
        return {"url": url, "size": size, "etag": etag, "last_modified": response.headers.get("Last-Modified")}

def get_block(task: tuple[int, int, int, Path, dict]) -> tuple[int, int, bool]:
    index, start, end, directory, remote = task
    part = directory / f"{index:05d}.part"
    proof = directory / f"{index:05d}.sha256"
    length = end - start + 1
    if part.exists() and proof.exists() and part.stat().st_size == length:
        if sha256(part) == proof.read_text(encoding="ascii").strip():
            return (index, length, True)
    part.unlink(missing_ok=True)
    proof.unlink(missing_ok=True)
    for attempt in range(5):
        tmp = directory / f"{index:05d}.tmp"
        try:
            req = Request(remote["url"], headers={"Range": f"bytes={start}-{end}", "If-Range": remote["etag"]})
            with urlopen(req, timeout=50) as response:
                expected_range = f"bytes {start}-{end}/{remote['size']}"
                if response.status != 206 or response.headers.get("Content-Range") != expected_range:
                    raise RuntimeError(f"range mismatch {index}: {response.status} {response.headers.get('Content-Range')}")
                if response.headers.get("ETag") != remote["etag"]:
                    raise RuntimeError(f"ETag changed for {index}")
                digest = hashlib.sha256()
                count = 0
                with tmp.open("wb") as out:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        count += len(chunk)
                        digest.update(chunk)
                if count != length:
                    raise RuntimeError(f"short range {index}: {count} != {length}")
            os.replace(tmp, part)
            proof.write_text(digest.hexdigest(), encoding="ascii")
            return (index, length, False)
        except Exception:
            tmp.unlink(missing_ok=True)
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 8))
    raise AssertionError("unreachable")

def download(root: Path, workers: int, max_blocks: int | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("output root must not be a symlink")
    remote = metadata(SOURCE)
    parts = root / "parts"
    parts.mkdir(exist_ok=True)
    origin_path = root / "origin.json"
    if origin_path.exists():
        if json.loads(origin_path.read_text(encoding="utf-8")) != remote:
            raise RuntimeError("remote archive changed: refuse to reuse cached blocks")
    else:
        origin_path.write_text(json.dumps(remote, indent=2) + "\n", encoding="utf-8")
    blocks = (remote["size"] + BLOCK - 1) // BLOCK
    tasks = [(i, i * BLOCK, min(remote["size"] - 1, (i + 1) * BLOCK - 1), parts, remote) for i in range(blocks)]
    tasks_now = tasks if max_blocks is None else tasks[:max_blocks]
    t0 = time.monotonic()
    complete = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(get_block, task): task[0] for task in tasks_now}
        for future in cf.as_completed(jobs):
            ix, length, cached = future.result()
            complete += 1
            if complete % 12 == 0 or complete == len(tasks_now):
                elapsed = max(time.monotonic() - t0, 0.01)
                print(f"BLOCKS={complete}/{len(tasks_now)} last={ix} reused={cached} elapsed={elapsed:.1f}s", flush=True)
    if max_blocks is not None and max_blocks < len(tasks):
        print(f"PARTIAL=YES fetched_blocks={max_blocks}/{blocks}; safe to resume", flush=True)
        return
    path = root / "VisA_20220922.tar"
    tmp = root / "VisA_20220922.tar.assembling"
    if not path.is_file():
        digest = hashlib.sha256()
        with tmp.open("wb") as out:
            for i, start, end, _, _ in tasks:
                block = parts / f"{i:05d}.part"
                proof = parts / f"{i:05d}.sha256"
                if block.stat().st_size != end-start+1 or sha256(block) != proof.read_text(encoding="ascii").strip():
                    raise RuntimeError(f"corrupted part {i}")
                with block.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        out.write(chunk)
                        digest.update(chunk)
        if tmp.stat().st_size != remote["size"]:
            raise RuntimeError("wrong archive size")
        os.replace(tmp, path)
    archive_hash = sha256(path)
    if archive_hash != ARCHIVE_SHA256:
        raise RuntimeError(f"official VisA SHA-256 mismatch: {archive_hash}")
    with tarfile.open(path, "r:") as archive:
        entries = archive.getmembers()
        boards = sorted({m.name.split("/")[0] for m in entries if "pcb" in m.name.lower()})
        count = sum(m.isfile() for m in entries)
    report = {"source": remote, "sha256": archive_hash, "tar_members": len(entries), "tar_files": count,
              "pcb_paths_examples": boards[:20], "downloaded_at_unix": int(time.time())}
    (root / "archive_integrity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"ARCHIVE_PASS=YES sha256={archive_hash} files={count} pcb_examples={boards[:8]}", flush=True)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-blocks", type=int, default=None, help="test a partial, resumable transfer")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16 or args.max_blocks is not None and args.max_blocks < 1:
        parser.error("workers must be 1..16, max-blocks positive")
    download(args.root, args.workers, args.max_blocks)

if __name__ == "__main__":
    main()
