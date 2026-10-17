#!/usr/bin/env python3
"""Vision PCB V1: stdlib-only, fail-closed offline benchmark scorer.

Real model inference/training belongs to isolated, Resource-Manager-admitted runners.
This tool verifies manifests, freezes calibration and evaluates supplied predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import statistics
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
CATALOG = {
    "minicpm-v4.7-35b-a3b": "vlm",
    "minicpm-v4.7-1b": "vlm",
    "minicpm-v4.6": "vlm",
    "qwen3-vl-8b": "vlm",
    "patchcore": "anomaly",
    "yolo": "detection",
    "winclip": "anomaly",
}
SPLITS = {"train", "calibration", "holdout", "challenge"}


class BenchmarkError(ValueError):
    pass


def require(cond: bool, message: str) -> None:
    if not cond:
        raise BenchmarkError(message)


def load_jsonl(path: pathlib.Path) -> list[dict]:
    require(path.is_file(), f"file missing: {path}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BenchmarkError(f"{path}:{line_number} invalid JSON: {exc}") from exc
        require(isinstance(item, dict), f"{path}:{line_number} expected JSON object")
        rows.append(item)
    require(bool(rows), f"empty JSONL: {path}")
    return rows


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def score01(value: object, where: str) -> float:
    require(type(value) in (int, float), f"{where}: expected numeric score")
    score = float(value)
    require(math.isfinite(score) and 0 <= score <= 1, f"{where}: score outside [0,1]")
    return score


def box4(value: object, where: str) -> tuple[float, float, float, float]:
    require(isinstance(value, list) and len(value) == 4, f"{where}: expected 4 box coords")
    coords = tuple(score01(v, where) for v in value)
    x1, y1, x2, y2 = coords
    require(x1 < x2 and y1 < y2, f"{where}: invalid box order")
    return coords


def validate_ground(rows: list[dict], check_files: bool = False, base: pathlib.Path | None = None) -> dict:
    observed = {}
    seen_specimens: dict[str, str] = {}
    seen_sources: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    families: dict[str, set[str]] = defaultdict(set)
    counts = Counter()
    for row in rows:
        needed = ("sample_id", "dataset", "family", "specimen_id", "source_id", "split", "label", "sha256", "regions")
        require(all(k in row for k in needed), f"missing required GT fields: {row.get('sample_id', '?')}")
        sid = row["sample_id"]
        require(isinstance(sid, str) and sid and sid not in observed, f"duplicate/invalid sample_id: {sid}")
        split = row["split"]
        require(split in SPLITS, f"{sid}: unsupported split {split}")
        require(row["label"] in ("normal", "anomaly"), f"{sid}: invalid label")
        require(all(isinstance(row[k], str) and row[k] for k in ("dataset", "family", "specimen_id", "source_id")), f"{sid}: missing group ids")
        checksum = row["sha256"]
        require(isinstance(checksum, str) and len(checksum) == 64 and all(c in '0123456789abcdef' for c in checksum), f"{sid}: bad sha256")
        require(isinstance(row["regions"], list), f"{sid}: regions must be a list")
        if row["label"] == "normal":
            require(not row["regions"], f"{sid}: normal sample has defect regions")
        for i, region in enumerate(row["regions"]):
            require(isinstance(region, dict) and isinstance(region.get("class"), str) and region["class"], f"{sid}: invalid region class")
            box4(region.get("box"), f"{sid}:GT region {i}")
        for key, seen, group in (("specimen_id", seen_specimens, row["specimen_id"]), ("source_id", seen_sources, row["source_id"]), ("sha256", seen_hashes, checksum)):
            if group in seen:
                require(seen[group] == split, f"LEAKAGE {key}={group}: {seen[group]} versus {split}")
            seen[group] = split
        if check_files:
            require(base is not None, "--image-root required with --check-files")
            require("image_path" in row and isinstance(row["image_path"], str), f"{sid}: image_path missing")
            resolved = (base / row["image_path"]).resolve()
            require(resolved.is_relative_to(base.resolve()), f"{sid}: path escapes image root")
            require(resolved.is_file(), f"{sid}: missing image {resolved}")
            require(sha256(resolved) == checksum, f"{sid}: image checksum mismatch")
        observed[sid] = row
        families[split].add(row["family"])
        counts[f"{split}:{row['label']}"] += 1
    require(not (families['challenge'] & (families['train'] | families['calibration'] | families['holdout'])), "LEAKAGE: challenge families occur in another split")
    return {"count": len(observed), "splits": dict(counts), "families": {k: sorted(v) for k, v in families.items() if v}}


def validate_predictions(rows: list[dict], truth: list[dict], split: str) -> tuple[str, dict[str, dict]]:
    require(split in ("calibration", "holdout", "challenge"), f"not a scoring split: {split}")
    expected = {row["sample_id"] for row in truth if row["split"] == split}
    require(bool(expected), f"GT does not contain split={split}")
    predictions = {}
    models = set()
    for row in rows:
        sid = row.get("sample_id")
        require(isinstance(sid, str) and sid not in predictions, f"duplicate/invalid prediction id: {sid}")
        require(sid in expected, f"unexpected prediction {sid} (other split or unknown)")
        model = row.get("model_id")
        require(model in CATALOG, f"unsupported model_id: {model}")
        models.add(model)
        score01(row.get("image_score"), f"{sid}:image_score")
        mode = row.get("localization_mode")
        require(mode in ("none", "boxes"), f"{sid}: localization_mode must be none or boxes")
        regions = row.get("regions")
        require(isinstance(regions, list), f"{sid}: regions must be list")
        require(mode == "boxes" or not regions, f"{sid}: nonempty regions with localization_mode=none")
        for i, region in enumerate(regions):
            require(isinstance(region, dict), f"{sid}: invalid predicted region {i}")
            score01(region.get("score"), f"{sid}: region {i}")
            box4(region.get("box"), f"{sid}: region {i}")
        predictions[sid] = row
    require(len(models) == 1, "prediction file must refer to exactly one model")
    require(set(predictions) == expected, f"incomplete prediction coverage: missing {len(expected - set(predictions))}, extra {len(set(predictions) - expected)}")
    modes = {row["localization_mode"] for row in rows}
    require(len(modes) == 1, "mixed localization_mode in one run")
    return models.pop(), predictions


def thresholds_calibrate(truth: list[dict], pred: dict[str, dict], target_fpr: float) -> dict:
    normal_scores = sorted(row["image_score"] for sid, row in pred.items() if next(x for x in truth if x['sample_id'] == sid)['label'] == 'normal')
    require(normal_scores, "calibration needs normal images")
    require(any(x["label"] == "anomaly" and x["sample_id"] in pred for x in truth), "calibration needs anomalous images")
    # Candidate thresholds guarantee all observed negative scores <= threshold classify as normal.
    # Selection uses ONLY calibration normals, not holdout or challenge labels/predictions.
    candidates = sorted(set([0.0, 1.0] + [math.nextafter(v, math.inf) for v in normal_scores if v < 1.0]))
    eligible = [t for t in candidates if sum(s >= t for s in normal_scores) / len(normal_scores) <= target_fpr]
    require(bool(eligible), "cannot satisfy target FPR: normal score of 1.0")
    chosen = min(eligible)
    require(chosen <= 1.0, "invalid threshold")
    return {"image_threshold": chosen, "calibration_fpr": sum(s >= chosen for s in normal_scores) / len(normal_scores), "calibration_normals": len(normal_scores)}


def roc_auc(y: list[int], scores: list[float]) -> float | None:
    pos = [s for s, z in zip(scores, y) if z]
    neg = [s for s, z in zip(scores, y) if not z]
    if not pos or not neg:
        return None
    favorable = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return favorable / (len(pos) * len(neg))


def average_precision(y: list[int], scores: list[float]) -> float | None:
    positives = sum(y)
    if not positives:
        return None
    # Group equal-score ties: invariant to input row order.
    buckets = defaultdict(lambda: [0, 0])
    for label, score in zip(y, scores):
        buckets[score][label] += 1
    tp = fp = 0
    area = 0.0
    for score in sorted(buckets, reverse=True):
        fp += buckets[score][0]
        tp += buckets[score][1]
        area += buckets[score][1] / positives * (tp / (tp + fp))
    return area


def box_iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection)


def region_score(gold: list[dict], predictions: dict[str, dict], split: str, region_threshold: float, iou_threshold: float) -> dict:
    records = [row for row in gold if row["split"] == split]
    mode = next(iter({predictions[r['sample_id']]['localization_mode'] for r in records}))
    if mode == "none":
        return {"status": "not_supported", "recall": None, "precision": None, "false_alarms_per_pcb": None, "mean_best_iou": None}
    tp = fp = fn = 0
    best_iou = []
    for row in records:
        gt = [box4(r['box'], 'GT') for r in row['regions']]
        detected = [box4(r['box'], 'prediction') for r in predictions[row['sample_id']]['regions'] if r['score'] >= region_threshold]
        # Maximum-cardinality matching, then maximum total IoU (DP exact for <=18 detections; greedy fallback is intentionally NOT allowed).
        edges = [(i, j, box_iou(a, b)) for i, a in enumerate(gt) for j, b in enumerate(detected) if box_iou(a, b) >= iou_threshold]
        if max(len(gt), len(detected)) > 18:
            # Deterministic maximum bipartite matching via augmenting paths, without falsely inflating recall.
            adjacency = defaultdict(list)
            for i, j, w in sorted(edges, key=lambda x: -x[2]):
                adjacency[i].append(j)
            matched: dict[int, int] = {}
            def augment(i: int, seen: set[int]) -> bool:
                for j in adjacency[i]:
                    if j not in seen:
                        seen.add(j)
                        if j not in matched or augment(matched[j], seen):
                            matched[j] = i
                            return True
                return False
            matches = sum(augment(i, set()) for i in range(len(gt)))
        else:
            # Exact max matches with bitmask DP across predicted regions.
            from functools import lru_cache
            adjacency = defaultdict(list)
            for i, j, w in edges:
                adjacency[i].append((j, w))
            @lru_cache(None)
            def solve(i: int, mask: int) -> tuple[int, float]:
                if i == len(gt):
                    return (0, 0.0)
                best = solve(i + 1, mask)
                for j, w in adjacency[i]:
                    if not mask & (1 << j):
                        n, s = solve(i + 1, mask | (1 << j))
                        candidate = (n + 1, s + w)
                        if candidate > best:
                            best = candidate
                return best
            matches = solve(0, 0)[0]
        tp += matches
        fn += len(gt) - matches
        fp += len(detected) - matches
        best_iou.extend(max((box_iou(a, b) for b in detected), default=0.0) for a in gt)
    return {
        "status": "evaluated", "recall": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "false_alarms_per_pcb": fp / len({row["specimen_id"] for row in records}),
        "mean_best_iou": statistics.mean(best_iou) if best_iou else None,
        "tp": tp, "fp": fp, "fn": fn,
    }


def evaluate(truth: list[dict], pred: dict[str, dict], split: str, threshold: float, region_threshold: float, iou_threshold: float) -> dict:
    rows = [row for row in truth if row['split'] == split]
    labels = [int(row['label'] == 'anomaly') for row in rows]
    scores = [pred[row['sample_id']]['image_score'] for row in rows]
    positives, negatives = sum(labels), len(labels) - sum(labels)
    tp = sum(l and s >= threshold for l, s in zip(labels, scores))
    fp = sum(not l and s >= threshold for l, s in zip(labels, scores))
    return {
        "split": split, "samples": len(rows), "positives": positives, "negatives": negatives,
        "image": {
            "auroc": roc_auc(labels, scores),
            "average_precision": average_precision(labels, scores),
            "recall": tp / positives if positives else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "false_positive_rate": fp / negatives if negatives else None,
            "false_alarms_per_pcb": fp / len({row["specimen_id"] for row in rows}),
            "tp": tp, "fp": fp, "fn": positives - tp,
        },
        "localization": region_score(truth, pred, split, region_threshold, iou_threshold),
    }


def save_json(path: pathlib.Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"output already exists (immutable artifacts): {path}")
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n')


def cmd_validate(args: argparse.Namespace) -> None:
    rows = load_jsonl(args.ground_truth)
    summary = validate_ground(rows, args.check_files, args.image_root)
    print(json.dumps({"status": "PASS", **summary}, ensure_ascii=False, indent=2))


def cmd_calibrate(args: argparse.Namespace) -> None:
    require(0 <= args.max_fpr < 1, "--max-fpr must be in [0,1)")
    truth = load_jsonl(args.ground_truth)
    validate_ground(truth)
    model, pred = validate_predictions(load_jsonl(args.predictions), truth, 'calibration')
    result = thresholds_calibrate(truth, pred, args.max_fpr)
    result.update({"schema_version": 1, "model_id": model, "ground_truth_sha256": sha256(args.ground_truth),
                   "calibration_predictions_sha256": sha256(args.predictions), "target_fpr": args.max_fpr})
    save_json(args.output, result)
    print(f"CALIBRATION=PASS model={model} threshold={result['image_threshold']:.8f} target_fpr={args.max_fpr}")


def cmd_score(args: argparse.Namespace) -> None:
    truth = load_jsonl(args.ground_truth)
    validate_ground(truth)
    model, pred = validate_predictions(load_jsonl(args.predictions), truth, args.split)
    thresholds = json.loads(args.thresholds.read_text(encoding='utf-8'))
    require(thresholds.get('schema_version') == 1 and thresholds.get('model_id') == model, 'model mismatch / unsupported calibration')
    require(thresholds.get('ground_truth_sha256') == sha256(args.ground_truth), 'ground-truth changed since calibration')
    require(thresholds.get('calibration_predictions_sha256') and thresholds.get('calibration_normals', 0) > 0, 'invalid calibration provenance')
    require(sha256(args.calibration_predictions) == thresholds['calibration_predictions_sha256'], 'calibration predictions changed since calibration')
    calibration_model, calibration_rows = validate_predictions(load_jsonl(args.calibration_predictions), truth, 'calibration')
    require(calibration_model == model, 'calibration model mismatch')
    target_fpr = score01(thresholds.get('target_fpr'), 'target_fpr')
    require(target_fpr < 1, 'target_fpr must be < 1')
    expected = thresholds_calibrate(truth, calibration_rows, target_fpr)
    require(all(thresholds.get(k) == expected[k] for k in ('image_threshold', 'calibration_fpr', 'calibration_normals')), 'calibration proof failed')
    image_t = score01(thresholds.get('image_threshold'), 'calibration threshold')
    result = {"schema_version": 1, "model_id": model, "catalog_class": CATALOG[model],
              "ground_truth_sha256": sha256(args.ground_truth), "prediction_sha256": sha256(args.predictions),
              "calibration_sha256": sha256(args.thresholds), "image_threshold": image_t,
              "region_threshold": args.region_threshold, "iou_threshold": args.iou_threshold,
              "metrics": evaluate(truth, pred, args.split, image_t, args.region_threshold, args.iou_threshold),
              "caveats": ["Bounding-box localization is NOT pixel-AUPRO.", "Inference latency and VRAM are not measured by this offline scorer."]}
    save_json(args.output, result)
    print(f"SCORE=PASS model={model} split={args.split} samples={result['metrics']['samples']}")


def cmd_compare(args: argparse.Namespace) -> None:
    reports = [json.loads(p.read_text(encoding='utf-8')) for p in args.reports]
    require(len(reports) >= 2, "compare requires >=2 reports")
    require(all(r.get('schema_version') == 1 for r in reports), 'unsupported report')
    require(len({r['model_id'] for r in reports}) == len(reports), 'duplicate model report')
    require(len({(r['metrics']['split'], r['ground_truth_sha256']) for r in reports}) == 1, 'different split / dataset versions: not comparable')
    require(len({(r.get('region_threshold'), r.get('iou_threshold')) for r in reports}) == 1, 'different localization policies: not comparable')
    def fmt(value: object) -> str:
        return 'N/A' if value is None else f'{value:.4f}'
    table = ['# Vision PCB V1 — porównanie modeli', '', f"Split: `{reports[0]['metrics']['split']}`. Wyniki rzeczywiste wyłącznie po ocenie kompletnych predykcji.", '',
             '| Model | Image AUROC | Image AUPR | Recall | FPR | Region Recall | False regions/PCB |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for report in sorted(reports, key=lambda r:r['model_id']):
        image, loc = report['metrics']['image'], report['metrics']['localization']
        table.append('| ' + ' | '.join([report['model_id'], fmt(image['auroc']), fmt(image['average_precision']), fmt(image['recall']),
                                         fmt(image['false_positive_rate']), fmt(loc['recall']), fmt(loc['false_alarms_per_pcb'])]) + ' |')
    table += ['', 'Nie porównuj metryk obrazowych z metrykami lokalizacji jako jednego wyniku. Brak masek => AUPRO nieobliczane.']
    require(not args.output.exists(), f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(table) + '\n')
    print(f"COMPARE=PASS models={len(reports)} output={args.output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog')
    validate = sub.add_parser('validate')
    validate.add_argument('--ground-truth', required=True, type=pathlib.Path)
    validate.add_argument('--check-files', action='store_true')
    validate.add_argument('--image-root', type=pathlib.Path)
    calibrate = sub.add_parser('calibrate')
    calibrate.add_argument('--ground-truth', required=True, type=pathlib.Path)
    calibrate.add_argument('--predictions', required=True, type=pathlib.Path)
    calibrate.add_argument('--output', required=True, type=pathlib.Path)
    calibrate.add_argument('--max-fpr', type=float, default=0.05)
    score = sub.add_parser('score')
    score.add_argument('--ground-truth', required=True, type=pathlib.Path)
    score.add_argument('--predictions', required=True, type=pathlib.Path)
    score.add_argument('--thresholds', required=True, type=pathlib.Path)
    score.add_argument('--calibration-predictions', required=True, type=pathlib.Path)
    score.add_argument('--split', required=True, choices=['holdout','challenge'])
    score.add_argument('--output', required=True, type=pathlib.Path)
    score.add_argument('--region-threshold', type=float, default=0.5)
    score.add_argument('--iou-threshold', type=float, default=0.3)
    compare = sub.add_parser('compare')
    compare.add_argument('--reports', required=True, nargs='+', type=pathlib.Path)
    compare.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.command == 'catalog':
            print(json.dumps(CATALOG, indent=2))
        elif args.command == 'validate':
            cmd_validate(args)
        elif args.command == 'calibrate':
            cmd_calibrate(args)
        elif args.command == 'score':
            require(0 <= args.region_threshold <= 1 and 0 < args.iou_threshold <= 1, 'invalid localization threshold')
            cmd_score(args)
        else:
            cmd_compare(args)
    except (BenchmarkError, OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(2, f'BENCHMARK=FAIL: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
