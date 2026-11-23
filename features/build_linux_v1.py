"""Build linux-v1 tables with the frozen feature code (docs/METHOD-FREEZE-v2.md, docs/LINUX-V1-DATA-TRANSLATION.md).

  python -m features.build_linux_v1 --out data/features/linux-v1-v0            # full build (2 workers)
  python -m features.build_linux_v1 --out data/features/linux-v1-v0 --resume   # continue after a stop
  python -m features.build_linux_v1 --check-only                               # checks 1-4 only, writes nothing

Checks before any case is built (the build stops on failure):
  1. no linux-v1 run ID in two dataset roots
  2. one adopted attempt per pair (scripts/pair_attempts.adopted_attempt); failed attempts listed with cause
  3. adopted pairs = schedule (69)
  4. features/compute.py sha256 = frozen value
Writes (git-ignored, under data/):
  cases.parquet               one row per run (69 fault + 69 control), times, onset source, eligibility, counts
  ranking.parquet             (eligible cpu_saturation / pod_failure run, fault_active window, candidate 11);
                              target = candidate is the root cause (exactly one per window)
  ranking-nodeview.parquet    same rows for eligible network_delay / packet_loss / traffic_surge runs (target 0;
                              node views and description only, never ranking training)
  detection.parquet           window aggregates (max/mean over candidates) for training/AUROC:
                              positives = fault_active of eligible fault runs, negatives = normal, sham_active,
                              recovered of all runs
  detection-ineligible.parquet fault_active windows of ineligible fault runs (meta_eligible false; alarm rate only)
  edges.parquet               per-window directed edge stats of every run (evaluation.edge_rank)
  folds.json                  repetition folds (fault and control run of a pair in the same fold)
  build-summary.json          parameters, checks, hashes, excluded attempts, counts, missing ratios
Per-case parts are saved under <out>/_parts/<case_id>/ as soon as a case finishes; --resume skips
finished cases. Progress goes to stdout and <out>/build-progress.log.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

import numpy as np
import pandas as pd

from features import compute, schema
from features.adapters import linux_v1
from features.windows import label_linux_v1, make_windows

FROZEN_COMPUTE_SHA256 = "1661a9f1dcc731472f47bff91b981f1e366bf5967d89b4c5b7d2ceebc053cb34"
DETECTION_SOURCES = ("f_cm_", "f_ct_", "f_log_", "f_nbr_")          # as features/build_re2ob.py
DETECTION_SKIP_SUFFIX = ("_n", "_zero_iqr", "_mask")
NEGATIVE_LABELS = ("normal", "sham_active", "recovered")
RANKING_FAULTS = ("cpu_saturation", "pod_failure")
REPO = Path(__file__).resolve().parents[1]
PART_FILES = ("ranking", "ranking_nodeview", "detection", "detection_ineligible", "edges")
OUTPUT_NAMES = {"ranking": "ranking.parquet", "ranking_nodeview": "ranking-nodeview.parquet",
                "detection": "detection.parquet", "detection_ineligible": "detection-ineligible.parquet",
                "edges": "edges.parquet"}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_compute_hash(path=None):
    """Check 4: the frozen feature code is unchanged."""
    path = Path(path or compute.__file__)
    got = file_sha256(path)
    if got != FROZEN_COMPUTE_SHA256:
        raise linux_v1.DatasetCheckError(f"{path} sha256 {got} != frozen {FROZEN_COMPUTE_SHA256}")
    return got


def case_meta(case):
    return {"meta_case_id": case.case_id, "meta_run_id": case.run_id, "meta_pair_id": case.pair_id,
            "meta_kind": case.kind, "meta_fault": case.fault, "meta_target_kind": case.target_kind,
            "meta_root_cause": case.root_cause, "meta_repetition": case.repetition, "meta_fold": case.repetition,
            "meta_dataset": linux_v1.DATASET}


def build_case(case, with_logs=True, verify_hashes=True):
    """(ranking, ranking_nodeview, detection, detection_ineligible, edges, info) for one run."""
    if verify_hashes:
        for name, want in case.view_hashes.items():
            got = file_sha256(case.path / case.view / name)
            if got != want:
                raise linux_v1.DatasetCheckError(f"{case.run_id}/{case.view}/{name}: sha256 {got} != pipeline {want}")
    metrics = linux_v1.load_metrics(case)
    spans = linux_v1.load_spans(case)
    logs = linux_v1.load_logs(case, keep_text=False) if with_logs else pd.DataFrame(columns=["t", "service", "err"])
    t_min, t_max = metrics["t"].min(), metrics["t"].max()
    windows = make_windows(case.onset, t_min, t_max + 1)
    windows["label"] = windows["rel"].map(lambda r: label_linux_v1(r, case))
    base_mask = (windows["label"] == "baseline_stats").to_numpy()
    feats, edge_keys, edge_arr = compute.node_features(
        windows, compute.metric_stats(metrics, windows), *compute.span_stats(spans, windows),
        compute.log_stats(logs, windows), base_mask)
    feats = feats.merge(windows[["rel", "label"]].rename(columns={"rel": "meta_rel", "label": "meta_label"}),
                        left_on="meta_window", right_index=True)
    meta = case_meta(case)
    for k, v in meta.items():
        feats[k] = v

    is_fault = case.kind == "fault"
    ranking = feats.iloc[0:0].assign(**{schema.TARGET_COLUMN: np.int8(0)})
    ranking_nodeview = ranking
    if is_fault and case.eligible:
        rows_fa = feats[feats["meta_label"] == "fault_active"].copy()
        rows_fa[schema.TARGET_COLUMN] = (rows_fa["meta_candidate"] == case.root_cause).astype(np.int8)
        if case.fault in RANKING_FAULTS:
            ranking = rows_fa
        else:
            ranking_nodeview = rows_fa

    det_cols = [c for c in feats.columns if c.startswith(DETECTION_SOURCES) and not c.endswith(DETECTION_SKIP_SUFFIX)]
    rows = feats[feats["meta_label"].isin(NEGATIVE_LABELS + ("fault_active",))]
    with np.errstate(all="ignore"):
        agg = rows.groupby("meta_window")[det_cols].agg(["max", "mean"])
    agg.columns = [f"{c}__{s}" for c, s in agg.columns]
    lab = rows.groupby("meta_window")[["meta_rel", "meta_label"]].first()
    det = agg.join(lab).reset_index()
    for k, v in meta.items():
        det[k] = v
    active = det["meta_label"] == "fault_active"
    if not is_fault and active.any():
        raise linux_v1.DatasetCheckError(f"{case.run_id}: control run has fault_active windows")
    det[schema.TARGET_COLUMN] = active.astype(np.int8)
    det["meta_eligible"] = ~active | bool(case.eligible)
    det["meta_detection_role"] = np.where(~active, "negative", np.where(case.eligible, "positive", "ineligible"))
    detection = det[det["meta_eligible"]].reset_index(drop=True)
    detection_ineligible = det[~det["meta_eligible"]].reset_index(drop=True)

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
        for k, v in meta.items():
            edges[k] = v

    counts = windows["label"].value_counts().to_dict()
    gaps = linux_v1.tolerated_gaps(case)
    info = {"case_id": case.case_id, "run_id": case.run_id, "pair_id": case.pair_id, "kind": case.kind,
            "fault": case.fault, "target_kind": case.target_kind, "root_cause": case.root_cause,
            "edge_src": case.edge_src, "edge_dst": case.edge_dst, "repetition": case.repetition,
            "fold": case.repetition, "dataset": linux_v1.DATASET, "root": case.root_name,
            "environment_id": case.environment_id, "attempt": case.attempt, "schedule_index": case.schedule_index,
            "view": case.view, "run_start": case.run_start, "onset": case.onset, "onset_source": case.onset_source,
            "started_at": case.started_at, "injection": case.injection, "removal": case.removal,
            "recovery": case.recovery, "data_valid": case.data_valid, "injection_valid": case.injection_valid,
            "impact_confirmed": case.impact_confirmed, "eligible": case.eligible, "status": case.status,
            "seconds_after_onset": float(t_max - case.onset), "n_spans": int(len(spans)), "n_logs": int(len(logs)),
            "tolerated_gap_points": int(sum(len(v) for g in gaps.values() for v in g.values())),
            **{f"windows_{k}": int(v) for k, v in counts.items()},
            "root_cause_has_metrics": bool(metrics["service"].eq(case.root_cause).any()),
            "root_cause_traced": bool(spans["service"].eq(case.root_cause).any()),
            "rows_ranking": int(len(ranking)), "rows_ranking_nodeview": int(len(ranking_nodeview)),
            "rows_detection": int(len(detection)),
            "rows_detection_ineligible": int(len(detection_ineligible)), "rows_edges": int(len(edges))}
    return ranking, ranking_nodeview, detection, detection_ineligible, edges, info


def _work(args):
    """Worker: build one case and write its parts; info.json is written last (completion marker)."""
    case, part_dir, with_logs, verify = args
    t0 = time.time()
    part_dir = Path(part_dir)
    tmp = part_dir.with_name(part_dir.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    *tables, info = build_case(case, with_logs, verify)
    for name, df in zip(PART_FILES, tables):
        df.to_parquet(tmp / f"{name}.parquet", index=False)
    info["build_s"] = round(time.time() - t0, 1)
    info["worker_maxrss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    (tmp / "info.json").write_text(json.dumps(info, indent=1, default=str), encoding="utf-8")
    shutil.rmtree(part_dir, ignore_errors=True)
    tmp.rename(part_dir)
    return info


def _log(out, msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    if out is not None:
        with open(Path(out) / "build-progress.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_checks(roots_path, schedule_path, expected_pairs=linux_v1.EXPECTED_PAIRS, compute_path=None):
    roots = linux_v1.load_roots(roots_path)
    adopted, excluded = linux_v1.resolve_pairs(roots, linux_v1.read_schedule(schedule_path), expected_pairs)
    compute_sha = check_compute_hash(compute_path)
    return roots, adopted, excluded, compute_sha


def assemble(out, cases, roots, adopted, excluded, compute_sha, args, started):
    parts = Path(out) / "_parts"
    infos = [json.loads((parts / c.case_id / "info.json").read_text(encoding="utf-8")) for c in cases]

    def cat(name):
        frames = [pd.read_parquet(parts / c.case_id / f"{name}.parquet") for c in cases]
        frames = [f for f in frames if len(f)]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    tables = {name: cat(name) for name in PART_FILES}
    infos = pd.DataFrame(infos)
    for name, fname in OUTPUT_NAMES.items():
        tables[name].to_parquet(out / fname, index=False)
    infos.to_parquet(out / "cases.parquet", index=False)
    folds = {str(k): sorted(infos.loc[infos["fold"] == k, "case_id"]) for k in sorted(infos["fold"].unique())}
    for pid, g in infos.groupby("pair_id"):
        if g["fold"].nunique() != 1:
            raise linux_v1.DatasetCheckError(f"pair {pid} spans folds {sorted(g['fold'].unique())}")
    (out / "folds.json").write_text(json.dumps(folds, indent=2), encoding="utf-8")

    ranking, detection = tables["ranking"], tables["detection"]
    fcols = [c for c in ranking.columns if c.startswith(schema.FEATURE_PREFIX)]
    dcols = [c for c in detection.columns if c.startswith(schema.FEATURE_PREFIX)]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "features"], capture_output=True, text=True,
                                cwd=REPO).stdout.strip())
    faults = infos[infos["kind"] == "fault"]
    summary = {
        "dataset": linux_v1.DATASET, "feature_version": schema.FEATURE_VERSION, "code_commit": commit,
        "features_dir_dirty": dirty,
        "code_sha256": {"features/compute.py": compute_sha,
                        "features/windows.py": file_sha256(REPO / "features" / "windows.py"),
                        "features/schema.py": file_sha256(REPO / "features" / "schema.py"),
                        "features/adapters/linux_v1.py": file_sha256(REPO / "features" / "adapters" / "linux_v1.py")},
        "roots": [{"name": r.name, "environment_id": r.environment_id, "path": str(r.path),
                   "adopted_pairs": sum(a["root"] is r for a in adopted)} for r in roots],
        "schedule": str(args.schedule), "schedule_sha256": file_sha256(args.schedule),
        "checks": {"run_id_collision": "none", "one_adopted_attempt_per_pair": True,
                   "adopted_pairs_equal_schedule": len(adopted), "compute_sha256_frozen": True},
        "excluded_attempts": excluded,
        "translation": {
            "decisions": "docs/LINUX-V1-DATA-TRANSLATION.md",
            "cpu_cores": "stored rate(container_cpu_usage_seconds_total[60s]) (no raw counter exported)",
            "network": "pod-level dropped-packet series (container label empty/POD), exception to POD exclusion",
            "not_collected_signals_nan": list(linux_v1.NOT_COLLECTED_SIGNALS),
            "tolerated_missing_points": "NaN on affected grid points, no forward fill",
            "pod_onset": "first kube_container_ready = 0 of the target service in [started_at, ended_at]",
            "control_times": "control run_start + (fault time - fault run_start)",
        },
        "params": {"window_s": schema.WINDOW_SECONDS, "stride_s": schema.STRIDE_SECONDS,
                   "resample_s": schema.RESAMPLE_SECONDS, "min_spans": schema.MIN_SPANS,
                   "with_logs": not args.no_logs, "verify_input_hashes": not args.no_verify, "workers": args.workers,
                   "limit": args.limit},
        "cases": int(len(infos)), "fault_runs": int(len(faults)), "control_runs": int((infos["kind"] == "control").sum()),
        "eligible_fault_runs": int(faults["eligible"].sum()),
        "onset_source": infos["onset_source"].value_counts().to_dict(),
        "pod_onset_fallback_runs": sorted(faults.loc[faults["onset_source"] == "fallback_started_at", "run_id"]),
        "tolerated_gap_points": int(infos["tolerated_gap_points"].sum()),
        "folds": {k: len(v) for k, v in folds.items()},
        "ranking": {"rows": int(len(ranking)), "feature_columns": len(fcols),
                    "positives": int(ranking[schema.TARGET_COLUMN].sum()) if len(ranking) else 0},
        "detection": {"rows": int(len(detection)), "feature_columns": len(dcols),
                      "positives": int(detection[schema.TARGET_COLUMN].sum()) if len(detection) else 0,
                      "by_label": detection["meta_label"].value_counts().to_dict() if len(detection) else {}},
        "ranking_nodeview_rows": int(len(tables["ranking_nodeview"])),
        "detection_ineligible_rows": int(len(tables["detection_ineligible"])),
        "edges_rows": int(len(tables["edges"])),
        "missing_ratio_ranking": {c: round(float(ranking[c].isna().mean()), 4) for c in fcols} if len(ranking) else {},
        "max_worker_rss_mb": int(infos["worker_maxrss_mb"].max()),
        "elapsed_s": round(time.time() - started, 1),
    }
    (out / "build-summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", default=str(REPO / "campaigns" / "linux-v1" / "dataset-roots.yaml"))
    ap.add_argument("--schedule", default=str(REPO / "campaigns" / "linux-v1" / "schedule.csv"))
    ap.add_argument("--out", default=f"data/features/linux-v1-{schema.FEATURE_VERSION}")
    ap.add_argument("--workers", type=int, default=2, help="default 2 (host memory-pressure history)")
    ap.add_argument("--limit", type=int, help="only the first N cases (smoke test)")
    ap.add_argument("--resume", action="store_true", help="continue a stopped build in --out")
    ap.add_argument("--check-only", action="store_true", help="run checks 1-4 and list cases; write nothing")
    ap.add_argument("--no-logs", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="skip sha256 check of input parquet files")
    ap.add_argument("--expected-pairs", type=int, default=linux_v1.EXPECTED_PAIRS)
    args = ap.parse_args(argv)
    started = time.time()
    roots, adopted, excluded, compute_sha = run_checks(args.roots, args.schedule, args.expected_pairs)
    if args.check_only:
        cases = [c for p in adopted for c in linux_v1.pair_cases(p, resolve_pod_onset=False)]
        print(json.dumps({"checks": "pass", "adopted_pairs": len(adopted), "cases": len(cases),
                          "by_root": {r.name: sum(a["root"] is r for a in adopted) for r in roots},
                          "eligible_fault_runs": sum(c.eligible for c in cases if c.kind == "fault"),
                          "excluded_attempts": [(e["fault_run_id"], e["run_folders"]) for e in excluded],
                          "compute_sha256": compute_sha}, indent=2))
        return None
    out = Path(args.out)
    if (out / "build-summary.json").exists():
        raise SystemExit(f"{out} already holds a finished build; use a new --out (outputs are never overwritten)")
    if out.exists() and any(out.iterdir()) and not args.resume:
        raise SystemExit(f"{out} is not empty; use --resume to continue it or a new --out")
    (out / "_parts").mkdir(parents=True, exist_ok=True)
    _log(out, f"checks pass: {len(adopted)} pairs, {len(excluded)} excluded attempts, compute.py {compute_sha[:12]}")
    cases = [c for p in adopted for c in linux_v1.pair_cases(p)][: args.limit]
    todo = [c for c in cases if not (out / "_parts" / c.case_id / "info.json").exists()]
    _log(out, f"{len(cases)} cases, {len(cases) - len(todo)} already done, {len(todo)} to build, workers {args.workers}")
    done = len(cases) - len(todo)
    jobs = [(c, str(out / "_parts" / c.case_id), not args.no_logs, not args.no_verify) for c in todo]
    if jobs:
        with ProcessPoolExecutor(max_workers=args.workers, max_tasks_per_child=1) as ex:
            futures = {ex.submit(_work, j): j[0].case_id for j in jobs}
            for fut in as_completed(futures):
                info = fut.result()      # an error stops the build; finished parts stay for --resume
                done += 1
                _log(out, f"[{done}/{len(cases)}] {info['case_id']} {info['build_s']}s rss {info['worker_maxrss_mb']}MB "
                          f"elapsed {time.time() - started:.0f}s")
    summary = assemble(out, cases, roots, adopted, excluded, compute_sha, args, started)
    _log(out, f"done: {summary['cases']} cases, ranking {summary['ranking']['rows']} rows, "
              f"detection {summary['detection']['rows']} rows, {summary['elapsed_s']}s")
    return summary


if __name__ == "__main__":
    main()
