#!/usr/bin/env python3
"""Construct conservative cross-family VisA PCB benchmark manifests.

Never writes images into Git. Dataset is fetched separately to NVMe.
Physical specimen identities are unknown. Image-stem specimen_id is a
proxy for scorer counters; full-family separation prevents cross-split
leakage but FP/PCB must be interpreted as FP/image for these manifests.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image

CATEGORIES = ("pcb1", "pcb2", "pcb3", "pcb4")
EXPECTED_NORMAL = (1004, 1001, 1006, 1005)
EXPECTED_ANOMALY = (100, 100, 100, 100)
ARCHIVE_SHA256 = "2eb8690c803ab37de0324772964100169ec8ba1fa3f7e94291c9ca673f40f362"

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            h.update(block)
    return h.hexdigest()

def enforce_path(root: Path, relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative or ".." in Path(relative).parts:
        raise ValueError(f"unsafe relative path: {relative}")
    result = (root / relative).resolve(strict=True)
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes dataset root: {relative}")
    if not result.is_file():
        raise ValueError(f"not a file: {relative}")
    return result

def load_dataset(root: Path) -> list[dict]:
    samples = []
    counts = Counter()
    for family in CATEGORIES:
        csv_file = enforce_path(root, family + "/image_anno.csv")
        with csv_file.open(encoding="utf-8-sig", newline="") as stream:
            source_rows = list(csv.DictReader(stream))
        seen = set()
        for item in source_rows:
            image_rel = item["image"]
            label = "normal" if item["label"] == "normal" else "anomaly"
            if not image_rel.startswith(family + "/Data/Images/"):
                raise ValueError(f"unexpected image path {image_rel}")
            if image_rel in seen:
                raise ValueError(f"duplicate image {image_rel}")
            seen.add(image_rel)
            image_file = enforce_path(root, image_rel)
            with Image.open(image_file) as image:
                width, height = image.size
            if width < 1 or height < 1:
                raise ValueError(f"invalid dimensions {image_rel}")
            mask_rel = item["mask"]
            regions = []
            mask_hash = None
            if label == "anomaly":
                if not mask_rel or not mask_rel.startswith(family + "/Data/Masks/Anomaly/"):
                    raise ValueError(f"anomaly missing mask {image_rel}")
                mask_file = enforce_path(root, mask_rel)
                with Image.open(mask_file) as mask:
                    if mask.size != (width, height):
                        raise ValueError(f"image and mask dimensions differ {image_rel}")
                    bbox = mask.convert("L").getbbox()
                if bbox is None:
                    raise ValueError(f"empty anomaly mask {mask_rel}")
                x1, y1, x2, y2 = bbox
                regions = [{"class": "anomaly_any_union_bbox",
                            "box": [x1 / width, y1 / height, x2 / width, y2 / height]}]
                mask_hash = digest(mask_file)
            elif mask_rel:
                raise ValueError(f"normal has unexpected mask: {image_rel}")
            samples.append({
                "sample_id": "visa-" + family + "-" + image_rel.rsplit("/", 2)[-2].lower() + "-" + Path(image_rel).stem,
                "dataset": "visa-" + family, "family": family.upper(),
                "specimen_id": "visa-image-proxy-" + image_rel,
                "source_id": "visa-original-" + image_rel,
                "sha256": digest(image_file), "image_path": image_rel, "label": label, "regions": regions,
                "_annotation": {"sample_id": "visa-" + family + "-" + image_rel.rsplit("/", 2)[-2].lower() + "-" + Path(image_rel).stem,
                                "original_label": item["label"], "mask_path": mask_rel or None, "mask_sha256": mask_hash,
                                "dimensions": [width, height] }
            })
            counts[(family, label)] += 1
        if (counts[(family, "normal")], counts[(family, "anomaly")]) != (
            EXPECTED_NORMAL[CATEGORIES.index(family)], EXPECTED_ANOMALY[CATEGORIES.index(family)]):
            raise ValueError(f"unexpected source counts {family} {counts}")
    if len({x["sample_id"] for x in samples}) != len(samples):
        raise ValueError("duplicate sample ids")
    seen_digests = defaultdict(set)
    for x in samples:
        seen_digests[x["sha256"]].add(x["family"])
    duplicate_families = {k: v for k, v in seen_digests.items() if len(v) > 1}
    if duplicate_families:
        raise ValueError(f"identical source images in multiple families: {len(duplicate_families)}")
    return sorted(samples, key=lambda x: x["sample_id"])

def make_fold(samples: list[dict], i: int) -> tuple[list[dict], dict]:
    family_role = {CATEGORIES[(i + j) % 4]: role for j, role in enumerate(("train", "calibration", "holdout", "challenge"))}
    truth = []
    skipped = 0
    for raw in samples:
        fam = raw["family"].lower()
        split = family_role[fam]
        if split == "train" and raw["label"] == "anomaly":
            skipped += 1
            continue
        truth.append({**{k: v for k, v in raw.items() if not k.startswith("_")}, "split": split})
    truth.sort(key=lambda x: x["sample_id"])
    counts = Counter((x["split"], x["label"]) for x in truth)
    report = {"fold": i, "family_roles": family_role, "rows": len(truth), "excluded_train_anomalies": skipped,
              "split_counts": {s: {label: counts[(s, label)] for label in ("normal", "anomaly")}
                               for s in ("train", "calibration", "holdout", "challenge")},
              "group_policy": "whole-family separation; image identity used as specimen proxy, FP/PCB == FP/image",
              "warning": "Exploratory; physical DUT identifiers are unavailable. Union bboxes are not pixel segmentation."}
    return truth, report

def save_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if digest(path) == hashlib.sha256(data).hexdigest():
            return
        raise FileExistsError(f"manifest already exists with different content: {path}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="extracted VisA root")
    parser.add_argument("--out", type=Path, required=True, help="output manifests folder (NVMe)")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    sample_data = load_dataset(root)
    evidence = [x["_annotation"] for x in sample_data]
    evidence_bytes = ("\n".join(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in evidence) + "\n").encode()
    save_immutable(args.out / "annotation_evidence.jsonl", evidence_bytes)
    for fold in range(4):
        truth, report = make_fold(sample_data, fold)
        data = ("\n".join(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in truth) + "\n").encode()
        report["ground_truth_sha256"] = hashlib.sha256(data).hexdigest()
        report["archive_sha256"] = ARCHIVE_SHA256
        save_immutable(args.out / f"fold_{fold}.jsonl", data)
        save_immutable(args.out / f"fold_{fold}.meta.json", (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())
        print(f"FOLD_{fold}=PASS rows={len(truth)} sha={report['ground_truth_sha256']} counts={report['split_counts']}", flush=True)
    print(f"ALL_FOLDS=PASS source_images={len(sample_data)} evidence={len(evidence)}", flush=True)

if __name__ == "__main__":
    main()
