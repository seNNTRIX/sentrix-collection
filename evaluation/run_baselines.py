"""R3 baselines on a feature build (RE2-OB feature v0).

  python -m evaluation.run_baselines --features data/features/re2ob-v0 --out experiments/<id>

Ranking baselines (all defined before looking at any result):
  random       every candidate gets the same score -> expected tie rank = random order
  freq_prior   score = how often the candidate was the root cause in the TRAINING folds
  stat_metric  window score = max over the 6 metric signals of |f_cm_<signal>_dmean|
               (robust z vs the case's own baseline; BARO-style, our features)
  stat_trace   window score = max(|f_ct_in_p90_lr|, |f_ct_in_edge_p90_lr|)
  stat_combined window score = max of the two scores above after converting each to
               its rank among candidates in the same window (no scale mixing)
Detection baselines (window level): max over candidates of the metric / trace scores.
Case-level aggregation: evaluation/aggregate.py (mean over windows 60-300 s after injection).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from features.schema import CANDIDATES, METRIC_SIGNALS

TRACED = ("checkoutservice", "currencyservice", "emailservice", "frontend", "paymentservice",
          "productcatalogservice", "recommendationservice")
COMMON_FAULTS = ("cpu", "delay", "loss")
COMMON_SERVICES = ("checkoutservice", "currencyservice", "productcatalogservice", "recommendationservice")


def add_scores(r):
    r = r.copy()
    r["s_random"] = 0.0
    r["s_stat_metric"] = r[[f"f_cm_{s}_dmean" for s in METRIC_SIGNALS]].abs().max(axis=1, skipna=True)
    r["s_stat_trace"] = r[["f_ct_in_p90_lr", "f_ct_in_edge_p90_lr"]].abs().max(axis=1, skipna=True)
    keys = ["meta_case_id", "meta_window"]
    rm = r.groupby(keys)["s_stat_metric"].rank(pct=True)
    rt = r.groupby(keys)["s_stat_trace"].rank(pct=True)
    r["s_stat_combined"] = pd.concat([rm, rt], axis=1).max(axis=1, skipna=True)
    return r


def freq_prior_scores(r):
    """Out-of-fold: for each test fold, frequency of root causes in the other folds."""
    out = pd.Series(np.nan, index=r.index)
    roots = r.groupby("meta_case_id")[["meta_root_cause", "meta_fold"]].first()
    for fold in sorted(r["meta_fold"].unique()):
        train = roots[roots["meta_fold"] != fold]["meta_root_cause"].value_counts(normalize=True)
        idx = r["meta_fold"] == fold
        out[idx] = r.loc[idx, "meta_candidate"].map(train).fillna(0.0)
    return out


def evaluate(r, score, candidates, subset=None):
    rows = list(case_rankings(r, score, candidates))
    if subset:
        rows = [x for x in rows if subset(x[3])]
    cases = [(s, i) for _, s, i, _ in rows]
    summary = M.ranking_summary(cases)
    per = M.per_case_scores(cases)
    for m in ("AC@1", "AC@3", "Avg@5"):
        summary[f"{m}_ci95"] = M.bootstrap_ci(per, m, seed=0)
    folds = {}
    for f in sorted({x[3]["fold"] for x in rows}):
        fc = [(s, i) for _, s, i, meta in rows if meta["fold"] == f]
        folds[f] = M.ranking_summary(fc)["Avg@5"]
    summary["Avg@5_fold_mean"] = float(np.mean(list(folds.values())))
    summary["Avg@5_fold_std"] = float(np.std(list(folds.values())))
    by_fault = {}
    for fault in sorted({x[3]["fault"] for x in rows}):
        fc = [(s, i) for _, s, i, meta in rows if meta["fault"] == fault]
        by_fault[fault] = {k: round(v, 3) for k, v in M.ranking_summary(fc).items() if k != "n_cases"}
    summary["by_fault"] = by_fault
    return summary


def detection_eval(det):
    out = {}
    metric_cols = [f"f_cm_{s}_dmean__max" for s in METRIC_SIGNALS]
    scores = {
        "stat_metric": det[metric_cols].max(axis=1, skipna=True),
        "stat_trace": det[["f_ct_in_p90_lr__max", "f_ct_in_edge_p90_lr__max"]].max(axis=1, skipna=True),
    }
    rng = np.random.default_rng(0)
    case_ids = det["meta_case_id"].unique()
    for name, s in scores.items():
        res = M.detection_summary(det["target"], s.to_numpy())
        boots = []
        groups = {c: np.flatnonzero(det["meta_case_id"].to_numpy() == c) for c in case_ids}
        for _ in range(300):
            pick = rng.choice(case_ids, size=len(case_ids), replace=True)
            idx = np.concatenate([groups[c] for c in pick])
            boots.append(M.detection_summary(det["target"].to_numpy()[idx], s.to_numpy()[idx])["AUROC"])
        res["AUROC_ci95"] = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
        out[name] = res
    return out


def fmt(x):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    feat = Path(args.features)
    r = add_scores(pd.read_parquet(feat / "ranking.parquet"))
    r["s_freq_prior"] = freq_prior_scores(r)
    det = pd.read_parquet(feat / "detection.parquet")

    methods = ["random", "freq_prior", "stat_metric", "stat_trace", "stat_combined"]
    views = {
        "all_cases_all_candidates": (CANDIDATES, None),
        "all_cases_traced_candidates": (TRACED, None),
        "common_faults": (CANDIDATES, lambda m: m["fault"] in COMMON_FAULTS),
        "common_faults_common_services": (CANDIDATES, lambda m: m["fault"] in COMMON_FAULTS
                                          and m["root_cause"] in COMMON_SERVICES),
    }
    results = {"ranking": {v: {} for v in views}, "detection": detection_eval(det)}
    for v, (cands, subset) in views.items():
        for m in methods:
            results["ranking"][v][m] = evaluate(r, f"s_{m}", cands, subset)
    summary = json.loads((feat / "build-summary.json").read_text())
    results["inputs"] = {"features": str(feat), "feature_code_commit": summary.get("code_commit"),
                         "cases": summary.get("cases")}

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")
    lines = ["# R3 baselines (RE2-OB feature v0)", ""]
    for v in views:
        lines += [f"## {v}", "", "| method | n | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | Avg@5 fold mean ± std |",
                  "|---|---|---|---|---|---|---|"]
        for m in methods:
            s = results["ranking"][v][m]
            ci = s["Avg@5_ci95"]
            lines.append(f"| {m} | {s['n_cases']} | {fmt(s['AC@1'])} | {fmt(s['AC@3'])} | {fmt(s['Avg@5'])} "
                         f"({fmt(ci[0])}–{fmt(ci[1])}) | {fmt(s['MRR'])} | {fmt(s['Avg@5_fold_mean'])} ± {fmt(s['Avg@5_fold_std'])} |")
        lines.append("")
    v = "all_cases_all_candidates"
    faults = sorted(results["ranking"][v]["stat_metric"]["by_fault"])
    lines += ["## Avg@5 by fault (all cases, all candidates)", "",
              "| method | " + " | ".join(faults) + " |", "|---|" + "---|" * len(faults)]
    for m in methods:
        bf = results["ranking"][v][m]["by_fault"]
        lines.append(f"| {m} | " + " | ".join(fmt(bf[f]["Avg@5"]) for f in faults) + " |")
    lines += ["", "## Detection (window level, normal vs fault_active)", "",
              "| method | AUROC (95% CI, case bootstrap) | AUPRC | positive rate |", "|---|---|---|---|"]
    for name, d in results["detection"].items():
        lines.append(f"| {name} | {fmt(d['AUROC'])} ({fmt(d['AUROC_ci95'][0])}–{fmt(d['AUROC_ci95'][1])}) | "
                     f"{fmt(d['AUPRC'])} | {fmt(d['positive_rate'])} |")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'results.md'} and {out / 'results.json'}")


if __name__ == "__main__":
    main()
