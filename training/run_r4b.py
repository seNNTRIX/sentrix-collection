"""R4b: unseen root-cause service (pre-registered in experiments/20261027-re2ob-r4b/config.yaml).

  python -m training.run_r4b --out experiments/20261027-re2ob-r4b

Primary criterion: leave-one-root-cause-service-out (LOSO) Avg@5 with hyperparameters chosen by
inner LOSO over the training services. Repetition CV (as in R4) is a secondary condition.
The decision rule in config.yaml is applied mechanically in decide().
"""
import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.aggregate import HORIZON, case_rankings
from evaluation.run_baselines import TRACED, add_scores
from training import lgbm
from training.run_r4 import cols_for, fmt, paired_diff, summarize

CORE = ("f_cm_", "f_ct_")
IDENTITY_LIKE = ("_zero_iqr", "_n", "f_cm_cpu_limit_ratio_mean", "f_cm_mem_limit_ratio_mean",
                 "f_ct_mask", "f_ct_in_err", "f_ct_out_err")
MONO_UP = ("f_cm_cpu_cores_", "f_cm_cpu_limit_ratio_", "f_cm_mem_limit_ratio_", "f_cm_net_drop_pkts_",
           "f_ct_in_err_d", "f_ct_in_p50_lr", "f_ct_in_p90_lr", "f_ct_in_edge_p90_lr")
PREFERENCE = ["V2_rel", "V3_rel_mono", "V1_core", "V4_hybrid"]
NONINFERIOR_MARGIN = -0.02


def rel_cols(df):
    def identity_like(c):
        return c.endswith(("_zero_iqr", "_n")) or c in IDENTITY_LIKE
    return [c for c in cols_for(df, CORE) if not identity_like(c)]


def monotone(cols):
    return [1 if c.startswith(MONO_UP) else 0 for c in cols]


def hybrid(a_rows, b_rows):
    """Per case: -(rank in a + rank in b) / 2, average ranks for ties, NaN ranked last."""
    b = {cid: s for cid, s, _, _ in b_rows}
    out = []
    for cid, s, i, meta in a_rows:
        ra = pd.Series(s).rank(ascending=False, method="average", na_option="bottom").to_numpy()
        rb = pd.Series(b[cid]).rank(ascending=False, method="average", na_option="bottom").to_numpy()
        out.append((cid, -(ra + rb) / 2, i, meta))
    return out


def fingerprint_probe(df, cols, candidates):
    """Accuracy of predicting the candidate's service name from its features (repetition 3-fold)."""
    d = df[(df["meta_rel"] >= HORIZON[0]) & (df["meta_rel"] < HORIZON[1]) & df["meta_candidate"].isin(candidates)]
    correct = 0
    for test in sorted(d["meta_fold"].unique()):
        tr, te = d[d["meta_fold"] != test], d[d["meta_fold"] == test]
        m = lgb.LGBMClassifier(objective="multiclass", num_leaves=15, n_estimators=100, **lgbm.COMMON)
        m.fit(tr[cols], tr["meta_candidate"])
        correct += int((m.predict(te[cols]) == te["meta_candidate"].to_numpy()).sum())
    return {"accuracy": correct / len(d), "chance": 1 / len(candidates), "n_rows": len(d)}


def decide(res):
    loso, rep = res["paired_loso_vs_stat"], res["paired_rep_vs_stat"]
    superior = [v for v in PREFERENCE if loso[v]["ci95"][0] > 0 and rep[v]["verdict"] != "worse"]
    noninf = [v for v in PREFERENCE if loso[v]["ci95"][0] > NONINFERIOR_MARGIN and rep[v]["verdict"] == "better"]
    for tier, eligible in (("superior", superior), ("non-inferior", noninf)):
        if eligible:
            pick = eligible[0]
            for v in eligible[1:]:
                if res["paired_loso_between"][f"{v} - {pick}"]["verdict"] == "better":
                    pick = v
            return {"tier": tier, "eligible": eligible, "primary": pick}
    best = max(PREFERENCE, key=lambda v: res["ranking_loso"][v]["Avg@5"])
    return {"tier": "none", "eligible": [], "primary": "stat_combined", "secondary": best}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    R = pd.read_parquet(Path(args.features) / "ranking.parquet")
    res = {"features": {}, "ranking_loso": {}, "ranking_rep": {}, "loso_by_service": {}, "chosen_loso": {},
           "chosen_rep": {}, "paired_loso_vs_stat": {}, "paired_rep_vs_stat": {}, "paired_loso_between": {}}

    def checkpoint():
        (out / "results.partial.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")

    core, rel = cols_for(R, CORE), rel_cols(R)
    res["features"] = {"core": core, "rel": rel, "monotone_up": [c for c, m in zip(rel, monotone(rel)) if m]}
    stat_rows = list(case_rankings(add_scores(R), "s_stat_combined"))

    # fingerprint probe (diagnostic only)
    res["fingerprint"] = {f"{b} {cn}": fingerprint_probe(R, cols, cands)
                          for b, cols in (("core", core), ("rel", rel))
                          for cn, cands in (("11 candidates", list(R["meta_candidate"].unique())), ("7 traced", TRACED))}
    print("fingerprint", {k: round(v["accuracy"], 3) for k, v in res["fingerprint"].items()}, flush=True)
    checkpoint()

    specs = {"V1_core": (core, None), "V2_rel": (rel, None),
             "V3_rel_mono": (rel, {"monotone_constraints": monotone(rel)})}
    loso_rows, rep_rows = {}, {}
    for name, (cols, extra) in specs.items():
        loso_rows[name], res["chosen_loso"][name] = lgbm.loso_ranker(R, cols, extra=extra)
        rep_rows[name], res["chosen_rep"][name], _, _ = lgbm.cv_ranker(R, cols, extra=extra)
        print(name, "loso", round(M.ranking_summary([(s, i) for _, s, i, _ in loso_rows[name]])["Avg@5"], 3),
              "rep", round(M.ranking_summary([(s, i) for _, s, i, _ in rep_rows[name]])["Avg@5"], 3), flush=True)
        checkpoint()
    loso_rows["V4_hybrid"] = hybrid(loso_rows["V2_rel"], stat_rows)
    rep_rows["V4_hybrid"] = hybrid(rep_rows["V2_rel"], stat_rows)

    res["ranking_loso"]["stat_combined"] = summarize(stat_rows)
    res["ranking_rep"]["stat_combined"] = res["ranking_loso"]["stat_combined"]
    for v in PREFERENCE:
        res["ranking_loso"][v] = summarize(loso_rows[v])
        res["ranking_rep"][v] = summarize(rep_rows[v])
        res["paired_loso_vs_stat"][v] = paired_diff(loso_rows[v], stat_rows)
        res["paired_rep_vs_stat"][v] = paired_diff(rep_rows[v], stat_rows)
    for a in PREFERENCE:
        for b in PREFERENCE:
            if a != b:
                res["paired_loso_between"][f"{a} - {b}"] = paired_diff(loso_rows[a], loso_rows[b])
    services = sorted(R["meta_root_cause"].unique())
    for svc in services:
        res["loso_by_service"][svc] = {
            v: M.ranking_summary([(s, i) for _, s, i, meta in rows if meta["root_cause"] == svc])
            for v, rows in [("stat_combined", stat_rows)] + [(v, loso_rows[v]) for v in PREFERENCE]}
    res["decision"] = decide(res)
    (out / "results.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    (out / "results.partial.json").unlink(missing_ok=True)

    names = ["stat_combined"] + PREFERENCE
    L = ["# R4b results (RE2-OB, unseen root-cause service)", "",
         f"features: core {len(core)}, rel {len(rel)}; monotone +1 on {len(res['features']['monotone_up'])} rel features", "",
         "## Fingerprint probe (predict the candidate's service from its features; diagnostic only)", "",
         "| features | candidates | accuracy | chance |", "|---|---|---|---|"]
    for k, v in res["fingerprint"].items():
        b, cn = k.split(" ", 1)
        L.append(f"| {b} | {cn} | {fmt(v['accuracy'])} | {fmt(v['chance'])} |")
    for title, key, pkey in (("LOSO (primary; params by inner LOSO)", "ranking_loso", "paired_loso_vs_stat"),
                             ("Repetition 3-fold CV (secondary)", "ranking_rep", "paired_rep_vs_stat")):
        L += ["", f"## {title}", "", "| method | AC@1 | AC@3 | Avg@5 (95% CI) | MRR | diff vs stat (95% CI) | verdict |",
              "|---|---|---|---|---|---|---|"]
        for n in names:
            s, ci = res[key][n], res[key][n]["Avg@5_ci95"]
            p = res[pkey].get(n)
            pd_ = f"{fmt(p['mean_diff'])} ({fmt(p['ci95'][0])} – {fmt(p['ci95'][1])})" if p else "-"
            L.append(f"| {n} | {fmt(s['AC@1'])} | {fmt(s['AC@3'])} | {fmt(s['Avg@5'])} ({fmt(ci[0])}–{fmt(ci[1])}) "
                     f"| {fmt(s['MRR'])} | {pd_} | {p['verdict'] if p else '-'} |")
    L += ["", "## LOSO Avg@5 by held-out root-cause service", "", "| held-out | " + " | ".join(names) + " |",
          "|---|" + "---|" * len(names)]
    for svc in services:
        L.append(f"| {svc} | " + " | ".join(fmt(res["loso_by_service"][svc][n]["Avg@5"]) for n in names) + " |")
    faults = sorted(res["ranking_loso"]["V1_core"]["by_fault"])
    L += ["", "## LOSO Avg@5 by fault", "", "| method | " + " | ".join(faults) + " |", "|---|" + "---|" * len(faults)]
    for n in names:
        L.append(f"| {n} | " + " | ".join(fmt(res["ranking_loso"][n]["by_fault"].get(f)) for f in faults) + " |")
    L += ["", "## LOSO paired differences between variants", "", "| comparison | mean diff | 95% CI | verdict |", "|---|---|---|---|"]
    for i, a in enumerate(PREFERENCE):
        for b in PREFERENCE[i + 1:]:
            v = res["paired_loso_between"][f"{a} - {b}"]
            L.append(f"| {a} - {b} | {fmt(v['mean_diff'])} | {fmt(v['ci95'][0])} – {fmt(v['ci95'][1])} | {v['verdict']} |")
    L += ["", "## Chosen hyperparameters (LOSO, per held-out service)", ""]
    for n, ch in res["chosen_loso"].items():
        L.append(f"- {n}: " + "; ".join(f"{svc}: {c['params']}" for svc, c in ch.items()))
    d = res["decision"]
    L += ["", "## Decision (pre-registered rule)", "", f"- tier: {d['tier']}", f"- eligible: {d['eligible']}",
          f"- primary linux-v1 ranking method: **{d['primary']}**"] + ([f"- secondary: {d['secondary']}"] if "secondary" in d else [])
    (out / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("decision", d, flush=True)


if __name__ == "__main__":
    main()
