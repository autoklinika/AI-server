#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path

CAPABILITIES = (
    "schematic_symptom_measurements",
    "good_bad_channels",
    "numeric_waveform",
    "thermal_intermittent",
    "pcb_short",
    "good_bad_channel_comparison",
    "insufficient_data",
    "borderline_sufficient",
)

def rows(path: Path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def prompt(row):
    return str(row.get("prompt") or row.get("user") or row.get("instruction") or "")

def category(row):
    return row.get("category") or row.get("metadata", {}).get("category") or "unknown"

def normalized(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\b[tp]?-?\d{3,}\b", "<id>", text)
    text = re.sub(r"\b\d+(?:[.,]\d+)?\s*°?c\b", "<temp>", text)
    text = re.sub(r"\b\d+(?:[.,]\d+)?\b", "<n>", text)
    text = re.sub(r"[^a-ząćęłńóśźż0-9<>]+", " ", text)
    return " ".join(text.split())

def tokens(text: str):
    return set(normalized(text).split())

def jaccard(a: str, b: str) -> float:
    x, y = tokens(a), tokens(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def summarize(path: Path):
    data = rows(path)
    prompts = [prompt(x) for x in data]
    norms = [normalized(x) for x in prompts]
    cats = collections.Counter(category(x) for x in data)
    nc = collections.Counter(norms)
    return {
        "path": str(path),
        "sha256": sha(path),
        "records": len(data),
        "categories": dict(sorted(cats.items())),
        "exact_unique_prompts": len(set(prompts)),
        "normalized_unique_prompts": len(set(norms)),
        "normalized_duplicate_rows": sum(n - 1 for n in nc.values() if n > 1),
    }, data

def near_duplicate_pairs(left, right, threshold: float):
    result = []
    for a in left:
        pa = prompt(a)
        for b in right:
            pb = prompt(b)
            score = jaccard(pa, pb)
            if score >= threshold:
                result.append({
                    "left_id": a.get("case_id") or a.get("record_id"),
                    "right_id": b.get("case_id") or b.get("record_id"),
                    "similarity": round(score, 4),
                })
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", action="append", nargs=2, metavar=("NAME", "PATH"), required=True)
    ap.add_argument("--near-threshold", type=float, default=0.82)
    ap.add_argument("--output")
    args = ap.parse_args()

    summaries = {}
    datasets = {}
    for name, raw in args.split:
        p = Path(raw)
        summaries[name], datasets[name] = summarize(p)

    overlaps = {}
    names = list(datasets)
    for i, a in enumerate(names):
        an = {normalized(prompt(x)) for x in datasets[a]}
        for b in names[i + 1:]:
            bn = {normalized(prompt(x)) for x in datasets[b]}
            exact = sorted(an & bn)
            near = near_duplicate_pairs(datasets[a], datasets[b], args.near_threshold)
            overlaps[f"{a}__{b}"] = {
                "normalized_exact_overlap": len(exact),
                "near_duplicate_pairs": len(near),
                "near_duplicate_examples": near[:25],
            }

    checks = {}
    for name, summary in summaries.items():
        checks[f"{name}_has_prompts"] = summary["exact_unique_prompts"] > 0
        checks[f"{name}_no_normalized_duplicates"] = summary["normalized_duplicate_rows"] == 0

    for key, value in overlaps.items():
        checks[f"{key}_no_normalized_overlap"] = value["normalized_exact_overlap"] == 0
        checks[f"{key}_no_near_overlap"] = value["near_duplicate_pairs"] == 0

    out = {
        "schema_version": 1,
        "near_threshold": args.near_threshold,
        "summaries": summaries,
        "cross_split_overlap": overlaps,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
    }
    text = json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(text)
    print(text, end="")
    print("P510_DATA_AUDIT=" + out["status"])

if __name__ == "__main__":
    main()
