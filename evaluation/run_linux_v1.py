"""linux-v1 evaluation of the frozen method (docs/METHOD-FREEZE-v2.md section 4, METHOD-FREEZE.md 6.3,
docs/LINUX-V1-DATA-TRANSLATION.md).

  python -m evaluation.run_linux_v1 --features data/features/linux-v1-v0 --out experiments/<id>
  python -m evaluation.run_linux_v1 --features data/features/linux-v1-v0 --re2ob data/features/re2ob-v0 --out ...

Method A (supplementary): the frozen v2 model files are applied unchanged to every linux-v1 case.
  ranking  : RF rel18 (main), V4 (v1 frozen: LambdaRank rel18 rank-averaged with stat_combined),
             stat_combined, random. Cases = eligible cpu_saturation / pod_failure runs (ranking.parquet).
  detection: LightGBM all58 (main), v1 detector (rel36), stat_metric. Window AUROC/AUPRC with case bootstrap.
             The operating threshold is the 95th percentile of the TRAINING normal-window scores, so run alarm
             rates need the RE2-OB detection table (--re2ob); without it only AUROC/AUPRC are reported.
  edge     : frozen statistical edge score vs random, eligible network_delay / packet_loss runs.
  node view: RF rel18 node ranking for edge faults (either end / source only / destination only), surge: rank
             of frontend (descriptive).
Method B (main, needs --re2ob): repetition 3-fold. Train on RE2-OB 90 cases + linux-v1 training folds with the
  frozen hyperparameters, test on the held-out repetition. RF rel18 (main) and RF rel14 (secondary, rx/tx
  removed), LightGBM all58 detection with threshold = 95th percentile of training normal windows.
No hyperparameter is selected here. All CIs are case-level bootstrap (2000, seed 0).
"""
import argparse
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from evaluation.edge_rank import edge_case_rankings
from evaluation.run_baselines import add_scores
from features.schema import CANDIDATES

V2 = Path("experiments/20261028-re2ob-v2-freeze")
V1 = Path("experiments/20261027-re2ob-r5-freeze")
RXTX = ("f_cm_net_rx_pkts_dmean", "f_cm_net_rx_pkts_dmax", "f_cm_net_tx_pkts_dmean", "f_cm_net_tx_pkts_dmax")
NODE_FAULTS = ("cpu_saturation", "pod_failure")
EDGE_FAULTS = ("network_delay", "packet_loss")
N_BOOT, SEED = 2000, 0
ALARM_RUN = 2           # consecutive windows above threshold
THRESHOLD_Q = 0.95      # of training normal-window scores


# ---------------------------------------------------------------- helpers
def summarize(rows, by=("fault",)):
    """rows: (case_id, scores, true_index, meta). Overall + CI, per fault, paymentservice separately."""
    cases = [(s, i) for _, s, i, _ in rows]
    out = M.ranking_summary(cases)
    per = M.per_case_scores(cases)
    for m in ("AC@1", "AC@3", "Avg@5", "MRR"):
        out[f"{m}_ci95"] = M.bootstrap_ci(per, m, n_boot=N_BOOT, seed=SEED)
    for key in by:
        out[f"by_{key}"] = {v: M.ranking_summary([(s, i) for _, s, i, mt in rows if mt[key] == v])
                            for v in sorted({mt[key] for _, _, _, mt in rows})}
    pay = [(s, i) for _, s, i, mt in rows if mt.get("root_cause") == "paymentservice"]
    out["paymentservice"] = M.ranking_summary(pay) if pay else {}
    out["per_case"] = [{"case_id": c, **mt, **pc, "rank": M.rank_distribution(s, i)[0] + 1}
                       for (c, s, i, mt), pc in zip(rows, per)]
    return out


def paired(rows_a, rows_b, metric="Avg@5"):
    """Mean difference a - b of a per-case metric with a paired case bootstrap CI."""
    b = {c: (s, i) for c, s, i, _ in rows_b}
    keep = [(s, i, *b[c]) for c, s, i, _ in rows_a if c in b]
    va = np.array([r[metric] for r in M.per_case_scores([(s, i) for s, i, _, _ in keep])])
    vb = np.array([r[metric] for r in M.per_case_scores([(s2, i2) for _, _, s2, i2 in keep])])
    d = va - vb
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(d), size=(N_BOOT, len(d)))
    means = d[idx].mean(axis=1)
    lo, hi = float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
    verdict = "better" if lo > 0 else ("worse" if hi < 0 else "no difference")
    return {"metric": metric, "diff": float(d.mean()), "ci95": (lo, hi), "verdict": verdict, "n_cases": len(d)}


def hybrid(a_rows, b_rows):
    """V4: per case -(rank in a + rank in b)/2 (training/run_r4b.hybrid)."""
    b = {cid: s for cid, s, _, _ in b_rows}
    out = []
    for cid, s, i, meta in a_rows:
        ra = pd.Series(s).rank(ascending=False, method="average", na_option="bottom").to_numpy()
        rb = pd.Series(b[cid]).rank(ascending=False, method="average", na_option="bottom").to_numpy()
        out.append((cid, -(ra + rb) / 2, i, meta))
    return out


def detection_with_ci(y, s, case_ids):
    res = M.detection_summary(y, s)
    rng = np.random.default_rng(SEED)
    uniq = np.unique(case_ids)
    groups = {c: np.flatnonzero(case_ids == c) for c in uniq}
    boots = []
    for _ in range(N_BOOT):
        idx = np.concatenate([groups[c] for c in rng.choice(uniq, size=len(uniq), replace=True)])
        if len(np.unique(y[idx])) == 2:
            boots.append(M.detection_summary(y[idx], s[idx])["AUROC"])
    res["AUROC_ci95"] = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    return res


def run_alarms(det, score, threshold):
    """Run alarm = 2 consecutive windows above threshold within onset+60 s .. removal (fault_active, or the sham
    period sham_active for control runs). Returns per-run table."""
    d = det.assign(_s=score)
    d = d[d["meta_label"].isin(("fault_active", "sham_active"))].sort_values(["meta_case_id", "meta_rel"])
    rows = []
    for cid, g in d.groupby("meta_case_id"):
        above = (g["_s"].to_numpy() > threshold).astype(int)
        rel = g["meta_rel"].to_numpy()
        hit, first = False, None
        for k in range(len(above) - ALARM_RUN + 1):
            if above[k:k + ALARM_RUN].all() and np.all(np.diff(rel[k:k + ALARM_RUN]) == 10):
                hit, first = True, float(rel[k + ALARM_RUN - 1] + 30)   # alarm known at the end of the 2nd window
                break
        rows.append({"case_id": cid, "kind": g["meta_kind"].iloc[0], "fault": g["meta_fault"].iloc[0],
                     "eligible": bool(g["meta_eligible"].iloc[0]) if "meta_eligible" in g else True,
                     "alarm": hit, "alarm_rel_s": first})
    return pd.DataFrame(rows)


def alarm_summary(runs):
    f = runs[runs["kind"] == "fault"]
    c = runs[runs["kind"] == "control"]
    by = {k: float(g["alarm"].mean()) for k, g in f.groupby("fault")}
    return {"fault_alarm_rate": float(f["alarm"].mean()) if len(f) else None, "n_fault_runs": int(len(f)),
            "control_false_alarm_rate": float(c["alarm"].mean()) if len(c) else None, "n_control_runs": int(len(c)),
            "fault_alarm_rate_by_fault": by,
            "median_alarm_rel_s": float(f.loc[f["alarm"], "alarm_rel_s"].median()) if f["alarm"].any() else None}


def node_view(nodeview, score_col):
    """Edge faults: is either end / the source / the destination of the true edge in the top k of node ranking."""
    out = {}
    r = nodeview[nodeview["meta_fault"].isin(EDGE_FAULTS)].copy()
    r["meta_root_cause_edge"] = r["meta_root_cause"]
    res = {"either": [], "source": [], "destination": []}
    for cid, g in r.groupby("meta_case_id"):
        src, dst = g["meta_root_cause_edge"].iloc[0].split("->")
        rows = list(case_rankings(g.assign(meta_root_cause=src), score_col))
        if not rows:
            continue
        _, s, _, _ = rows[0]
        i_src, i_dst = CANDIDATES.index(src), CANDIDATES.index(dst)
        h = {k: (M.case_hit_at(s, i_src, k), M.case_hit_at(s, i_dst, k)) for k in (1, 3, 5)}
        res["source"].append({k: v[0] for k, v in h.items()})
        res["destination"].append({k: v[1] for k, v in h.items()})
        res["either"].append({k: max(v) for k, v in h.items()})       # lenient, not the paper definition
    for name, lst in res.items():
        out[name] = {f"AC@{k}": float(np.mean([x[k] for x in lst])) for k in (1, 3, 5)} if lst else {}
        out[name]["n_cases"] = len(lst)
    return out


def surge_frontend_rank(nodeview, score_col):
    r = nodeview[nodeview["meta_fault"] == "traffic_surge"]
    ranks = []
    for cid, g in r.groupby("meta_case_id"):
        rows = list(case_rankings(g.assign(meta_root_cause="frontend"), score_col))
        if rows:
            _, s, i, _ = rows[0]
            ranks.append({"case_id": cid, "frontend_rank": M.rank_distribution(s, i)[0] + 1})
    return ranks


def edge_eval(edges, cases):
    sel = cases[(cases["kind"] == "fault") & cases["eligible"] & cases["fault"].isin(EDGE_FAULTS)]
    roots = dict(zip(sel["case_id"], sel["root_cause"]))
    metas = {c: {"fault": f, "fold": int(r)} for c, f, r in zip(sel["case_id"], sel["fault"], sel["repetition"])}
    rows = list(edge_case_rankings(edges[edges["meta_case_id"].isin(roots)], roots, metas))
    res = summarize(rows)
    rand = [(c, np.zeros(len(s)), i, m) for c, s, i, m in rows]      # constant score = random expectation
    res_rand = M.ranking_summary([(s, i) for _, s, i, _ in rand])
    by_edge = {}
    for c, s, i, m in rows:
        by_edge.setdefault(m["root_cause"], []).append((s, i))
    res["by_edge"] = {e: M.ranking_summary(v) for e, v in sorted(by_edge.items())}
    res["n_candidates_median"] = float(np.median([len(s) for _, s, _, _ in rows])) if rows else None
    return res, res_rand


# ---------------------------------------------------------------- method A
def load_frozen():
    v2 = json.loads((V2 / "frozen.json").read_text(encoding="utf-8"))
    v1 = json.loads((V1 / "frozen.json").read_text(encoding="utf-8"))
    rf = joblib.load(V2 / "models" / "ranker_rf.joblib")
    det = lgb.Booster(model_file=str(V2 / "models" / "detector_lgbm.txt"))
    v1_rank = lgb.Booster(model_file=str(V1 / "models" / "ranker.txt"))
    v1_det = lgb.Booster(model_file=str(V1 / "models" / "detector.txt"))
    return v2, v1, rf, det, v1_rank, v1_det


def rf_scores(rf, df):
    X = df[rf["features"]].astype(float).fillna(rf["nan_fill"]).to_numpy()
    return rf["model"].predict_proba(X)[:, 1]


def method_a(feat):
    v2, v1, rf, det, v1_rank, v1_det = load_frozen()
    R = add_scores(pd.read_parquet(feat / "ranking.parquet"))
    NV = pd.read_parquet(feat / "ranking-nodeview.parquet")
    D = pd.read_parquet(feat / "detection.parquet")
    DI = pd.read_parquet(feat / "detection-ineligible.parquet")
    E = pd.read_parquet(feat / "edges.parquet")
    C = pd.read_parquet(feat / "cases.parquet")
    assert set(R["meta_fault"]) <= set(NODE_FAULTS), "ranking.parquet must hold cpu/pod cases only"

    R["s_rf"] = rf_scores(rf, R)
    R["s_v1lgbm"] = v1_rank.predict(R[v1["ranking"]["features"]])
    NV["s_rf"] = rf_scores(rf, NV)

    rows = {m: list(case_rankings(R, f"s_{m}")) for m in ("rf", "v1lgbm", "stat_combined", "random")}
    rows["v4"] = hybrid(rows["v1lgbm"], rows["stat_combined"])
    ranking = {m: summarize(rows[m]) for m in ("rf", "v4", "stat_combined", "random")}
    ranking_paired = {"rf_minus_stat_combined": paired(rows["rf"], rows["stat_combined"]),
                      "rf_minus_v4": paired(rows["rf"], rows["v4"]),
                      "v4_minus_stat_combined": paired(rows["v4"], rows["stat_combined"])}

    y, cid = D["target"].to_numpy(), D["meta_case_id"].to_numpy()
    det_scores = {"lgbm_all58": det.predict(D[v2["detection"]["features"]]),
                  "v1_rel36": v1_det.predict(D[v1["detection"]["features"]]),
                  "stat_metric": D[[c for c in D.columns if c.startswith("f_cm_") and c.endswith("_dmean__max")]]
                  .max(axis=1, skipna=True).to_numpy()}
    detection = {k: detection_with_ci(y, s, cid) for k, s in det_scores.items()}
    detection["ineligible_windows"] = int(len(DI))

    edge, edge_rand = edge_eval(E, C)
    return {"ranking": ranking, "ranking_paired": ranking_paired, "detection": detection,
            "edge": {"stat_edge": edge, "random": edge_rand},
            "node_view_edge_faults": node_view(NV, "s_rf"), "surge_frontend_rank": surge_frontend_rank(NV, "s_rf"),
            "notes": ["Method A: RE2-OB final models applied unchanged; paymentservice is an unseen root cause.",
                      "rx/tx packet features are NaN in linux-v1 -> 0 in RF (LINUX-V1-DATA-TRANSLATION.md 1).",
                      "Run alarm rates need the RE2-OB training normal-window threshold (Method B / --re2ob)."]}


# ---------------------------------------------------------------- method B
def method_b(feat, re2):
    v2 = json.loads((V2 / "frozen.json").read_text(encoding="utf-8"))
    rp = {k: v for k, v in v2["ranking"]["params"].items()}
    dp = {k: v for k, v in v2["detection"]["params"].items()}
    rel18 = v2["ranking"]["features"]
    rel14 = [c for c in rel18 if c not in RXTX]
    dcols = v2["detection"]["features"]
    R2 = pd.read_parquet(re2 / "ranking.parquet")
    D2 = pd.read_parquet(re2 / "detection.parquet")
    R = add_scores(pd.read_parquet(feat / "ranking.parquet"))
    NV = pd.read_parquet(feat / "ranking-nodeview.parquet")
    D = pd.read_parquet(feat / "detection.parquet")
    DI = pd.read_parquet(feat / "detection-ineligible.parquet")
    for name, df in (("re2ob ranking", R2), ("re2ob detection", D2)):
        missing = [c for c in (rel18 if "ranking" in name else dcols) if c not in df]
        assert not missing, f"{name} lacks {missing[:5]}"

    folds = sorted(R["meta_fold"].unique())
    R["s_rf18"], R["s_rf14"] = np.nan, np.nan
    NV["s_rf18"] = np.nan
    D["s_det"], DI["s_det"] = np.nan, np.nan
    fold_info = []
    for f in folds:
        trR = pd.concat([R2[rel18 + ["target"]], R.loc[R["meta_fold"] != f, rel18 + ["target"]]], ignore_index=True)
        teR, teNV = R["meta_fold"] == f, NV["meta_fold"] == f
        for name, cols in (("rf18", rel18), ("rf14", rel14)):
            m = RandomForestClassifier(n_jobs=4, **rp).fit(trR[cols].astype(float).fillna(0.0).to_numpy(), trR["target"])
            R.loc[teR, f"s_{name}"] = m.predict_proba(R.loc[teR, cols].astype(float).fillna(0.0).to_numpy())[:, 1]
            if name == "rf18":
                NV.loc[teNV, "s_rf18"] = m.predict_proba(NV.loc[teNV, cols].astype(float).fillna(0.0).to_numpy())[:, 1]
        trD = pd.concat([D2[dcols + ["target"]], D.loc[D["meta_fold"] != f, dcols + ["target"]]], ignore_index=True)
        det = lgb.LGBMClassifier(objective="binary", **dp).fit(trD[dcols], trD["target"])
        thr = float(np.quantile(det.predict_proba(trD.loc[trD["target"] == 0, dcols])[:, 1], THRESHOLD_Q))
        for T in (D, DI):
            te = T["meta_fold"] == f
            if not te.any():
                continue
            T.loc[te, "s_det"] = det.predict_proba(T.loc[te, dcols])[:, 1]
            T.loc[te, "thr"] = thr
        fold_info.append({"fold": int(f), "n_train_rank_rows": int(len(trR)), "n_train_det_rows": int(len(trD)),
                          "threshold": thr})

    rows = {m: list(case_rankings(R, f"s_{m}")) for m in ("rf18", "rf14", "stat_combined", "random")}
    ranking = {m: summarize(rows[m]) for m in rows}
    ranking_paired = {"rf18_minus_stat_combined": paired(rows["rf18"], rows["stat_combined"]),
                      "rf14_minus_rf18": paired(rows["rf14"], rows["rf18"])}
    fold_avg5 = {m: [M.ranking_summary([(s, i) for _, s, i, mt in rows[m] if mt["fold"] == f]).get("Avg@5")
                     for f in folds] for m in rows}
    y, cid = D["target"].to_numpy(), D["meta_case_id"].to_numpy()
    detection = {"lgbm_all58": detection_with_ci(y, D["s_det"].to_numpy(), cid)}
    runs = pd.concat([run_alarms(D[D["meta_fold"] == f], D.loc[D["meta_fold"] == f, "s_det"], t["threshold"])
                      for f, t in zip(folds, fold_info)], ignore_index=True)
    inel = pd.concat([run_alarms(DI[DI["meta_fold"] == f], DI.loc[DI["meta_fold"] == f, "s_det"], t["threshold"])
                      for f, t in zip(folds, fold_info) if (DI["meta_fold"] == f).any()], ignore_index=True) \
        if len(DI) else pd.DataFrame()
    detection["alarms"] = alarm_summary(runs)
    detection["ineligible_fault_alarm_rate"] = float(inel["alarm"].mean()) if len(inel) else None
    detection["runs"] = runs.to_dict(orient="records")
    return {"folds": fold_info, "ranking": ranking, "ranking_paired": ranking_paired, "fold_avg5": fold_avg5,
            "detection": detection, "node_view_edge_faults": node_view(NV, "s_rf18"),
            "surge_frontend_rank": surge_frontend_rank(NV, "s_rf18"),
            "notes": ["Method B: frozen hyperparameters, no selection; training = RE2-OB 90 + linux-v1 other folds.",
                      "rf14 = rel18 without the 4 rx/tx features (secondary, pre-registered sensitivity)."]}


# ---------------------------------------------------------------- report
def fmt(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"


def write_md(res, out):
    L = ["# linux-v1 evaluation", ""]
    for key, title in (("method_a", "Method A — RE2-OB frozen models applied unchanged (supplementary)"),
                       ("method_b", "Method B — repetition 3-fold (main)")):
        if key not in res:
            continue
        r = res[key]
        L += [f"## {title}", "", "| ranking (eligible cpu/pod) | n | AC@1 | AC@3 | Avg@5 (95% CI) | MRR |",
              "|---|---:|---:|---:|---|---:|"]
        for m, v in r["ranking"].items():
            ci = v.get("Avg@5_ci95", (None, None))
            L.append(f"| {m} | {v.get('n_cases')} | {fmt(v.get('AC@1'))} | {fmt(v.get('AC@3'))} | "
                     f"{fmt(v.get('Avg@5'))} ({fmt(ci[0])}–{fmt(ci[1])}) | {fmt(v.get('MRR'))} |")
        L += ["", "| paired (Avg@5) | diff | 95% CI | verdict |", "|---|---:|---|---|"]
        for k, p in r["ranking_paired"].items():
            L.append(f"| {k} | {fmt(p['diff'])} | {fmt(p['ci95'][0])}–{fmt(p['ci95'][1])} | {p['verdict']} |")
        L += ["", "| detection | AUROC (95% CI) | AUPRC | windows |", "|---|---|---:|---:|"]
        for k, d in r["detection"].items():
            if isinstance(d, dict) and "AUROC" in d:
                L.append(f"| {k} | {fmt(d['AUROC'])} ({fmt(d['AUROC_ci95'][0])}–{fmt(d['AUROC_ci95'][1])}) | "
                         f"{fmt(d['AUPRC'])} | {d['n_windows']} |")
        if "alarms" in r["detection"]:
            a = r["detection"]["alarms"]
            L += ["", f"Run alarms: fault {fmt(a['fault_alarm_rate'])} of {a['n_fault_runs']}, control false alarm "
                      f"{fmt(a['control_false_alarm_rate'])} of {a['n_control_runs']}, median alarm at onset+"
                      f"{fmt(a['median_alarm_rel_s'])} s"]
        if "edge" in r:
            e, er = r["edge"]["stat_edge"], r["edge"]["random"]
            L += ["", "| edge ranking (eligible delay/loss) | n | AC@1 | AC@3 | Avg@5 |", "|---|---:|---:|---:|---:|",
                  f"| stat edge | {e.get('n_cases')} | {fmt(e.get('AC@1'))} | {fmt(e.get('AC@3'))} | {fmt(e.get('Avg@5'))} |",
                  f"| random | {er.get('n_cases')} | {fmt(er.get('AC@1'))} | {fmt(er.get('AC@3'))} | {fmt(er.get('Avg@5'))} |"]
        nv = r["node_view_edge_faults"]
        L += ["", "Node view of edge faults (AC@1 / AC@3): " +
              ", ".join(f"{k} {fmt(v.get('AC@1'))} / {fmt(v.get('AC@3'))}" for k, v in nv.items()), ""]
        L += [f"- {n}" for n in r["notes"]] + [""]
    (out / "results.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/linux-v1-v0")
    ap.add_argument("--re2ob", default=None, help="RE2-OB feature dir (ranking/detection parquet) for Method B")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    feat, out = Path(args.features), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res = {"features": str(feat), "method_a": method_a(feat)}
    if args.re2ob:
        res["method_b"] = method_b(feat, Path(args.re2ob))
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    write_md(res, out)
    print((out / "results.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
