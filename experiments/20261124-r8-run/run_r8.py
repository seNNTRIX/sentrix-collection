"""R8 run (experiments/20261116-log-semantic-r8/PREREG.md). Stages, in this order:

  prepare  : masked log lines per case (RE2-OB from the Zenodo release, linux-v1 from data/r8-input) and the
             window table of every case; one dictionary of masked texts per dataset.
  check    : PREREG 6 "확인 (결과 전)" on RE2-OB (message column, body format, injector logs, baseline half counts).
  tune     : RE2-OB only. D = A' + same-service MiniLM features; LOSO over the 5 root-cause services with the frozen
             RF parameters; N_min in (3, 5, 10) x M_min in (20, 50); max pooled LOSO Avg@5, ties -> smaller N_min,
             then smaller M_min. Writes tune.json. linux-v1 is not touched.
  evaluate : needs tune.json. RE2-OB LOSO dev results for A, A', B, C, D, then linux-v1 repetition 3-fold
             (training = RE2-OB 90 + linux-v1 other folds, as Method B), primary comparison D vs A Avg@5.

  python experiments/20261124-r8-run/run_r8.py prepare|check|tune|evaluate
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation import metrics as M  # noqa: E402
from evaluation.aggregate import case_rankings  # noqa: E402
from evaluation.run_linux_v1 import paired, summarize  # noqa: E402
from features import log_semantic as LS  # noqa: E402
from features.adapters import re2ob  # noqa: E402
from features.schema import CANDIDATES  # noqa: E402
from features.windows import label_re2ob, make_windows  # noqa: E402

OUT = Path(__file__).resolve().parent
WORK = ROOT / "data" / "r8-work"
RE2_ROOT = ROOT / "data" / "RE2" / "RE2-OB"
RE2_FEAT = ROOT / "data" / "features" / "re2ob-v0"
LV1 = ROOT / "data" / "r8-input" / "linux-v1-v0"
FROZEN = json.loads((ROOT / "experiments" / "20261028-re2ob-v2-freeze" / "frozen.json").read_text(encoding="utf-8"))
REL18 = FROZEN["ranking"]["features"]
RF_PARAMS = FROZEN["ranking"]["params"]
APRIME = REL18 + ["f_log_rate_lr", "f_log_err_rate_d"]
GRID = [(n, m) for n in (3, 5, 10) for m in (20, 50)]       # order = tie-break order (smaller first)
SEED = 20261116
ENCODERS = {"B": ("hash", "service"), "C": ("minilm", "all"), "D": ("minilm", "service")}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- prepare
def re2_case_logs(case):
    lg = pd.read_csv(case.path / "logs.csv", usecols=lambda c: c in {"timestamp", "container_name", "message", "error"},
                     dtype=str, keep_default_na=False)
    lg["service"] = lg["container_name"].map(re2ob.canonical)
    lg["t"] = pd.to_numeric(lg["timestamp"], errors="coerce") / 1e9
    lg = lg.dropna(subset=["t"])
    err = lg["error"].replace("", None) if "error" in lg else None
    lg = lg.assign(error=err)
    return lg[["t", "service", "message", "error"] + (["container_name"] if "container_name" in lg else [])]


def prepare_re2():
    out = WORK / "re2ob"
    (out / "logs").mkdir(parents=True, exist_ok=True)
    texts, wins, raw_info = {}, [], []
    for case in re2ob.list_cases(RE2_ROOT):
        metrics = re2ob.load_metrics(case)
        w = make_windows(case.onset, metrics["t"].min(), metrics["t"].max() + 1)
        w["label"] = w["rel"].map(label_re2ob)
        w["meta_window"] = np.arange(len(w))
        w["case_id"] = case.case_id
        wins.append(w[["case_id", "meta_window", "w_start", "w_end", "rel", "label"]])
        raw = re2_case_logs(case)
        containers = raw["container_name"].value_counts().to_dict()
        lg = LS.prepare_logs(raw[["t", "service", "message", "error"]])
        ids = np.array([texts.setdefault(t, len(texts)) for t in lg["text"]], dtype=np.int32)
        pd.DataFrame({"t": lg["t"].to_numpy(), "service": lg["service"].astype("category"), "text_id": ids}) \
            .to_parquet(out / "logs" / f"{case.case_id}.parquet")
        raw_info.append({"case_id": case.case_id, "n_raw": int(len(raw)), "n_prepared": int(len(lg)),
                         "has_message": bool(raw["message"].astype(str).str.len().gt(0).any()),
                         "json_body_share": float(raw["message"].astype(str).str.lstrip().str.startswith("{").mean()),
                         "non_candidate_containers": {k: int(v) for k, v in containers.items() if re2ob.canonical(k) is None}})
        log("re2ob", case.case_id, len(raw), len(lg), len(texts))
    pd.concat(wins, ignore_index=True).to_parquet(out / "windows.parquet")
    pd.DataFrame({"text_id": list(texts.values()), "text": list(texts.keys())}).to_parquet(out / "texts.parquet")
    (out / "raw_info.json").write_text(json.dumps(raw_info, indent=1), encoding="utf-8")


def prepare_lv1():
    """linux-v1: data/r8-input already holds mask(extract_text(...)) per line in load order; apply the rest of
    prepare_logs (candidate services, drop empty text, stable sort by t) without masking twice."""
    out = WORK / "lv1"
    (out / "logs").mkdir(parents=True, exist_ok=True)
    tx = pd.read_parquet(LV1 / "log-texts.parquet").set_index("text_id")["text"]
    for f in sorted((LV1 / "logs").glob("*.parquet")):
        d = pd.read_parquet(f).sort_values("row", kind="stable")
        d = d[d["service"].astype(str).isin(CANDIDATES)]
        d = d[tx.reindex(d["text_id"]).fillna("").to_numpy() != ""]
        d = d.sort_values("t", kind="stable")
        pd.DataFrame({"t": d["t"].to_numpy(), "service": d["service"].astype(str).astype("category"),
                      "text_id": d["text_id"].to_numpy(np.int32)}).to_parquet(out / "logs" / f.name)
    w = pd.read_parquet(LV1 / "windows.parquet")
    w[["case_id", "meta_window", "w_start", "w_end", "label"]].to_parquet(out / "windows.parquet")
    tx.reset_index().to_parquet(out / "texts.parquet")
    log("lv1 prepared", len(list((out / "logs").glob("*.parquet"))))


# ---------------------------------------------------------------- features
class FixedCache:
    """EmbeddingCache over a fixed dictionary, encoded once (same vectors as LS.EmbeddingCache)."""
    def __init__(self, encoder, texts):
        self.index = {t: i for i, t in enumerate(texts)}
        self._m = encoder(list(texts))

    def ids(self, texts):
        return np.fromiter((self.index[t] for t in texts), dtype=np.int64, count=len(texts))

    def matrix(self):
        return self._m


def caches(dataset, kinds):
    texts = pd.read_parquet(WORK / dataset / "texts.parquet").sort_values("text_id")["text"].tolist()
    out = {}
    if "hash" in kinds:
        out["hash"] = FixedCache(LS.HashingEncoder(), texts)
    if "minilm" in kinds:
        cache_file = WORK / dataset / "minilm.npy"
        if cache_file.exists():
            c = FixedCache(lambda t: np.zeros((len(t), 1)), texts)
            c._m = np.load(cache_file)
        else:
            c = FixedCache(LS.MiniLMEncoder(device="cpu"), texts)
            np.save(cache_file, c._m)
        out["minilm"] = c
    return texts, out


def features(dataset, groups, combos):
    """groups: experiment letters; combos: (n_min, m_min) list. Returns {(letter, n, m): DataFrame}."""
    kinds = {ENCODERS[g][0] for g in groups}
    texts, cs = caches(dataset, kinds)
    W = pd.read_parquet(WORK / dataset / "windows.parquet")
    res = {}
    for f in sorted((WORK / dataset / "logs").glob("*.parquet")):
        cid = f.stem
        d = pd.read_parquet(f)
        lg = pd.DataFrame({"t": d["t"].to_numpy(), "service": d["service"].astype(str).to_numpy(),
                           "text": np.array(texts, dtype=object)[d["text_id"].to_numpy()]})
        w = W[W["case_id"] == cid].reset_index(drop=True)
        for g in groups:
            kind, scope = ENCODERS[g]
            for n, m in combos:
                fe = LS.semantic_features(lg, w, cs[kind], scope=scope, prefix=LS.PREFIXES[g], n_min=n, m_min=m, seed=SEED)
                fe = fe.merge(w[["w_start", "meta_window"]], on="w_start").drop(columns="w_start")
                fe["meta_case_id"] = cid
                res.setdefault((g, n, m), []).append(fe.rename(columns={"service": "meta_candidate"}))
        log(dataset, cid)
    return {k: pd.concat(v, ignore_index=True) for k, v in res.items()}


def attach(R, fe):
    return R.merge(fe, on=["meta_case_id", "meta_window", "meta_candidate"], how="left")


# ---------------------------------------------------------------- models
def fit_score(train, test, cols):
    rf = RandomForestClassifier(n_jobs=4, **RF_PARAMS)
    rf.fit(train[cols].astype(float).fillna(0.0).to_numpy(), train["target"])
    return rf.predict_proba(test[cols].astype(float).fillna(0.0).to_numpy())[:, 1]


def loso_rows(R, cols):
    R = R.copy()
    R["s"] = np.nan
    for svc in sorted(R["meta_root_cause"].unique()):
        te = R["meta_root_cause"] == svc
        R.loc[te, "s"] = fit_score(R[~te], R[te], cols)
    return list(case_rankings(R, "s"))


def cols_for(letter):
    if letter == "A":
        return REL18
    if letter == "A'":
        return APRIME
    p = LS.PREFIXES[letter]
    return APRIME + [f"{p}_dmean", f"{p}_dp90", f"{p}_valid"]


# ---------------------------------------------------------------- stages
def stage_check():
    info = json.loads((WORK / "re2ob" / "raw_info.json").read_text(encoding="utf-8"))
    W = pd.read_parquet(WORK / "re2ob" / "windows.parquet")
    halves = []
    for f in sorted((WORK / "re2ob" / "logs").glob("*.parquet")):
        d = pd.read_parquet(f)
        w = W[W["case_id"] == f.stem]
        a, mid, dist = LS.split_baseline(w)
        b = float(w.loc[w["label"] == "baseline_stats", "w_end"].max())
        for s in CANDIDATES:
            x = d[d["service"].astype(str) == s]["t"]
            halves.append({"case_id": f.stem, "service": s, "ref_first_half": int(((x >= a) & (x < mid)).sum()),
                           "second_half": int(((x >= mid) & (x < b)).sum()), "dist_windows": int(len(dist))})
    H = pd.DataFrame(halves)
    out = {"n_cases": len(info), "all_have_message": all(i["has_message"] for i in info),
           "json_body_share_max": max(i["json_body_share"] for i in info),
           "non_candidate_containers": sorted({k for i in info for k in i["non_candidate_containers"]}),
           "ref_first_half_median_by_service": H.groupby("service")["ref_first_half"].median().to_dict(),
           "service_cases_with_ref_lt_20": H[H["ref_first_half"] < 20].groupby("service").size().to_dict(),
           "service_cases_with_ref_lt_50": H[H["ref_first_half"] < 50].groupby("service").size().to_dict(),
           "dist_windows": sorted(H["dist_windows"].unique().tolist())}
    (OUT / "re2ob-check.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


def stage_tune():
    R2 = pd.read_parquet(RE2_FEAT / "ranking.parquet")
    fe = features("re2ob", ["D"], GRID)
    results = []
    for n, m in GRID:
        X = attach(R2, fe[("D", n, m)])
        rows = loso_rows(X, cols_for("D"))
        s = M.ranking_summary([(sc, i) for _, sc, i, _ in rows])
        valid = float(X["f_lsem_valid"].fillna(0).mean())
        results.append({"N_min": n, "M_min": m, "loso_avg5": s["Avg@5"], "loso": s, "valid_share": valid})
        log("tune", n, m, s["Avg@5"], valid)
    best = None
    for r in results:                        # strict > keeps the earlier (smaller) setting on ties
        if best is None or r["loso_avg5"] > best["loso_avg5"] + 1e-12:
            best = r
    out = {"criterion": "RE2-OB D (A' + same-service MiniLM) LOSO over 5 root-cause services, pooled Avg@5, "
                        "frozen RF params; ties -> smaller N_min, then smaller M_min",
           "grid": results, "chosen": {"N_min": best["N_min"], "M_min": best["M_min"]}}
    (OUT / "tune.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out["chosen"]), [(r["N_min"], r["M_min"], round(r["loso_avg5"], 4)) for r in results])


def stage_evaluate():
    chosen = json.loads((OUT / "tune.json").read_text(encoding="utf-8"))["chosen"]
    n, m = chosen["N_min"], chosen["M_min"]
    letters = ["A", "A'", "B", "C", "D"]
    R2 = pd.read_parquet(RE2_FEAT / "ranking.parquet")
    f2 = features("re2ob", ["B", "C", "D"], [(n, m)])
    for g in "BCD":
        R2 = attach(R2, f2[(g, n, m)])
    dev = {}
    for L in letters:
        dev[L] = M.ranking_summary([(s, i) for _, s, i, _ in loso_rows(R2, cols_for(L))])
        log("re2ob dev", L, dev[L]["Avg@5"])
    validity = {g: {"re2ob_rows_valid_share": float(R2[f"{LS.PREFIXES[g]}_valid"].fillna(0).mean())} for g in "BCD"}

    R = pd.read_parquet(LV1 / "ranking.parquet")
    f1 = features("lv1", ["B", "C", "D"], [(n, m)])
    for g in "BCD":
        R = attach(R, f1[(g, n, m)])
        validity[g]["lv1_rows_valid_share"] = float(R[f"{LS.PREFIXES[g]}_valid"].fillna(0).mean())
    folds = sorted(R["meta_fold"].unique())
    for L in letters:
        R[f"s_{L}"] = np.nan
    for f in folds:
        te = R["meta_fold"] == f
        train = pd.concat([R2, R[~te]], ignore_index=True)
        for L in letters:
            R.loc[te, f"s_{L}"] = fit_score(train, R[te], cols_for(L))
        log("lv1 fold", f)
    rows = {L: list(case_rankings(R, f"s_{L}")) for L in letters}
    summ = {L: summarize(rows[L]) for L in letters}
    comp = {"primary_D_minus_A": paired(rows["D"], rows["A"]),
            "D_minus_A'": paired(rows["D"], rows["A'"]), "D_minus_B": paired(rows["D"], rows["B"]),
            "D_minus_C": paired(rows["D"], rows["C"]), "A'_minus_A": paired(rows["A'"], rows["A"])}
    rank = {L: {pc["case_id"]: pc["rank"] for pc in summ[L]["per_case"]} for L in letters}
    meta = {pc["case_id"]: pc for pc in summ["A"]["per_case"]}
    per_case = [{"case_id": c, "fault": meta[c]["fault"], "root_cause": meta[c]["root_cause"],
                 **{f"rank_{L}": rank[L][c] for L in letters}} for c in sorted(meta)]
    res = {"chosen": chosen, "re2ob_dev_loso": dev, "validity": validity,
           "lv1": {L: {k: v for k, v in summ[L].items() if k != "per_case"} for L in letters},
           "comparisons": comp, "per_case": per_case,
           "notes": ["RE2-OB dev numbers use the data the N_min/M_min were chosen on (optimistic).",
                     "pod-checkoutservice cases: one repetition was viewed before PREREG (PREREG 2); flagged in per_case."]}
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"lv1": {L: {k: res["lv1"][L][k] for k in ("AC@1", "AC@3", "Avg@5", "MRR", "n_cases")} for L in letters},
                      "comparisons": comp}, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["prepare", "check", "tune", "evaluate"])
    a = ap.parse_args()
    if a.stage == "prepare":
        prepare_re2()
        prepare_lv1()
    elif a.stage == "check":
        stage_check()
    elif a.stage == "tune":
        stage_tune()
    else:
        stage_evaluate()


if __name__ == "__main__":
    main()
