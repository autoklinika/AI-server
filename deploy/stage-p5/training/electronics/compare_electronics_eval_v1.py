#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path


def compare(base: dict, tuned: dict, min_relative_improvement: float = 0.05) -> dict:
    if base.get("status") != "PASS" or tuned.get("status") != "PASS":
        raise ValueError("evaluation status is not PASS")
    if base.get("records") != tuned.get("records"):
        raise ValueError("evaluation record count mismatch")
    b = float(base["token_weighted_loss"])
    t = float(tuned["token_weighted_loss"])
    if not (b > 0 and t > 0):
        raise ValueError("invalid loss")
    improvement = (b - t) / b
    return {
        "base_token_weighted_loss": b,
        "tuned_token_weighted_loss": t,
        "absolute_improvement": b - t,
        "relative_improvement": improvement,
        "min_relative_improvement": min_relative_improvement,
        "gate_pass": improvement >= min_relative_improvement,
        "records": base["records"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tuned", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--min-relative-improvement", type=float, default=0.05)
    args = ap.parse_args()
    base = json.loads(Path(args.base).read_text())
    tuned = json.loads(Path(args.tuned).read_text())
    result = compare(base, tuned, args.min_relative_improvement)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    if not result["gate_pass"]:
        raise SystemExit("P5_2_ELECTRONICS_HOLDOUT_GATE=FAIL")
    print("P5_2_ELECTRONICS_HOLDOUT_GATE=PASS")


if __name__ == "__main__":
    main()
