"""Official RCAEval BARO on RE2-OB (reference numbers; RE2-OB results are not published).

Runs inside a separate venv with the PyPI package RCAEval installed
(data/tools/rcaeval-venv, git-ignored), with this repository on PYTHONPATH:

  PYTHONPATH=. data/tools/rcaeval-venv/Scripts/python -m evaluation.run_rcaeval_baro \
      --root data/RE2/RE2-OB --file simple_metrics.csv --out experiments/<id>/baro_simple.json

Protocol = RCAEval's: normal = rows before inject_time, anomalous = rows from inject_time
on (the whole 720 s after injection, not our 60-300 s horizon). The function call is
RCAEval.e2e.baro.baro(data, inject_time, dataset="re2-ob"). Two service-level scores:
  dedup   : metric ranking -> first occurrence of each service, scored with
            evaluation.metrics (same code and tie rule as our baselines)
  rcaeval : RCAEval Evaluator "service" accuracy, re-implemented from
            RCAEval/benchmark/evaluation.py (add_case: hit@k = root service in the
            entities of the top-k METRIC nodes; duplicates not removed). The
            Evaluator itself is not imported because its module pulls the package's
            very large "default" extra (requests, boto, ...).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from RCAEval.e2e.baro import baro

from evaluation import metrics as M
from features.adapters.re2ob import canonical, list_cases
from features.schema import CANDIDATES


def service_of(col):
    return canonical(col.split("_", 1)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/RE2/RE2-OB")
    ap.add_argument("--file", default="simple_metrics.csv")
    ap.add_argument("--out", required=True)
    ap.add_argument("--official", action="store_true", help="replicate RCAEval main.py preprocessing for re2-ob")
    ap.add_argument("--length", type=int, default=20, help="main.py --length (minutes, total)")
    ap.add_argument("--drop-col", action="append", default=[],
                    help="NOT official: drop a column before BARO (sensitivity check)")
    args = ap.parse_args()
    coarse = {k: 0 for k in range(1, 6)}
    cases, per_case = [], []
    for case in list_cases(args.root):
        data = pd.read_csv(case.path / args.file)
        if args.official:
            # RCAEval main.py (github.com/phamquiluan/RCAEval, main branch) for --dataset re2-ob:
            # drop time.1 and *_latency-50, inf->NaN, ffill, fillna(0), keep length*60//2 rows
            # (default length 20 -> 600) on each side of inject_time, *_latency-90 -> *_latency.
            data = data.drop(columns=["time.1"], errors="ignore")
            data = data.loc[:, ~data.columns.str.endswith("_latency-50")]
            data = data.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
            inject = int(case.onset)
            half = args.length * 60 // 2
            data = pd.concat([data[data["time"] < inject].tail(half), data[data["time"] >= inject].head(half)],
                             ignore_index=True)
            data.columns = [c.replace("_latency-90", "_latency") for c in data.columns]
            data = data.drop(columns=args.drop_col, errors="ignore")   # sensitivity only; empty = official
            out = baro(data, inject, dataset="re2-ob", anomalies=None, dk_select_useful=False)
        else:
            data = data[pd.to_numeric(data["time"], errors="coerce").notna()].copy()
            data["time"] = data["time"].astype(float)
            out = baro(data, case.onset, dataset="re2-ob")
        ranks = out["ranks"]
        order = []
        for col in ranks:
            s = service_of(col)
            if s and s not in order:
                order.append(s)
        # services never ranked share the lowest score
        scores = np.array([len(order) - order.index(c) if c in order else 0 for c in CANDIDATES], dtype=float)
        idx = list(CANDIDATES).index(case.root_cause)
        cases.append((scores, idx))
        entities = [service_of(c) or c.split("_", 1)[0] for c in ranks]
        for k in coarse:
            coarse[k] += int(case.root_cause in entities[:k])
        hit = M.case_hit_at(scores, idx, 1)
        per_case.append({"case_id": case.case_id, "fault": case.fault, "top3_services": order[:3], "AC@1": hit})
    res = {"file": args.file, "official_protocol": args.official and not args.drop_col,
           "dropped_columns": args.drop_col, "length": args.length if args.official else None,
           "n_cases": len(cases), "dedup": M.ranking_summary(cases),
           "rcaeval_service": {"AC@1": coarse[1] / len(cases), "AC@3": coarse[3] / len(cases),
                               "Avg@5": sum(coarse[k] for k in range(1, 6)) / 5 / len(cases)},
           "by_fault_dedup": {}}
    for fault in sorted({p["fault"] for p in per_case}):
        fc = [c for c, p in zip(cases, per_case) if p["fault"] == fault]
        res["by_fault_dedup"][fault] = {k: round(v, 3) for k, v in M.ranking_summary(fc).items() if k != "n_cases"}
    res["per_case"] = per_case
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("per_case", "by_fault_dedup")}, indent=2))


if __name__ == "__main__":
    main()
