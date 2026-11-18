"""Build RE2-OB training tables (R2).

  python -m features.build_re2ob --root data/RE2/RE2-OB --out data/features/re2ob-v0

Writes (git-ignored, under data/):
  ranking.parquet   one row per (case, fault_active window, candidate service); target=1 for the root cause
  detection.parquet one row per (case, normal or fault_active window); target=1 for fault_active
  edges.parquet     raw per-window directed edge stats (for later edge ranking work)
  cases.parquet     case index with label counts and data-quality notes
  folds.json        repetition-based 3-fold split (test case ids per fold)
  build-summary.json parameters, input checksum, code commit, counts, missing ratios
Only columns starting with "f_" are model inputs; "meta_*" and "target" are not.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
import pandas as pd

from features import compute, schema
from features.adapters import re2ob
from features.windows import label_re2ob, make_windows

DETECTION_SOURCES = ("f_cm_", "f_ct_", "f_log_", "f_nbr_")
DETECTION_SKIP_SUFFIX = ("_n", "_zero_iqr", "_mask")


def build_case(case, with_logs=True):
    metrics = re2ob.load_metrics(case)
    spans = re2ob.load_spans(case)
    logs = re2ob.load_logs(case) if with_logs else pd.DataFrame(columns=["t", "service", "err"])
    t_min, t_max = metrics["t"].min(), metrics["t"].max()
    windows = make_windows(case.onset, t_min, t_max + 1)
    windows["label"] = windows["rel"].map(label_re2ob)
    base_mask = (windows["label"] == "baseline_stats").to_numpy()
    feats, edge_keys, edge_arr = compute.node_features(
        windows, compute.metric_stats(metrics, windows), *compute.span_stats(spans, windows),
        compute.log_stats(logs, windows), base_mask)
    feats = feats.merge(windows[["rel", "label"]].rename(columns={"rel": "meta_rel", "label": "meta_label"}),
                        left_on="meta_window", right_index=True)
    meta = {"meta_case_id": case.case_id, "meta_fault": case.fault, "meta_root_cause": case.root_cause,
            "meta_repetition": case.repetition, "meta_fold": case.repetition}
    for k, v in meta.items():
        feats[k] = v

    ranking = feats[feats["meta_label"] == "fault_active"].copy()
    ranking[schema.TARGET_COLUMN] = (ranking["meta_candidate"] == case.root_cause).astype(np.int8)

    det_cols = [c for c in feats.columns if c.startswith(DETECTION_SOURCES) and not c.endswith(DETECTION_SKIP_SUFFIX)]
    rows = feats[feats["meta_label"].isin(["normal", "fault_active"])]
    with np.errstate(all="ignore"):
        agg = rows.groupby("meta_window")[det_cols].agg(["max", "mean"])
    agg.columns = [f"{c}__{s}" for c, s in agg.columns]
    lab = rows.groupby("meta_window")[["meta_rel", "meta_label"]].first()
    detection = agg.join(lab).reset_index()
    for k, v in meta.items():
        detection[k] = v
    detection[schema.TARGET_COLUMN] = (detection["meta_label"] == "fault_active").astype(np.int8)

    edges = []
    for (src, dst) in edge_keys:
        e = pd.DataFrame({k: v for k, v in edge_arr[(src, dst)].items()})
        e["meta_window"] = np.arange(len(e))
        e["meta_src"], e["meta_dst"] = src, dst
        edges.append(e)
    edges = pd.concat(edges, ignore_index=True) if edges else pd.DataFrame()
    if len(edges):
        edges = edges.merge(windows[["rel", "label"]].rename(columns={"rel": "meta_rel", "label": "meta_label"}),
                            left_on="meta_window", right_index=True)
        edges["meta_case_id"] = case.case_id

    counts = windows["label"].value_counts().to_dict()
    info = {"case_id": case.case_id, "root_cause": case.root_cause, "fault": case.fault,
            "repetition": case.repetition, "fold": case.repetition, "onset": case.onset,
            "seconds_after_onset": float(t_max - case.onset), "n_spans": int(len(spans)),
            "n_logs": int(len(logs)), **{f"windows_{k}": int(v) for k, v in counts.items()},
            "root_cause_has_metrics": bool(metrics["service"].eq(case.root_cause).any()),
            "root_cause_traced": bool(spans["service"].eq(case.root_cause).any())}
    return ranking, detection, edges, info


def _run(args):
    case, with_logs = args
    return build_case(case, with_logs)


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="data/RE2/RE2-OB")
    ap.add_argument("--out", default=f"data/features/re2ob-{schema.FEATURE_VERSION}")
    ap.add_argument("--limit", type=int, help="only the first N cases (smoke test)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-logs", action="store_true")
    args = ap.parse_args()
    started = time.time()
    cases = re2ob.list_cases(args.root)[: args.limit]
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; use a new --out (outputs are never overwritten)")
    out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_run, [(c, not args.no_logs) for c in cases]))
    ranking = pd.concat([r[0] for r in results], ignore_index=True)
    detection = pd.concat([r[1] for r in results], ignore_index=True)
    edges = pd.concat([r[2] for r in results if len(r[2])], ignore_index=True)
    infos = pd.DataFrame([r[3] for r in results])
    ranking.to_parquet(out / "ranking.parquet", index=False)
    detection.to_parquet(out / "detection.parquet", index=False)
    edges.to_parquet(out / "edges.parquet", index=False)
    infos.to_parquet(out / "cases.parquet", index=False)
    folds = {str(k): sorted(infos.loc[infos["fold"] == k, "case_id"]) for k in sorted(infos["fold"].unique())}
    (out / "folds.json").write_text(json.dumps(folds, indent=2), encoding="utf-8")
    fcols = [c for c in ranking.columns if c.startswith(schema.FEATURE_PREFIX)]
    checksums = Path(args.root).parent / "CHECKSUMS.txt"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "features"], capture_output=True, text=True).stdout.strip())
    summary = {
        "feature_version": schema.FEATURE_VERSION, "code_commit": commit, "features_dir_dirty": dirty,
        "input_root": str(args.root), "input_checksums": checksums.read_text().strip() if checksums.exists() else None,
        "params": {"window_s": schema.WINDOW_SECONDS, "stride_s": schema.STRIDE_SECONDS,
                   "resample_s": schema.RESAMPLE_SECONDS, "min_spans": schema.MIN_SPANS,
                   "with_logs": not args.no_logs, "limit": args.limit},
        "cases": int(len(infos)), "folds": {k: len(v) for k, v in folds.items()},
        "ranking": {"rows": int(len(ranking)), "feature_columns": len(fcols),
                    "positives": int(ranking[schema.TARGET_COLUMN].sum())},
        "detection": {"rows": int(len(detection)), "positives": int(detection[schema.TARGET_COLUMN].sum()),
                      "feature_columns": len([c for c in detection.columns if c.startswith(schema.FEATURE_PREFIX)])},
        "missing_ratio_ranking": {c: round(float(ranking[c].isna().mean()), 4) for c in fcols},
        "elapsed_s": round(time.time() - started, 1),
    }
    (out / "build-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "missing_ratio_ranking"}, indent=2))


if __name__ == "__main__":
    main()
