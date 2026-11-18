"""R6b: rank-average ensembles of the R6 models (pre-registered in experiments/20261027-re2ob-r6b-ensemble/config.yaml).

  .venv-r6/Scripts/python -m training.run_r6b --r6 experiments/20261027-re2ob-r6-models --out experiments/20261027-re2ob-r6b-ensemble

Trains nothing. Reads the R6 out-of-fold rows (parts/<model>.json) and the R6 decision (results.json),
builds equal-weight rank-average ensembles and applies the decision rule in config.yaml mechanically.
"""
import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from evaluation.run_baselines import METRIC_SIGNALS, add_scores
from training.run_r4 import fmt, paired_diff, summarize
from training.run_r6 import FSETS, MODELS, ci, det_ci, det_paired, rows_in

GBDTS = ["lgbm", "xgb", "catboost"]
RANK_ENSEMBLES = {"E_gbdt_stat": GBDTS + ["stat"], "E_all": MODELS, "E_all_stat": MODELS + ["stat"]}  # fewest members first
DET_ENSEMBLES = {"D_all": MODELS, "D_all_stat": MODELS + ["stat"]}


def ranks(s):
    """High score = rank 1, ties average, NaN last (same rule as R4b hybrid)."""
    return pd.Series(s).rank(ascending=False, method="average", na_option="bottom").to_numpy()


def rank_average(members):
    """members: list of case-row lists aligned by case id. Score = -(mean rank)."""
    by_id = [{cid: s for cid, s, _, _ in rows} for rows in members]
    out = []
    for cid, _, i, meta in members[0]:
        out.append((cid, -np.mean([ranks(m[cid]) for m in by_id], axis=0), i, meta))
    return out


def mean_spearman(a_rows, b_rows):
    """Mean over cases of the Spearman correlation between two members' candidate scores."""
    b = {cid: s for cid, s, _, _ in b_rows}
    r = [np.corrcoef(ranks(s), ranks(b[cid]))[0, 1] for cid, s, _, _ in a_rows]
    return float(np.nanmean(r))


def pick_rows(name, store, stat):
    if name == "stat_combined":
        return stat
    return store[name]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--r6", default="experiments/20261027-re2ob-r6-models")
    ap.add_argument("--r4b", default="experiments/20261027-re2ob-r4b")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    r6, out = Path(args.r6), Path(args.out)
    R = pd.read_parquet(Path(args.features) / "ranking.parquet")
    D = pd.read_parquet(Path(args.features) / "detection.parquet")
    parts = {m: json.loads((r6 / "parts" / f"{m}.json").read_text(encoding="utf-8")) for m in MODELS}
    r6res = json.loads((r6 / "results.json").read_text(encoding="utf-8"))
    rpick, dpick = r6res["ranking_decision"]["pick"], r6res["detection_decision"]["pick"]

    # ---------------------------------------------------------------- ranking
    stat = list(case_rankings(add_scores(R), "s_stat_combined"))
    member = {split: {} for split in ("loso", "rep")}
    for m in MODELS:
        for fs in FSETS:
            for split in ("loso", "rep"):
                member[split][(m, fs)] = rows_in(parts[m]["ranking"][f"{fs}|{split}"]["rows"])
    for split in ("loso", "rep"):
        for fs in FSETS:
            member[split][("stat", fs)] = stat

    # R6 pick rows rebuilt from the same parts (pure or hybrid with stat)
    def r6_rows(split):
        if rpick == "stat_combined":
            return stat
        m, fs, kind = rpick.split("|")
        rows = member[split][(m, fs)]
        return rows if kind == "pure" else rank_average([rows, stat])

    ens = {"loso": {}, "rep": {}}
    for split in ("loso", "rep"):
        for e, ms in RANK_ENSEMBLES.items():
            for fs in FSETS:
                ens[split][f"{e}|{fs}"] = rank_average([member[split][(m, fs)] for m in ms])
    pick_loso, pick_rep = r6_rows("loso"), r6_rows("rep")
    names = list(ens["loso"])
    res = {"r6_pick": {"ranking": rpick, "detection": dpick},
           "ranking_loso": {n: summarize(ens["loso"][n]) for n in names},
           "ranking_rep": {n: summarize(ens["rep"][n]) for n in names},
           "reference_loso": {f"R6 pick ({rpick})": summarize(pick_loso), "stat_combined": summarize(stat)},
           "reference_rep": {f"R6 pick ({rpick})": summarize(pick_rep), "stat_combined": summarize(stat)},
           "paired_loso_vs_r6_pick": {n: paired_diff(ens["loso"][n], pick_loso) for n in names},
           "paired_rep_vs_stat": {n: paired_diff(ens["rep"][n], stat) for n in names}}
    r4b = Path(args.r4b) / "results.json"
    if r4b.exists():
        v4 = json.loads(r4b.read_text(encoding="utf-8"))
        res["reference_r5_v4"] = {"loso": v4["ranking_loso"]["V4_hybrid"], "rep": v4["ranking_rep"]["V4_hybrid"],
                                  "source": str(r4b)}
    eligible = [n for n in names if res["paired_loso_vs_r6_pick"][n]["verdict"] == "better"
                and res["paired_rep_vs_stat"][n]["verdict"] != "worse"]
    order = lambda n: (list(RANK_ENSEMBLES).index(n.split("|")[0]), FSETS.index(n.split("|")[1]))  # noqa: E731
    res["ranking_decision"] = {"eligible": sorted(eligible, key=order),
                               "pick": min(eligible, key=order) if eligible else rpick,
                               "replaces_r6_pick": bool(eligible)}

    # diversity and per-member scores (LOSO)
    res["members_loso_avg5"] = {f"{m}|{fs}": M.ranking_summary([(s, i) for _, s, i, _ in member["loso"][(m, fs)]])["Avg@5"]
                                for m in MODELS for fs in FSETS}
    res["members_loso_avg5"]["stat_combined"] = M.ranking_summary([(s, i) for _, s, i, _ in stat])["Avg@5"]
    res["member_spearman_loso"] = {
        fs: {f"{a}~{b}": mean_spearman(member["loso"][(a, fs)], member["loso"][(b, fs)])
             for a, b in combinations(MODELS + ["stat"], 2)} for fs in FSETS}

    # timing: members run one after another in sentrix-core
    rtime = {(m, fs): parts[m]["ranking"][f"{fs}|loso"]["timing"]["predict_ms_per_window"] for m in MODELS for fs in FSETS}
    res["ranking_predict_ms_per_window"] = {f"{e}|{fs}": sum(rtime[(m, fs)] for m in ms if m != "stat")
                                            for e, ms in RANK_ENSEMBLES.items() for fs in FSETS}

    # ---------------------------------------------------------------- detection
    metric_cols = [f"f_cm_{s}_dmean__max" for s in METRIC_SIGNALS]
    dmember = {(m, fs): np.array(parts[m]["detection"][fs]["scores"], dtype=float) for m in MODELS for fs in FSETS}
    stat_metric = D[metric_cols].max(axis=1, skipna=True).to_numpy()
    fold = D["meta_fold"].to_numpy()

    def pct_in_fold(s):
        """Percentile rank within each evaluated fold; NaN treated as the lowest score."""
        out_ = np.empty(len(s))
        for f in np.unique(fold):
            idx = fold == f
            out_[idx] = pd.Series(s[idx]).rank(pct=True, method="average", na_option="top").to_numpy()
        return out_

    dens = {}
    for e, ms in DET_ENSEMBLES.items():
        for fs in FSETS:
            dens[f"{e}|{fs}"] = np.mean([pct_in_fold(stat_metric if m == "stat" else dmember[(m, fs)]) for m in ms], axis=0)
    if dpick == "stat_metric":
        dpick_s = stat_metric
    else:
        m, fs, _ = dpick.split("|")
        dpick_s = dmember[(m, fs)]
    res["detection"] = {n: {**M.detection_summary(D["target"], s), "AUROC_ci95": det_ci(D, s)} for n, s in dens.items()}
    res["detection_reference"] = {f"R6 pick ({dpick})": {**M.detection_summary(D["target"], dpick_s),
                                                         "AUROC_ci95": det_ci(D, dpick_s)}}
    res["paired_det_vs_r6_pick"] = {n: det_paired(D, s, dpick_s) for n, s in dens.items()}
    deligible = [n for n in dens if res["paired_det_vs_r6_pick"][n]["verdict"] == "better"]
    dorder = lambda n: (list(DET_ENSEMBLES).index(n.split("|")[0]), FSETS.index(n.split("|")[1]))  # noqa: E731
    res["detection_decision"] = {"eligible": sorted(deligible, key=dorder),
                                 "pick": min(deligible, key=dorder) if deligible else dpick,
                                 "replaces_r6_pick": bool(deligible)}
    dtime = {(m, fs): parts[m]["detection"][fs]["timing"]["predict_ms_per_window"] for m in MODELS for fs in FSETS}
    res["detection_predict_ms_per_window"] = {f"{e}|{fs}": sum(dtime[(m, fs)] for m in ms if m != "stat")
                                              for e, ms in DET_ENSEMBLES.items() for fs in FSETS}

    (out / "results.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    write_md(res, names, out)
    print("ranking", res["ranking_decision"], "\ndetection", res["detection_decision"], flush=True)


def write_md(res, names, out):
    rd, dd = res["ranking_decision"], res["detection_decision"]
    L = ["# R6b results (RE2-OB, rank-average ensembles of R6 models)", "",
         f"- R6 picks: ranking **{res['r6_pick']['ranking']}**, detection **{res['r6_pick']['detection']}**",
         f"- ranking decision: **{rd['pick']}** (replaces R6 pick: {rd['replaces_r6_pick']}; eligible {rd['eligible']})",
         f"- detection decision: **{dd['pick']}** (replaces R6 pick: {dd['replaces_r6_pick']}; eligible {dd['eligible']})", "",
         "## Root-cause ranking", "",
         "| candidate | LOSO Avg@5 (95% CI) | vs R6 pick (95% CI) | verdict | LOSO AC@1 | rep Avg@5 | rep vs stat | predict ms/window |",
         "|---|---|---|---|---|---|---|---|"]
    for n in names:
        lo, rp, v, s = res["ranking_loso"][n], res["ranking_rep"][n], res["paired_loso_vs_r6_pick"][n], res["paired_rep_vs_stat"][n]
        L.append(f"| {n} | {fmt(lo['Avg@5'])} ({ci(lo['Avg@5_ci95'])}) | {fmt(v['mean_diff'])} ({ci(v['ci95'])}) | {v['verdict']} | "
                 f"{fmt(lo['AC@1'])} | {fmt(rp['Avg@5'])} | {s['verdict']} | {res['ranking_predict_ms_per_window'][n]:.3f} |")
    for k, lo in res["reference_loso"].items():
        rp = res["reference_rep"][k]
        L.append(f"| *{k}* | {fmt(lo['Avg@5'])} ({ci(lo['Avg@5_ci95'])}) | - | - | {fmt(lo['AC@1'])} | {fmt(rp['Avg@5'])} | - | - |")
    if "reference_r5_v4" in res:
        v4 = res["reference_r5_v4"]
        L.append(f"| *R5 V4 (R4b run, different grid)* | {fmt(v4['loso']['Avg@5'])} ({ci(v4['loso']['Avg@5_ci95'])}) | - | - | "
                 f"{fmt(v4['loso']['AC@1'])} | {fmt(v4['rep']['Avg@5'])} | - | - |")
    L += ["", "## Members: LOSO Avg@5", "", "| member | Avg@5 |", "|---|---|"]
    L += [f"| {k} | {fmt(v)} |" for k, v in res["members_loso_avg5"].items()]
    L += ["", "## Member diversity: mean per-case Spearman correlation of candidate scores (LOSO)", ""]
    for fs, d in res["member_spearman_loso"].items():
        L.append(f"- {fs}: " + "; ".join(f"{k} {v:.2f}" for k, v in d.items()))
    L += ["", "## Detection", "", "| candidate | AUROC (95% CI) | AUPRC | vs R6 pick (95% CI) | verdict | predict ms/window |",
          "|---|---|---|---|---|---|"]
    for n, d in res["detection"].items():
        v = res["paired_det_vs_r6_pick"][n]
        L.append(f"| {n} | {fmt(d['AUROC'])} ({ci(d['AUROC_ci95'])}) | {fmt(d['AUPRC'])} | {fmt(v['mean_diff'])} ({ci(v['ci95'])}) | "
                 f"{v['verdict']} | {res['detection_predict_ms_per_window'][n]:.3f} |")
    for k, d in res["detection_reference"].items():
        L.append(f"| *{k}* | {fmt(d['AUROC'])} ({ci(d['AUROC_ci95'])}) | {fmt(d['AUPRC'])} | - | - | - |")
    L += ["", "## Not tried", "", "- stacking / learned weights: 90 cases are too few without nested CV (config.yaml not_decided_here)"]
    (out / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
