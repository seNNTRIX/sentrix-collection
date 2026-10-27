"""LightGBM models with leakage-safe, case-grouped cross-validation.

Ranking model: shared-weight LambdaRank over (window, candidate) rows. A query
group is one window of one case; the label is 1 for the root-cause candidate.
No service identity is an input (only f_* columns of the chosen bundle).
"""
from functools import partial
import itertools

import lightgbm as lgb
import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from features.schema import CANDIDATES

SEED = 0
RANK_GRID = {"num_leaves": [7, 15, 31], "n_estimators": [100, 300], "min_child_samples": [20, 100]}
LOSO_GRID = {"num_leaves": [7, 15], "n_estimators": [100, 300], "min_child_samples": [20, 100]}
DET_GRID = {"num_leaves": [15, 31], "n_estimators": [100, 300], "min_child_samples": [20, 100]}
COMMON = {"learning_rate": 0.05, "random_state": SEED, "deterministic": True, "force_row_wise": True,
          "n_jobs": 4, "verbose": -1}


def grid(g):
    keys = sorted(g)
    for values in itertools.product(*(g[k] for k in keys)):
        yield dict(zip(keys, values))


def model_size(p):
    return (p["num_leaves"] * p["n_estimators"], -p["min_child_samples"])


# ---------------------------------------------------------------- ranking
def fit_ranker(df, cols, params, extra=None):
    """extra: additional LightGBM arguments that are not tuned (e.g. monotone_constraints)."""
    df = df.sort_values(["meta_case_id", "meta_window", "meta_candidate"])
    groups = df.groupby(["meta_case_id", "meta_window"], sort=False).size().to_numpy()
    m = lgb.LGBMRanker(objective="lambdarank", **COMMON, **params, **(extra or {}))
    m.fit(df[cols], df["target"], group=groups)
    return m


def score_cases(model, df, cols, candidates=CANDIDATES):
    df = df.copy()
    df["s_model"] = model.predict(df[cols])
    return list(case_rankings(df, "s_model", candidates)), df


def rank_avg5(model, df, cols):
    rows, _ = score_cases(model, df, cols)
    return M.ranking_summary([(s, i) for _, s, i, _ in rows])["Avg@5"]


def select_params(df, cols, folds, grid_def, fit, evaluate, key="meta_fold"):
    """Inner CV inside the training folds: train on the other groups, validate on one.

    key="meta_fold": groups are repetitions; key="meta_root_cause": groups are root-cause services (LOSO).
    """
    best, best_score = None, -np.inf
    for p in grid(grid_def):
        scores = []
        for val in folds:
            tr = df[df[key].isin([f for f in folds if f != val])]
            va = df[df[key] == val]
            scores.append(evaluate(fit(tr, cols, p), va, cols))
        s = float(np.mean(scores))
        if s > best_score + 1e-12 or (abs(s - best_score) <= 1e-12 and model_size(p) < model_size(best)):
            best, best_score = p, s
    return best, best_score


def cv_ranker(df, cols, candidates=CANDIDATES, fixed_params=None, extra=None):
    """Outer 3-fold by repetition. Returns per-case rows (out-of-fold), chosen params, models."""
    fit = fit_ranker if extra is None else partial(fit_ranker, extra=extra)
    oof, chosen, models, scored = [], {}, {}, []
    folds = sorted(df["meta_fold"].unique())
    for test in folds:
        train_df = df[df["meta_fold"] != test]
        train_folds = [f for f in folds if f != test]
        if fixed_params is None:
            params, inner = select_params(train_df, cols, train_folds, RANK_GRID, fit, rank_avg5)
        else:
            params, inner = fixed_params, None
        model = fit(train_df, cols, params)
        rows, sdf = score_cases(model, df[df["meta_fold"] == test], cols, candidates)
        oof += rows
        scored.append(sdf[["meta_case_id", "meta_window", "meta_rel", "meta_candidate", "meta_root_cause",
                           "meta_fault", "meta_fold", "target", "s_model"]])
        chosen[int(test)] = {"params": params, "inner_avg5": inner}
        models[int(test)] = model
    return oof, chosen, models, pd.concat(scored, ignore_index=True)


def loso_ranker(df, cols, extra=None, grid_def=None):
    """Leave-one-root-cause-service-out. For held-out service s: test = cases whose root cause is s,
    train = all other cases (s still appears there as a negative candidate). Hyperparameters by inner
    LOSO over the training services. Returns per-case rows (out-of-fold over all cases) and chosen params."""
    fit = fit_ranker if extra is None else partial(fit_ranker, extra=extra)
    grid_def = LOSO_GRID if grid_def is None else grid_def
    oof, chosen = [], {}
    services = sorted(df["meta_root_cause"].unique())
    for held in services:
        train_df = df[df["meta_root_cause"] != held]
        inner_services = [s for s in services if s != held]
        params, inner = select_params(train_df, cols, inner_services, grid_def, fit, rank_avg5, key="meta_root_cause")
        model = fit(train_df, cols, params)
        rows, _ = score_cases(model, df[df["meta_root_cause"] == held], cols)
        oof += rows
        chosen[held] = {"params": params, "inner_avg5": inner}
    return oof, chosen


# ---------------------------------------------------------------- detection
def fit_detector(df, cols, params):
    m = lgb.LGBMClassifier(objective="binary", **COMMON, **params)
    m.fit(df[cols], df["target"])
    return m


def det_auroc(model, df, cols):
    return M.detection_summary(df["target"], model.predict_proba(df[cols])[:, 1])["AUROC"]


def cv_detector(df, cols):
    folds = sorted(df["meta_fold"].unique())
    parts, chosen = [], {}
    for test in folds:
        tr = df[df["meta_fold"] != test]
        params, inner = select_params(tr, cols, [f for f in folds if f != test], DET_GRID, fit_detector, det_auroc)
        model = fit_detector(tr, cols, params)
        te = df[df["meta_fold"] == test].copy()
        te["s_model"] = model.predict_proba(te[cols])[:, 1]
        parts.append(te[["meta_case_id", "meta_window", "target", "s_model"]])
        chosen[int(test)] = {"params": params, "inner_auroc": inner}
    return pd.concat(parts, ignore_index=True), chosen


# ---------------------------------------------------------------- joint classification baseline
JOINT_PARAMS = {"num_leaves": 15, "n_estimators": 200, "min_child_samples": 20}


def wide_table(df, cols):
    """(case, window) rows; one column per candidate x feature (service identity = column position)."""
    # unstack keeps only (case, window) pairs that exist; pivot_table(dropna=False) built the
    # full cartesian product and produced rows without labels.
    piv = df.set_index(["meta_case_id", "meta_window", "meta_candidate"])[cols].unstack("meta_candidate")
    piv.columns = [f"{c}__{feat}" for feat, c in piv.columns]
    meta = df.groupby(["meta_case_id", "meta_window"])[["meta_rel", "meta_fold", "meta_root_cause", "meta_fault"]].first()
    return piv.join(meta).reset_index()


def cv_joint(df, cols):
    """service x fault classes; case prediction = mean class probability over 60-300 s windows."""
    from evaluation.aggregate import HORIZON
    w = wide_table(df, cols)
    xcols = [c for c in w.columns if "__" in c]
    w["label"] = w["meta_root_cause"] + "|" + w["meta_fault"]
    rows, fault_rows = [], []
    for test in sorted(w["meta_fold"].unique()):
        tr, te = w[w["meta_fold"] != test], w[w["meta_fold"] == test]
        m = lgb.LGBMClassifier(objective="multiclass", **COMMON, **JOINT_PARAMS)
        m.fit(tr[xcols], tr["label"])
        te = te[(te["meta_rel"] >= HORIZON[0]) & (te["meta_rel"] < HORIZON[1])]
        prob = pd.DataFrame(m.predict_proba(te[xcols]), columns=m.classes_, index=te.index)
        prob["meta_case_id"] = te["meta_case_id"].to_numpy()
        for case_id, g in prob.groupby("meta_case_id"):
            p = g.drop(columns="meta_case_id").mean()
            svc = {c: p[[k for k in p.index if k.split("|")[0] == c]].sum() for c in CANDIDATES}
            info = te[te["meta_case_id"] == case_id].iloc[0]
            scores = np.array([svc[c] for c in CANDIDATES])
            rows.append((case_id, scores, list(CANDIDATES).index(info["meta_root_cause"]),
                         {"fault": info["meta_fault"], "fold": int(test), "root_cause": info["meta_root_cause"]}))
            faults = {}
            for k, v in p.items():
                faults[k.split("|")[1]] = faults.get(k.split("|")[1], 0) + v
            fault_rows.append((info["meta_fault"], max(faults, key=faults.get)))
    return rows, fault_rows
