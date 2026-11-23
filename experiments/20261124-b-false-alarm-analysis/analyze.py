"""Post-hoc, supplementary (사후·보조): why did 26 of 69 linux-v1 control runs alarm under Method B?

Does not change any reported number, model, threshold or rule. Retrains the Method B fold detectors exactly as
evaluation/run_linux_v1.py method_b, checks that thresholds and per-run alarms reproduce the recorded results,
then describes (1) which control runs alarmed (pair fault type, repetition, collection time, alarm timing) and
(2) which features pushed the score up in the alarming windows (LightGBM pred_contrib = TreeSHAP, log-odds).

  .venv/bin/python experiments/20261124-b-false-alarm-analysis/analyze.py <recorded method-B results.json>
"""
import json
from pathlib import Path
import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.run_linux_v1 import THRESHOLD_Q, V2, run_alarms  # noqa: E402

OUT = Path(__file__).resolve().parent
LV1 = ROOT / "data" / "r8-input" / "linux-v1-v0"
RE2 = ROOT / "data" / "features" / "re2ob-v0"


def group_of(base):
    return {"cm": "지표", "ct": "trace", "log": "로그", "nbr": "이웃"}[base.split("_")[1]]


def main(recorded_path):
    rec = json.loads(Path(recorded_path).read_text())["method_b"]
    v2 = json.loads((V2 / "frozen.json").read_text())
    dp, dcols = dict(v2["detection"]["params"]), v2["detection"]["features"]
    D2 = pd.read_parquet(RE2 / "detection.parquet")
    D = pd.read_parquet(LV1 / "detection.parquet")
    meta = pd.read_parquet(LV1 / "cases-meta.parquet").set_index("case_id")
    folds = sorted(D["meta_fold"].unique())
    D["s"], D["thr"] = np.nan, np.nan
    contrib = np.full((len(D), len(dcols) + 1), np.nan)
    checks = []
    for f in folds:
        trD = pd.concat([D2[dcols + ["target"]], D.loc[D["meta_fold"] != f, dcols + ["target"]]], ignore_index=True)
        det = lgb.LGBMClassifier(objective="binary", **dp).fit(trD[dcols], trD["target"])
        thr = float(np.quantile(det.predict_proba(trD.loc[trD["target"] == 0, dcols])[:, 1], THRESHOLD_Q))
        rthr = next(x["threshold"] for x in rec["folds"] if x["fold"] == f)
        checks.append({"fold": int(f), "threshold": thr, "recorded": rthr, "match": abs(thr - rthr) < 1e-12})
        te = (D["meta_fold"] == f).to_numpy()
        D.loc[te, "s"] = det.predict_proba(D.loc[te, dcols])[:, 1]
        D.loc[te, "thr"] = thr
        contrib[te] = det.booster_.predict(D.loc[te, dcols], pred_contrib=True)
    runs = pd.concat([run_alarms(D[D["meta_fold"] == f], D.loc[D["meta_fold"] == f, "s"], D.loc[D["meta_fold"] == f, "thr"].iloc[0])
                      for f in folds], ignore_index=True)
    recruns = pd.DataFrame(rec["detection"]["runs"]).set_index("case_id")
    same = (runs.set_index("case_id")["alarm"] == recruns.loc[runs["case_id"], "alarm"]).all()
    checks.append({"per_run_alarms_match_recorded": bool(same), "n_runs": int(len(runs))})
    assert all(c.get("match", True) for c in checks[:-1]) and same, checks

    # ---------------- (1) which control runs
    C = runs[runs["kind"] == "control"].copy()
    C["repetition"] = [int(meta.loc[c, "repetition"]) for c in C["case_id"]]
    C["start_kst"] = pd.to_datetime([meta.loc[c, "run_start"] for c in C["case_id"]], unit="s", utc=True).tz_convert("Asia/Seoul")
    C["date"], C["hour"] = C["start_kst"].dt.strftime("%m-%d"), C["start_kst"].dt.hour
    C["night"] = C["hour"].isin(range(0, 7))
    by_fault = C.groupby("fault")["alarm"].agg(["sum", "count"])
    by_rep = C.groupby("repetition")["alarm"].agg(["sum", "count"])
    by_date = C.groupby("date")["alarm"].agg(["sum", "count"])
    def fisher(mask):
        a = int(C.loc[mask, "alarm"].sum()); b = int(mask.sum()) - a
        c = int(C.loc[~mask, "alarm"].sum()); d = int((~mask).sum()) - c
        return float(fisher_exact([[a, b], [c, d]])[1])
    # order of runs in the campaign (time sorted) vs alarm
    C = C.sort_values("start_kst").reset_index(drop=True)
    first_half = C.index < len(C) / 2

    # score distribution before the sham period: do alarming control runs already score high in 'normal' windows?
    W = D[D["meta_kind"] == "control"].copy()
    W["above"] = W["s"] > W["thr"]
    alarm_ids = set(C.loc[C["alarm"], "case_id"])
    W["run_alarm"] = W["meta_case_id"].isin(alarm_ids)
    pre = W[W["meta_label"] == "normal"].groupby("run_alarm")["above"].mean()
    sham = W[W["meta_label"] == "sham_active"].groupby("run_alarm")["above"].mean()
    rec_ = W[W["meta_label"] == "recovered"].groupby("run_alarm")["above"].mean()

    # ---------------- (2) which features push the score up
    names = dcols + ["bias"]
    idx = D.index.to_numpy()
    ctl_sham = (D["meta_kind"] == "control") & (D["meta_label"] == "sham_active")
    alarm_w = (ctl_sham & (D["s"] > D["thr"])).to_numpy()
    quiet_w = (ctl_sham & (D["s"] <= D["thr"])).to_numpy()
    fault_w = ((D["meta_kind"] == "fault") & (D["meta_label"] == "fault_active") & (D["s"] > D["thr"])).to_numpy()
    def top(mask, k=12):
        m = pd.Series(np.nanmean(contrib[mask], axis=0), index=names).drop("bias")
        return m
    A, Q, F = top(alarm_w), top(quiet_w), top(fault_w)
    diff = (A - Q).sort_values(ascending=False)
    base = lambda s: s.groupby(lambda n: n.rsplit("__", 1)[0]).sum()
    diff_base = base(A - Q).sort_values(ascending=False)
    groups = (A - Q).groupby(lambda n: group_of(n.rsplit("__", 1)[0])).sum().sort_values(ascending=False)
    # raw values of the top features: alarming vs quiet control windows vs fault windows
    raw = {}
    for n in diff.index[:8]:
        raw[n] = {"control_alarm_median": float(np.nanmedian(D.loc[alarm_w, n])), "control_quiet_median": float(np.nanmedian(D.loc[quiet_w, n])),
                  "fault_alarm_median": float(np.nanmedian(D.loc[fault_w, n])),
                  "p_mwu": float(mannwhitneyu(D.loc[alarm_w, n].dropna(), D.loc[quiet_w, n].dropna()).pvalue)}
    # per alarming run: the single top feature in its first alarm window
    first_top = []
    for cid in C.loc[C["alarm"], "case_id"]:
        g = D[(D["meta_case_id"] == cid) & (D["meta_label"] == "sham_active") & (D["s"] > D["thr"])].sort_values("meta_rel")
        row = contrib[D.index.get_indexer(g.index[:1])][0][:-1]
        first_top.append({"case_id": cid, "rel": float(g["meta_rel"].iloc[0]), "score": float(g["s"].iloc[0]),
                          "top_feature": dcols[int(np.argmax(row))], "top_contrib": float(row.max())})
    ft = pd.DataFrame(first_top)

    out = {"label": "post-hoc supplementary analysis (사후·보조); reported Method B numbers unchanged",
           "checks": checks,
           "control_alarm_by_pair_fault": {k: [int(v["sum"]), int(v["count"])] for k, v in by_fault.iterrows()},
           "fisher_pod_vs_rest_p": fisher(C["fault"] == "pod_failure"),
           "control_alarm_by_repetition": {int(k): [int(v["sum"]), int(v["count"])] for k, v in by_rep.iterrows()},
           "control_alarm_by_date_kst": {k: [int(v["sum"]), int(v["count"])] for k, v in by_date.iterrows()},
           "night_00_07_vs_day_fisher_p": fisher(C["night"]), "night_alarm": [int(C.loc[C["night"], "alarm"].sum()), int(C["night"].sum())],
           "campaign_first_half_alarm": [int(C.loc[first_half, "alarm"].sum()), int(first_half.sum())],
           "campaign_second_half_alarm": [int(C.loc[~first_half, "alarm"].sum()), int((~first_half).sum())],
           "alarm_rel_s_of_alarming_controls": C.loc[C["alarm"], "alarm_rel_s"].describe().to_dict(),
           "share_windows_above_threshold": {"normal_before_sham": pre.to_dict(), "sham_active": sham.to_dict(), "recovered": rec_.to_dict()},
           "shap_alarm_minus_quiet_top_features": diff.head(12).round(4).to_dict(),
           "shap_alarm_minus_quiet_by_base_feature": diff_base.head(10).round(4).to_dict(),
           "shap_alarm_minus_quiet_by_source": groups.round(4).to_dict(),
           "shap_fault_alarm_top_features": F.sort_values(ascending=False).head(10).round(4).to_dict(),
           "top_feature_raw_values": raw,
           "first_alarm_window_top_feature_counts": ft["top_feature"].value_counts().to_dict(),
           "n_windows": {"control_sham_alarm": int(alarm_w.sum()), "control_sham_quiet": int(quiet_w.sum()), "fault_active_alarm": int(fault_w.sum())},
           "control_runs": C.assign(start_kst=C["start_kst"].astype(str)).drop(columns=["night"]).to_dict(orient="records")}
    (OUT / "results.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "control_runs"}, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
