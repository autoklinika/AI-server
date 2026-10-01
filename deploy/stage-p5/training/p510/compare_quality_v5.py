#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

WEIGHTS = {
    "diagnostic_model_pass": 0.25,
    "measurement_pass": 0.30,
    "prediction_pass": 0.30,
    "no_guessing_pass": 0.15,
}
CORE = (
    "diagnostic_model_pass_rate",
    "measurement_pass_rate",
    "prediction_pass_rate",
    "no_guessing_pass_rate",
    "insufficient_data_abstention_rate",
    "overall_dimension_pass_rate",
)

def load(path):
    return json.loads(Path(path).read_text())

def case_score(row):
    return sum(weight * float(bool(row.get(key))) for key, weight in WEIGHTS.items())

def bootstrap_ci(values, resamples=5000, seed=20261001):
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0}
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * (resamples - 1))]
    hi = means[int(0.975 * (resamples - 1))]
    return {"mean": sum(values) / n, "low": lo, "high": hi, "n": n}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-records", type=int, default=64)
    ap.add_argument("--max-core-regression", type=float, default=0.03)
    ap.add_argument("--noninferiority-margin", type=float, default=0.01)
    ap.add_argument("--min-no-guessing", type=float, default=0.98)
    ap.add_argument("--min-abstention", type=float, default=0.95)
    ap.add_argument("--resamples", type=int, default=5000)
    args = ap.parse_args()

    parent = load(args.parent)
    candidate = load(args.candidate)
    pd = {x["case_id"]: x for x in parent["details"]}
    cd = {x["case_id"]: x for x in candidate["details"]}
    same_cases = set(pd) == set(cd)

    common = sorted(set(pd) & set(cd))
    deltas = [case_score(cd[k]) - case_score(pd[k]) for k in common]
    paired = bootstrap_ci(deltas, args.resamples)
    pm, cm = parent["metrics"], candidate["metrics"]
    metric_delta = {k: float(cm[k]) - float(pm[k]) for k in CORE}

    checks = {
        "same_cases": same_cases,
        "minimum_records": len(common) >= args.min_records,
        "candidate_parse": float(cm["final_parse_rate"]) >= 1.0,
        "candidate_no_guessing": float(cm["no_guessing_pass_rate"]) >= args.min_no_guessing,
        "candidate_abstention": float(cm["insufficient_data_abstention_rate"]) >= args.min_abstention,
        "point_improvement": float(cm["selection_score"]) > float(pm["selection_score"]),
        "paired_noninferior": paired["low"] >= -args.noninferiority_margin,
        "core_regression_guard": all(v >= -args.max_core_regression for v in metric_delta.values()),
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    out = {
        "status": status,
        "checks": checks,
        "records": len(common),
        "parent_selection_score": pm["selection_score"],
        "candidate_selection_score": cm["selection_score"],
        "selection_score_delta": float(cm["selection_score"]) - float(pm["selection_score"]),
        "paired_case_score_delta_95": paired,
        "metric_delta": metric_delta,
        "thresholds": {
            "min_records": args.min_records,
            "max_core_regression": args.max_core_regression,
            "noninferiority_margin": args.noninferiority_margin,
            "min_no_guessing": args.min_no_guessing,
            "min_abstention": args.min_abstention,
        },
    }

    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    print("P510_PAIRED_GATE=" + status)
    if status != "PASS":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
