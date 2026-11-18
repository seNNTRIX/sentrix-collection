"""Raw (un-normalised) counterparts of the rel18 features for the R7 ablation.

  python -m features.build_raw_r7 --root data/RE2/RE2-OB --out data/features/re2ob-r7-raw

Same cases, 5 s grid, windows and labels as features/build_re2ob.py; reuses features/compute.py
(metric_stats, span_stats, _baseline, _log_ratio) unchanged. Logs are not read.

Writes raw_nodes.parquet: one row per (case, window, candidate) for every labelled window with
  f_raw_<sig>_mean, f_raw_<sig>_max     window mean / max of the 6 metric signals (= f_opt_* in ranking.parquet)
  f_raw_in_rate, f_raw_in_err, f_raw_in_p50, f_raw_in_p90
  f_raw_out_p90, f_raw_in_edge_p90      max over outgoing / incoming edges of the client p90
  chk_in_p90_lr                         log ratio recomputed from f_raw_in_p90 (consistency check only)
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from features import compute, schema
from features.adapters import re2ob
from features.windows import label_re2ob, make_windows


def build_case(case):
    metrics = re2ob.load_metrics(case)
    spans = re2ob.load_spans(case)
    t_min, t_max = metrics["t"].min(), metrics["t"].max()
    windows = make_windows(case.onset, t_min, t_max + 1)
    windows["label"] = windows["rel"].map(label_re2ob)
    base_mask = (windows["label"] == "baseline_stats").to_numpy()
    mstats = compute.metric_stats(metrics, windows)
    node, edge = compute.span_stats(spans, windows)
    nw = len(windows)
    edge_keys = sorted({(s, d) for _, s, d in edge})
    p90 = {k: np.array([edge.get((wi, *k), {}).get("p90", np.nan) for wi in range(nw)]) for k in edge_keys}

    frames = []
    for svc in schema.CANDIDATES:
        def series(store, name):
            return np.array([store.get((wi, svc), {}).get(name, np.nan) for wi in range(nw)], dtype=float)
        col = {}
        for sig in schema.METRIC_SIGNALS:
            col[f"f_raw_{sig}_mean"] = series(mstats, f"{sig}_mean")
            col[f"f_raw_{sig}_max"] = series(mstats, f"{sig}_max")
        for name in ("in_rate", "in_err", "in_p50", "in_p90"):
            col[f"f_raw_{name}"] = series(node, name)
        out_ = [p90[k] for k in edge_keys if k[0] == svc]
        in_ = [p90[k] for k in edge_keys if k[1] == svc]
        with np.errstate(all="ignore"):
            col["f_raw_out_p90"] = np.nanmax(np.vstack(out_), axis=0) if out_ else np.full(nw, np.nan)
            col["f_raw_in_edge_p90"] = np.nanmax(np.vstack(in_), axis=0) if in_ else np.full(nw, np.nan)
        col["chk_in_p90_lr"] = compute._log_ratio(col["f_raw_in_p90"], compute._baseline(col["f_raw_in_p90"], base_mask)[0],
                                                  compute.EPS_LAT)
        df = pd.DataFrame(col)
        df.insert(0, "meta_window", np.arange(nw))
        df.insert(1, "meta_candidate", svc)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out = out.merge(windows[["rel", "label"]].rename(columns={"rel": "meta_rel", "label": "meta_label"}),
                    left_on="meta_window", right_index=True)
    out["meta_case_id"] = case.case_id
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="data/RE2/RE2-OB")
    ap.add_argument("--out", default="data/features/re2ob-r7-raw")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    started = time.time()
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; use a new --out (outputs are never overwritten)")
    out.mkdir(parents=True, exist_ok=True)
    cases = re2ob.list_cases(args.root)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        raw = pd.concat(list(ex.map(build_case, cases)), ignore_index=True)
    raw.to_parquet(out / "raw_nodes.parquet", index=False)
    summary = {"cases": int(raw["meta_case_id"].nunique()), "rows": int(len(raw)),
               "labels": raw.groupby("meta_label").size().to_dict(), "elapsed_s": round(time.time() - started, 1)}
    (out / "build-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
