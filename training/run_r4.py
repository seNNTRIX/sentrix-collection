"""R4 experiments on RE2-OB (pre-registered in experiments/<id>/config.yaml).

  python -m training.run_r4 --out experiments/20261027-re2ob-r4 [--w60 data/features/re2ob-v0-w60]

Rules fixed before running:
- outer split: repetition 3-fold; hyperparameters chosen by inner CV inside the two
  training repetitions only (train on one, validate on the other), max mean Avg@5,
  ties -> smaller model. Test folds are never used for selection.
- case aggregation and metrics: evaluation/ (R3, unchanged).
- an added bundle counts as better than `core` only if the paired case-bootstrap 95% CI
  of the Avg@5 difference excludes 0; otherwise "no difference" and the simpler set wins.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from evaluation.run_baselines import COMMON_FAULTS, COMMON_SERVICES, TRACED, add_scores
from features.schema import CANDIDATES
from training import lgbm

BUNDLES = {
    "metric": ("f_cm_",),
    "core": ("f_cm_", "f_ct_"),
    "core+opt": ("f_cm_", "f_ct_", "f_opt_"),
    "core+log": ("f_cm_", "f_ct_", "f_log_"),
    "core+nbr": ("f_cm_", "f_ct_", "f_nbr_"),
    "all": ("f_cm_", "f_ct_", "f_opt_", "f_log_", "f_nbr_"),
}


def cols_for(df, prefixes, drop=()):
    return [c for c in df.columns if c.startswith(prefixes) and c not in drop]


def per_case_avg5(rows):
    return {cid: M.per_case_scores([(s, i)])[0] for cid, s, i, _ in rows}


def summarize(rows, n_boot=2000):
    cases = [(s, i) for _, s, i, _ in rows]
    out = M.ranking_summary(cases)
    per = M.per_case_scores(cases)
    for m in ("AC@1", "AC@3", "Avg@5"):
        out[f"{m}_ci95"] = M.bootstrap_ci(per, m, n_boot=n_boot, seed=0)
    folds = {}
    for f in sorted({meta["fold"] for *_, meta in rows}):
        folds[f] = M.ranking_summary([(s, i) for _, s, i, meta in rows if meta["fold"] == f])["Avg@5"]
    out["Avg@5_fold_mean"], out["Avg@5_fold_std"] = float(np.mean(list(folds.values()))), float(np.std(list(folds.values())))
    out["by_fault"] = {f: round(M.ranking_summary([(s, i) for _, s, i, meta in rows if meta["fault"] == f])["Avg@5"], 3)
                       for f in sorted({meta["fault"] for *_, meta in rows})}
    common = [(s, i) for _, s, i, meta in rows if meta["fault"] in COMMON_FAULTS]
    common4 = [(s, i) for _, s, i, meta in rows if meta["fault"] in COMMON_FAULTS and meta["root_cause"] in COMMON_SERVICES]
    out["common_faults_Avg@5"] = M.ranking_summary(common)["Avg@5"]
    out["common_faults_services_Avg@5"] = M.ranking_summary(common4)["Avg@5"]
    return out


def paired_diff(a_rows, b_rows, metric="Avg@5", n_boot=2000, seed=0):
    a, b = per_case_avg5(a_rows), per_case_avg5(b_rows)
    ids = sorted(set(a) & set(b))
    d = np.array([a[c][metric] - b[c][metric] for c in ids])
    rng = np.random.default_rng(seed)
    boots = d[rng.integers(0, len(d), size=(n_boot, len(d)))].mean(axis=1)
    lo, hi = float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))
    return {"mean_diff": float(d.mean()), "ci95": (lo, hi), "n": len(ids),
            "verdict": "better" if lo > 0 else ("worse" if hi < 0 else "no difference")}


def mode_params(chosen):
    c = Counter(json.dumps(v["params"], sort_keys=True) for v in chosen.values())
    return json.loads(c.most_common(1)[0][0])


def fmt(x):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--w60", help="feature build with 60 s windows (optional)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    R = pd.read_parquet(Path(args.features) / "ranking.parquet")
    D = pd.read_parquet(Path(args.features) / "detection.parquet")
    res = {"ranking": {}, "chosen_params": {}, "paired": {}}

    def checkpoint():
        (out / "results.partial.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")

    base = add_scores(R)
    stat_rows = list(case_rankings(base, "s_stat_combined"))
    res["ranking"]["baseline stat_combined"] = summarize(stat_rows)

    oof = {}
    for name, prefixes in BUNDLES.items():
        cols = cols_for(R, prefixes)
        rows, chosen, models, scored = lgbm.cv_ranker(R, cols)
        oof[name] = (rows, chosen, models, scored, cols)
        res["ranking"][f"lgbm {name}"] = summarize(rows) | {"n_features": len(cols)}
        res["chosen_params"][name] = chosen
        print(name, round(res["ranking"][f"lgbm {name}"]["Avg@5"], 3), flush=True)
        checkpoint()

    core_rows = oof["core"][0]
    for name in BUNDLES:
        if name != "core":
            res["paired"][f"{name} - core"] = paired_diff(oof[name][0], core_rows)
    res["paired"]["core - stat_combined"] = paired_diff(core_rows, stat_rows)

    # sensitivity: no trace mask; traced candidates only (same out-of-fold scores)
    cols_nomask = cols_for(R, BUNDLES["core"], drop=("f_ct_mask",))
    rows_nomask, ch, _, _ = lgbm.cv_ranker(R, cols_nomask)
    res["ranking"]["lgbm core - f_ct_mask"] = summarize(rows_nomask)
    res["chosen_params"]["core-no-mask"] = ch
    res["paired"]["core-no-mask - core"] = paired_diff(rows_nomask, core_rows)
    traced_rows = list(case_rankings(oof["core"][3], "s_model", TRACED))
    res["ranking"]["lgbm core (traced candidates only)"] = summarize(traced_rows)
    res["ranking"]["baseline stat_combined (traced candidates only)"] = summarize(
        list(case_rankings(base, "s_stat_combined", TRACED)))

    # window length
    if args.w60:
        R60 = pd.read_parquet(Path(args.w60) / "ranking.parquet")
        rows60, ch60, _, _ = lgbm.cv_ranker(R60, cols_for(R60, BUNDLES["core"]))
        res["ranking"]["lgbm core (60 s windows)"] = summarize(rows60)
        res["chosen_params"]["core-w60"] = ch60
        res["paired"]["core w60 - core w30"] = paired_diff(rows60, core_rows)

    # leave-one-service-out (unseen root-cause service), fixed params = mode of core outer choices
    params = mode_params(oof["core"][1])
    res["loso_params"] = params
    cols = oof["core"][4]
    loso = {}
    for svc in sorted(R["meta_root_cause"].unique()):
        model = lgbm.fit_ranker(R[R["meta_root_cause"] != svc], cols, params)
        rows, _ = lgbm.score_cases(model, R[R["meta_root_cause"] == svc], cols)
        stat = [x for x in stat_rows if x[3]["root_cause"] == svc]
        loso[svc] = {"lgbm": M.ranking_summary([(s, i) for _, s, i, _ in rows]),
                     "stat_combined": M.ranking_summary([(s, i) for _, s, i, _ in stat])}
    res["loso"] = loso
    checkpoint()

    # joint classification baseline (service x fault classes, identity by column position)
    jrows, jfault = lgbm.cv_joint(R, oof["core"][4])
    res["ranking"]["joint classification (core)"] = summarize(jrows)
    from sklearn.metrics import accuracy_score, f1_score
    y, p = zip(*jfault)
    res["joint_fault_type"] = {"accuracy": accuracy_score(y, p), "macro_f1": f1_score(y, p, average="macro")}

    # detection
    det = {}
    for name, prefixes in {"core": ("f_cm_", "f_ct_"), "all": ("f_cm_", "f_ct_", "f_log_", "f_nbr_")}.items():
        dcols = [c for c in D.columns if c.startswith(prefixes)]
        scored, ch = lgbm.cv_detector(D, dcols)
        s = M.detection_summary(scored["target"], scored["s_model"].to_numpy())
        rng = np.random.default_rng(0)
        ids = scored["meta_case_id"].unique()
        groups = {c: np.flatnonzero(scored["meta_case_id"].to_numpy() == c) for c in ids}
        boots = []
        for _ in range(300):
            idx = np.concatenate([groups[c] for c in rng.choice(ids, len(ids))])
            boots.append(M.detection_summary(scored["target"].to_numpy()[idx], scored["s_model"].to_numpy()[idx])["AUROC"])
        s["AUROC_ci95"] = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
        det[name] = s | {"chosen": ch, "n_features": len(dcols)}
    res["detection"] = det

    # importance (core, fixed params, all 90 cases) and error analysis (core out-of-fold)
    final = lgbm.fit_ranker(R, cols, params)
    imp = pd.Series(final.booster_.feature_importance("gain"), index=cols).sort_values(ascending=False)
    res["importance_core_top15"] = {k: float(v) for k, v in imp.head(15).items()}
    errors = []
    for cid, s, i, meta in core_rows:
        if M.case_hit_at(s, i, 1) < 1:
            order = np.argsort(-np.where(np.isnan(s), -np.inf, s))
            errors.append({"case_id": cid, "fault": meta["fault"], "root_cause": meta["root_cause"],
                           "predicted_top3": [CANDIDATES[j] for j in order[:3]],
                           "true_rank_expected": 1 / M.case_reciprocal_rank(s, i)})
    res["errors_core"] = errors

    (out / "results.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    L = ["# R4 results (RE2-OB)", "", "## Root-cause ranking (11 candidates, 90 cases, out-of-fold)", "",
         "| method | features | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | fold mean ± std | common faults | common faults+services |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, s in res["ranking"].items():
        ci = s["Avg@5_ci95"]
        L.append(f"| {name} | {s.get('n_features', '-')} | {fmt(s['AC@1'])} | {fmt(s['AC@3'])} | {fmt(s['Avg@5'])} "
                 f"({fmt(ci[0])}–{fmt(ci[1])}) | {fmt(s['MRR'])} | {fmt(s['Avg@5_fold_mean'])} ± {fmt(s['Avg@5_fold_std'])} "
                 f"| {fmt(s['common_faults_Avg@5'])} | {fmt(s['common_faults_services_Avg@5'])} |")
    L += ["", "## Paired comparisons (Avg@5 difference, case bootstrap 95% CI)", "", "| comparison | mean diff | 95% CI | verdict |", "|---|---|---|---|"]
    for k, v in res["paired"].items():
        L.append(f"| {k} | {fmt(v['mean_diff'])} | {fmt(v['ci95'][0])} – {fmt(v['ci95'][1])} | {v['verdict']} |")
    faults = sorted(res["ranking"]["lgbm core"]["by_fault"])
    L += ["", "## Avg@5 by fault", "", "| method | " + " | ".join(faults) + " |", "|---|" + "---|" * len(faults)]
    for name, s in res["ranking"].items():
        if "traced" in name:
            continue
        L.append(f"| {name} | " + " | ".join(fmt(s["by_fault"].get(f)) for f in faults) + " |")
    L += ["", f"## Leave-one-service-out (params {params})", "", "| held-out root cause | n | lgbm AC@1 | lgbm Avg@5 | stat_combined Avg@5 |", "|---|---|---|---|---|"]
    for svc, v in loso.items():
        L.append(f"| {svc} | {v['lgbm']['n_cases']} | {fmt(v['lgbm']['AC@1'])} | {fmt(v['lgbm']['Avg@5'])} | {fmt(v['stat_combined']['Avg@5'])} |")
    L += ["", "## Joint classification fault type", "", f"accuracy {fmt(res['joint_fault_type']['accuracy'])}, macro-F1 {fmt(res['joint_fault_type']['macro_f1'])}",
          "", "## Detection (window level, out-of-fold)", "", "| model | features | AUROC (95% CI) | AUPRC |", "|---|---|---|---|"]
    for name, s in det.items():
        L.append(f"| lgbm {name} | {s['n_features']} | {fmt(s['AUROC'])} ({fmt(s['AUROC_ci95'][0])}–{fmt(s['AUROC_ci95'][1])}) | {fmt(s['AUPRC'])} |")
    L += ["", "## Feature importance (core, gain, top 15)", ""] + [f"- {k}: {v:.0f}" for k, v in res["importance_core_top15"].items()]
    L += ["", f"## Errors (core, AC@1 < 1): {len(errors)} cases", "", "| case | fault | true | predicted top 3 |", "|---|---|---|---|"]
    for e in errors:
        L.append(f"| {e['case_id']} | {e['fault']} | {e['root_cause']} | {', '.join(e['predicted_top3'])} |")
    (out / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
