"""R6: model family x feature set comparison (pre-registered in experiments/20261027-re2ob-r6-models/config.yaml).

  .venv-r6/Scripts/python -m training.run_r6 --out experiments/20261027-re2ob-r6-models --model lgbm
  .venv-r6/Scripts/python -m training.run_r6 --out experiments/20261027-re2ob-r6-models --combine

One process per model writes parts/<model>.json (out-of-fold case rows, chosen params, timing);
--combine adds stat_combined / stat_metric and the hybrids, applies the decision rules in config.yaml
mechanically and writes results.json and results.md.
"""
import argparse
import json
import time
import warnings
from pathlib import Path

import catboost as cb
import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from evaluation.run_baselines import METRIC_SIGNALS, add_scores
from training import lgbm
from training.freeze_r5 import rel_detection_cols
from training.run_r4 import cols_for, fmt, paired_diff, summarize
from training.run_r4b import CORE, hybrid, rel_cols

# scikit-learn 1.5.2 passes `iprint` to scipy 1.18 lbfgs; the option is ignored and results are unaffected.
warnings.filterwarnings("ignore", message="Unknown solver options: iprint")

SEED = 0
MODELS = ["logreg", "rf", "lgbm", "xgb", "catboost"]          # simplest first (decision order)
FSETS = ["rel", "core", "all"]
RANK_GRIDS = {
    "logreg": [{"C": c} for c in (0.01, 0.1, 1, 10)],
    "rf": [{"min_samples_leaf": l, "max_features": f} for l in (100, 20) for f in ("sqrt", 0.5)],
    "lgbm": [{"num_leaves": l, "n_estimators": n} for l in (7, 15) for n in (100, 300)],
    "xgb": [{"max_depth": d, "n_estimators": n} for d in (3, 4) for n in (100, 300)],
    "catboost": [{"depth": d, "iterations": n} for d in (4, 6) for n in (100, 300)],
}
DET_GRIDS = dict(RANK_GRIDS,
                 lgbm=[{"num_leaves": l, "n_estimators": n} for l in (15, 31) for n in (100, 300)],
                 xgb=[{"max_depth": d, "n_estimators": n} for d in (4, 6) for n in (100, 300)])
GBDT = {"learning_rate": 0.05}


# ---------------------------------------------------------------- feature sets
def rank_fsets(R):
    return {"rel": rel_cols(R), "core": cols_for(R, CORE), "all": cols_for(R, ("f_",))}


def det_fsets(D, R):
    f = rank_fsets(R)
    allc = [c for c in D.columns if c.startswith("f_")]
    return {"rel": rel_detection_cols(D, f["rel"]),
            "core": [c for c in allc if c.rsplit("__", 1)[0] in f["core"]], "all": allc}


# ---------------------------------------------------------------- model wrappers
class Scorer:
    """Uniform predict(X DataFrame) -> score array (higher = more likely root cause / fault)."""
    def __init__(self, fn):
        self.predict = fn


def dense(X):
    return np.nan_to_num(X.to_numpy(dtype=float), nan=0.0)


def sorted_groups(df):
    d = df.sort_values(["meta_case_id", "meta_window", "meta_candidate"])
    return d, d.groupby(["meta_case_id", "meta_window"], sort=False).ngroup().to_numpy()


def fit_linear(X, y, p):
    sc = StandardScaler().fit(dense(X))
    clf = LogisticRegression(C=p["C"], max_iter=5000).fit(sc.transform(dense(X)), y)
    return Scorer(lambda Z: clf.decision_function(sc.transform(dense(Z))))


def fit_forest(X, y, p):
    clf = RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=4, **p).fit(dense(X), y)
    return Scorer(lambda Z: clf.predict_proba(dense(Z))[:, 1])


def fit_rank(model, df, cols, p):
    if model == "logreg":
        return fit_linear(df[cols], df["target"], p)
    if model == "rf":
        return fit_forest(df[cols], df["target"], p)
    if model == "lgbm":
        return lgbm.fit_ranker(df, cols, {**p, "min_child_samples": 100})
    d, qid = sorted_groups(df)
    if model == "xgb":
        m = xgb.XGBRanker(objective="rank:ndcg", tree_method="hist", random_state=SEED, n_jobs=4, **GBDT, **p)
        m.fit(d[cols], d["target"], qid=qid)
        return Scorer(m.predict)
    if model == "catboost":
        m = cb.CatBoostRanker(loss_function="YetiRank", random_seed=SEED, thread_count=4, verbose=0,
                              allow_writing_files=False, **GBDT, **p)
        m.fit(cb.Pool(d[cols], d["target"], group_id=qid))
        return Scorer(m.predict)
    raise ValueError(model)


def fit_det(model, df, cols, p):
    X, y = df[cols], df["target"]
    if model == "logreg":
        return fit_linear(X, y, p)
    if model == "rf":
        return fit_forest(X, y, p)
    if model == "lgbm":
        m = lgb.LGBMClassifier(objective="binary", **lgbm.COMMON, min_child_samples=20, **p).fit(X, y)
    elif model == "xgb":
        m = xgb.XGBClassifier(objective="binary:logistic", tree_method="hist", random_state=SEED, n_jobs=4,
                              **GBDT, **p).fit(X, y)
    elif model == "catboost":
        m = cb.CatBoostClassifier(loss_function="Logloss", random_seed=SEED, thread_count=4, verbose=0,
                                  allow_writing_files=False, **GBDT, **p).fit(X, y)
    else:
        raise ValueError(model)
    return Scorer(lambda Z: m.predict_proba(Z)[:, 1])


# ---------------------------------------------------------------- CV
def rank_avg5(scorer, df, cols):
    rows, _ = lgbm.score_cases(scorer, df, cols)
    return M.ranking_summary([(s, i) for _, s, i, _ in rows])["Avg@5"]


def det_auroc(scorer, df, cols):
    return M.detection_summary(df["target"], scorer.predict(df[cols]))["AUROC"]


def select(df, cols, groups, key, grid_list, fit, evaluate):
    """Inner CV over `groups` of column `key`; strict > keeps the earlier (simpler) setting on ties."""
    best, best_s = None, -np.inf
    for p in grid_list:
        s = float(np.mean([evaluate(fit(df[df[key] != g], cols, p), df[df[key] == g], cols) for g in groups]))
        if s > best_s + 1e-12:
            best, best_s = p, s
    return best, best_s


class Timer:
    def __init__(self):
        self.fit_s, self.pred_s, self.pred_windows = [], 0.0, 0

    def summary(self):
        return {"fit_seconds_median": float(np.median(self.fit_s)), "n_final_fits": len(self.fit_s),
                "predict_ms_per_window": 1000 * self.pred_s / max(self.pred_windows, 1)}


def outer_rank(df, cols, model, key):
    """key='meta_root_cause' -> LOSO; key='meta_fold' -> repetition CV. Inner CV uses the same key."""
    fit = lambda d, c, p: fit_rank(model, d, c, p)  # noqa: E731
    rows, chosen, timer = [], {}, Timer()
    groups = sorted(df[key].unique())
    for held in groups:
        train = df[df[key] != held]
        p, inner = select(train, cols, [g for g in groups if g != held], key, RANK_GRIDS[model], fit, rank_avg5)
        t0 = time.perf_counter()
        scorer = fit(train, cols, p)
        timer.fit_s.append(time.perf_counter() - t0)
        test = df[df[key] == held]
        t0 = time.perf_counter()
        r, _ = lgbm.score_cases(scorer, test, cols)
        timer.pred_s += time.perf_counter() - t0
        timer.pred_windows += test.groupby(["meta_case_id", "meta_window"]).ngroups
        rows += r
        chosen[str(held)] = {"params": p, "inner": inner}
    return rows, chosen, timer.summary()


def outer_det(D, cols, model):
    fit = lambda d, c, p: fit_det(model, d, c, p)  # noqa: E731
    parts, chosen, timer = [], {}, Timer()
    folds = sorted(D["meta_fold"].unique())
    for test in folds:
        train = D[D["meta_fold"] != test]
        p, inner = select(train, cols, [f for f in folds if f != test], "meta_fold", DET_GRIDS[model], fit, det_auroc)
        t0 = time.perf_counter()
        scorer = fit(train, cols, p)
        timer.fit_s.append(time.perf_counter() - t0)
        te = D[D["meta_fold"] == test]
        t0 = time.perf_counter()
        s = scorer.predict(te[cols])
        timer.pred_s += time.perf_counter() - t0
        timer.pred_windows += len(te)
        parts.append(pd.DataFrame({"row": te.index.to_numpy(), "score": s}))
        chosen[str(int(test))] = {"params": p, "inner": inner}
    scored = pd.concat(parts).set_index("row")["score"].reindex(D.index).to_numpy()
    return scored, chosen, timer.summary()


# ---------------------------------------------------------------- serialisation
def rows_out(rows):
    return [[cid, [float(x) for x in s], int(i), meta] for cid, s, i, meta in rows]


def rows_in(rows):
    return [(cid, np.array(s, dtype=float), i, meta) for cid, s, i, meta in rows]


def run_model(model, R, D, out):
    res = {"model": model, "ranking": {}, "detection": {}}
    for fs, cols in rank_fsets(R).items():
        for split, key in (("loso", "meta_root_cause"), ("rep", "meta_fold")):
            t0 = time.perf_counter()
            rows, chosen, timing = outer_rank(R, cols, model, key)
            res["ranking"][f"{fs}|{split}"] = {"rows": rows_out(rows), "chosen": chosen, "timing": timing,
                                               "wall_seconds": time.perf_counter() - t0}
            print(model, fs, split, round(M.ranking_summary([(s, i) for _, s, i, _ in rows])["Avg@5"], 3),
                  f"{time.perf_counter() - t0:.0f}s", flush=True)
    for fs, cols in det_fsets(D, R).items():
        t0 = time.perf_counter()
        scored, chosen, timing = outer_det(D, cols, model)
        res["detection"][fs] = {"scores": [float(x) for x in scored], "chosen": chosen, "timing": timing,
                                "wall_seconds": time.perf_counter() - t0}
        print(model, "det", fs, round(M.detection_summary(D["target"], scored)["AUROC"], 3),
              f"{time.perf_counter() - t0:.0f}s", flush=True)
    (out / "parts").mkdir(parents=True, exist_ok=True)
    (out / "parts" / f"{model}.json").write_text(json.dumps(res), encoding="utf-8")


# ---------------------------------------------------------------- combine + decide
def simplicity(name):
    if name.startswith("stat_"):
        return (0, 0, 0)
    model, fs, kind = name.split("|")
    return (1 + MODELS.index(model), FSETS.index(fs), kind == "hybrid")


def det_paired(D, a, b, n_boot=1000, seed=0):
    y, case = D["target"].to_numpy(), D["meta_case_id"].to_numpy()
    ids = np.unique(case)
    groups = {c: np.flatnonzero(case == c) for c in ids}
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n_boot):
        idx = np.concatenate([groups[c] for c in rng.choice(ids, size=len(ids), replace=True)])
        d.append(M.detection_summary(y[idx], a[idx])["AUROC"] - M.detection_summary(y[idx], b[idx])["AUROC"])
    lo, hi = float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))
    mean = M.detection_summary(y, a)["AUROC"] - M.detection_summary(y, b)["AUROC"]
    return {"mean_diff": float(mean), "ci95": (lo, hi), "verdict": "better" if lo > 0 else ("worse" if hi < 0 else "no difference")}


def det_ci(D, s, n_boot=1000, seed=0):
    y, case = D["target"].to_numpy(), D["meta_case_id"].to_numpy()
    ids = np.unique(case)
    groups = {c: np.flatnonzero(case == c) for c in ids}
    rng = np.random.default_rng(seed)
    b = [M.detection_summary(y[idx], s[idx])["AUROC"]
         for idx in (np.concatenate([groups[c] for c in rng.choice(ids, size=len(ids), replace=True)]) for _ in range(n_boot))]
    return (float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975)))


def combine(R, D, out):
    parts = {m: json.loads((out / "parts" / f"{m}.json").read_text(encoding="utf-8")) for m in MODELS}
    stat = list(case_rankings(add_scores(R), "s_stat_combined"))
    loso, rep, info = {"stat_combined": stat}, {"stat_combined": stat}, {}
    for m in MODELS:
        for fs in FSETS:
            for split, store in (("loso", loso), ("rep", rep)):
                p = parts[m]["ranking"][f"{fs}|{split}"]
                rows = rows_in(p["rows"])
                store[f"{m}|{fs}|pure"] = rows
                store[f"{m}|{fs}|hybrid"] = hybrid(rows, stat)
                info.setdefault(f"{m}|{fs}", {})[split] = {"chosen": p["chosen"], "timing": p["timing"],
                                                           "wall_seconds": p["wall_seconds"]}
    names = list(loso)
    res = {"ranking_loso": {n: summarize(loso[n]) for n in names},
           "ranking_rep": {n: summarize(rep[n]) for n in names}, "ranking_info": info}
    best = max(names, key=lambda n: (res["ranking_loso"][n]["Avg@5"], [-x for x in simplicity(n)]))
    res["paired_loso_vs_best"] = {n: paired_diff(loso[n], loso[best]) for n in names if n != best}
    res["paired_loso_vs_stat"] = {n: paired_diff(loso[n], stat) for n in names if n != "stat_combined"}
    res["paired_rep_vs_stat"] = {n: paired_diff(rep[n], stat) for n in names if n != "stat_combined"}
    eligible = [n for n in names
                if (n == best or res["paired_loso_vs_best"][n]["verdict"] != "worse")
                and (n == "stat_combined" or res["paired_rep_vs_stat"][n]["verdict"] != "worse")]
    res["ranking_decision"] = {"best": best, "eligible": sorted(eligible, key=simplicity),
                               "pick": min(eligible, key=simplicity)}
    services = sorted(R["meta_root_cause"].unique())
    res["loso_by_service"] = {svc: {n: M.ranking_summary([(s, i) for _, s, i, meta in loso[n] if meta["root_cause"] == svc])["Avg@5"]
                                    for n in names} for svc in services}

    metric_cols = [f"f_cm_{s}_dmean__max" for s in METRIC_SIGNALS]
    dscores = {"stat_metric": D[metric_cols].max(axis=1, skipna=True).to_numpy()}
    dinfo = {}
    for m in MODELS:
        for fs in FSETS:
            p = parts[m]["detection"][fs]
            dscores[f"{m}|{fs}|pure"] = np.array(p["scores"], dtype=float)
            dinfo[f"{m}|{fs}"] = {"chosen": p["chosen"], "timing": p["timing"], "wall_seconds": p["wall_seconds"]}
    det = {n: {**M.detection_summary(D["target"], s), "AUROC_ci95": det_ci(D, s)} for n, s in dscores.items()}
    dbest = max(det, key=lambda n: (det[n]["AUROC"], [-x for x in simplicity(n)]))
    dpair = {n: det_paired(D, s, dscores[dbest]) for n, s in dscores.items() if n != dbest}
    deligible = [n for n in det if n == dbest or dpair[n]["verdict"] != "worse"]
    res.update({"detection": det, "detection_info": dinfo, "paired_det_vs_best": dpair,
                "detection_decision": {"best": dbest, "eligible": sorted(deligible, key=simplicity),
                                       "pick": min(deligible, key=simplicity)}})
    (out / "results.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    write_md(res, names, services, out)
    print("ranking", res["ranking_decision"], "\ndetection", res["detection_decision"], flush=True)


def ci(x):
    return f"{fmt(x[0])}–{fmt(x[1])}"


def write_md(res, names, services, out):
    rd, dd = res["ranking_decision"], res["detection_decision"]
    L = ["# R6 results (RE2-OB, model family x feature set)", "",
         f"- ranking pick: **{rd['pick']}** (best LOSO: {rd['best']}; {len(rd['eligible'])} eligible)",
         f"- detection pick: **{dd['pick']}** (best AUROC: {dd['best']}; {len(dd['eligible'])} eligible)", "",
         "## Root-cause ranking", "",
         "| candidate | LOSO Avg@5 (95% CI) | vs best (95% CI) | LOSO AC@1 | rep Avg@5 | rep vs stat | eligible |",
         "|---|---|---|---|---|---|---|"]
    for n in sorted(names, key=lambda n: -res["ranking_loso"][n]["Avg@5"]):
        lo, rp = res["ranking_loso"][n], res["ranking_rep"][n]
        vb = res["paired_loso_vs_best"].get(n)
        vs = res["paired_rep_vs_stat"].get(n)
        L.append(f"| {n} | {fmt(lo['Avg@5'])} ({ci(lo['Avg@5_ci95'])}) | "
                 f"{(fmt(vb['mean_diff']) + ' (' + ci(vb['ci95']) + ')') if vb else 'best'} | {fmt(lo['AC@1'])} | "
                 f"{fmt(rp['Avg@5'])} | {vs['verdict'] if vs else '-'} | {'yes' if n in rd['eligible'] else ''} |")
    pure = ["stat_combined"] + [n for n in names if n.endswith("|pure")]
    L += ["", "## LOSO Avg@5 by held-out root-cause service (pure models)", "",
          "| candidate | " + " | ".join(services) + " |", "|---|" + "---|" * len(services)]
    for n in pure:
        L.append(f"| {n} | " + " | ".join(fmt(res["loso_by_service"][s][n]) for s in services) + " |")
    faults = sorted(res["ranking_loso"]["stat_combined"]["by_fault"])
    L += ["", "## LOSO Avg@5 by fault (pure models)", "", "| candidate | " + " | ".join(faults) + " |",
          "|---|" + "---|" * len(faults)]
    for n in pure:
        L.append(f"| {n} | " + " | ".join(fmt(res["ranking_loso"][n]["by_fault"].get(f)) for f in faults) + " |")
    L += ["", "## Detection (repetition 3-fold, out-of-fold windows)", "",
          "| candidate | AUROC (95% CI) | AUPRC | vs best (95% CI) | eligible |", "|---|---|---|---|---|"]
    for n in sorted(res["detection"], key=lambda n: -res["detection"][n]["AUROC"]):
        d, v = res["detection"][n], res["paired_det_vs_best"].get(n)
        L.append(f"| {n} | {fmt(d['AUROC'])} ({ci(d['AUROC_ci95'])}) | {fmt(d['AUPRC'])} | "
                 f"{(fmt(v['mean_diff']) + ' (' + ci(v['ci95']) + ')') if v else 'best'} | {'yes' if n in dd['eligible'] else ''} |")
    L += ["", "## Timing (final fits of the outer splits; this PC, 4 threads)", "",
          "| model\\|features | ranking LOSO fit s (median) | ranking predict ms/window | detection fit s | detection predict ms/window | total wall s |",
          "|---|---|---|---|---|---|"]
    for k, v in res["ranking_info"].items():
        dv = res["detection_info"][k]
        wall = v["loso"]["wall_seconds"] + v["rep"]["wall_seconds"] + dv["wall_seconds"]
        L.append(f"| {k} | {v['loso']['timing']['fit_seconds_median']:.2f} | {v['loso']['timing']['predict_ms_per_window']:.3f} | "
                 f"{dv['timing']['fit_seconds_median']:.2f} | {dv['timing']['predict_ms_per_window']:.3f} | {wall:.0f} |")
    L += ["", "## Chosen hyperparameters (LOSO per held-out service / detection per fold)", ""]
    for k, v in res["ranking_info"].items():
        L.append(f"- {k} ranking: " + "; ".join(f"{s}: {c['params']}" for s, c in v["loso"]["chosen"].items()))
        L.append(f"- {k} detection: " + "; ".join(f"{f}: {c['params']}" for f, c in res["detection_info"][k]["chosen"].items()))
    L += ["", "## Decision (pre-registered rule, applied mechanically)", "",
          f"- ranking: best {rd['best']}; eligible (simplest first) {rd['eligible']}; pick **{rd['pick']}**",
          f"- detection: best {dd['best']}; eligible (simplest first) {dd['eligible']}; pick **{dd['pick']}**"]
    (out / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--out", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--model", choices=MODELS)
    g.add_argument("--combine", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    R = pd.read_parquet(Path(args.features) / "ranking.parquet")
    D = pd.read_parquet(Path(args.features) / "detection.parquet")
    if args.combine:
        combine(R, D, out)
    else:
        run_model(args.model, R, D, out)


if __name__ == "__main__":
    main()
