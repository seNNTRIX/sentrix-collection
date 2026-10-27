"""R7: raw-value ablation (pre-registered in experiments/20261027-re2ob-r7-raw-ablation/config.yaml).

  .venv-r6/Scripts/python -m training.run_r7 --out experiments/20261027-re2ob-r7-raw-ablation --check
  .venv-r6/Scripts/python -m training.run_r7 --out ... --model rf --fset raw18
  .venv-r6/Scripts/python -m training.run_r7 --out ... --detection
  .venv-r6/Scripts/python -m training.run_r7 --out ... --combine

Training and evaluation use training/run_r6.py unchanged (same grids, seeds, inner selection).
rel18 / core35 ranking rows are read from the R6 parts. Every mode runs the consistency check first.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation import metrics as M
from evaluation.run_baselines import METRIC_SIGNALS
from training.freeze_r5 import rel_detection_cols
from training.run_r4 import fmt, paired_diff, summarize
from training.run_r4b import rel_cols
from training.run_r6 import ci, det_ci, det_paired, outer_det, outer_rank, rows_in, rows_out

RAW18 = ([f"f_raw_{s}_{a}" for s in METRIC_SIGNALS for a in ("mean", "max")]
         + ["f_raw_in_rate", "f_raw_in_err", "f_raw_in_p50", "f_raw_in_p90", "f_raw_out_p90", "f_raw_in_edge_p90"])
KEYS = ["meta_case_id", "meta_window", "meta_candidate"]


def load(args):
    R = pd.read_parquet(Path(args.features) / "ranking.parquet")
    D = pd.read_parquet(Path(args.features) / "detection.parquet")
    raw = pd.read_parquet(Path(args.raw) / "raw_nodes.parquet")
    R7 = R.merge(raw[KEYS + RAW18 + ["chk_in_p90_lr"]], on=KEYS, how="left", validate="one_to_one")
    rows = raw[raw["meta_label"].isin(["normal", "fault_active"])]
    with np.errstate(all="ignore"):
        agg = rows.groupby(["meta_case_id", "meta_window"])[RAW18].agg(["max", "mean"])
    agg.columns = [f"{c}__{s}" for c, s in agg.columns]
    D7 = D.merge(agg.reset_index(), on=["meta_case_id", "meta_window"], how="left", validate="one_to_one")
    return R, R7, D7


def check(R7, D7):
    """Pre-registered consistency check; raises on any mismatch."""
    def same(a, b, tol=1e-9):
        x, y = R7[a].to_numpy(float), R7[b].to_numpy(float)
        nan_ok = bool((np.isnan(x) == np.isnan(y)).all())
        both = ~np.isnan(x) & ~np.isnan(y)
        return nan_ok and (not both.any() or float(np.max(np.abs(x[both] - y[both]))) < tol)
    pairs = [("chk_in_p90_lr", "f_ct_in_p90_lr"), ("f_raw_in_err", "f_ct_in_err")]
    pairs += [(f"f_raw_{s}_{a}", f"f_opt_{s}_{a}") for s in METRIC_SIGNALS for a in ("mean", "max")]
    bad = [p for p in pairs if not same(*p)]
    joined = int(R7["f_raw_in_rate"].notna().sum() + R7["f_raw_in_rate"].isna().sum())
    det_missing = int(D7[[c for c in D7.columns if c.startswith("f_raw_")]].isna().all(axis=1).sum())
    res = {"ranking_rows": len(R7), "joined": joined, "mismatched_pairs": bad, "checked_pairs": len(pairs),
           "detection_rows": len(D7), "detection_rows_without_raw": det_missing}
    if bad or joined != len(R7) or det_missing:
        raise SystemExit(f"consistency check FAILED: {res}")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--raw", default="data/features/re2ob-r7-raw")
    ap.add_argument("--r6", default="experiments/20261027-re2ob-r6-models")
    ap.add_argument("--out", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--model", choices=["rf", "lgbm"])
    g.add_argument("--detection", action="store_true")
    g.add_argument("--combine", action="store_true")
    ap.add_argument("--fset", choices=["raw18", "raw18+rel18"])
    args = ap.parse_args()
    out = Path(args.out)
    (out / "parts").mkdir(parents=True, exist_ok=True)
    R, R7, D7 = load(args)
    chk = check(R7, D7)
    if args.check:
        (out / "consistency-check.json").write_text(json.dumps(chk, indent=2), encoding="utf-8")
        print("consistency check passed", chk, flush=True)
        return
    rel = rel_cols(R)
    fsets = {"raw18": RAW18, "raw18+rel18": RAW18 + rel}
    if args.model:
        res = {}
        for split, key in (("loso", "meta_root_cause"), ("rep", "meta_fold")):
            rows, chosen, timing = outer_rank(R7, fsets[args.fset], args.model, key)
            res[split] = {"rows": rows_out(rows), "chosen": chosen, "timing": timing}
            print(args.model, args.fset, split, "done", flush=True)
        (out / "parts" / f"{args.model}__{args.fset}.json").write_text(json.dumps(res), encoding="utf-8")
        return
    raw_det = [f"{c}__{s}" for c in RAW18 for s in ("max", "mean")]
    rel_det = rel_detection_cols(D7, rel)
    if args.detection:
        res = {}
        for name, cols in (("raw18", raw_det), ("rel18", rel_det)):
            scores, chosen, timing = outer_det(D7, cols, "lgbm")
            res[name] = {"scores": [float(x) for x in scores], "chosen": chosen, "timing": timing}
            print("detection", name, "done", flush=True)
        (out / "parts" / "detection_lgbm.json").write_text(json.dumps(res), encoding="utf-8")
        return
    combine(out, Path(args.r6), D7)


def combine(out, r6, D7):
    r6parts = {m: json.loads((r6 / "parts" / f"{m}.json").read_text(encoding="utf-8")) for m in ("rf", "lgbm")}
    rows = {}
    for m in ("rf", "lgbm"):
        for split in ("loso", "rep"):
            rows[(m, "rel18", split)] = rows_in(r6parts[m]["ranking"][f"rel|{split}"]["rows"])
            rows[(m, "core35", split)] = rows_in(r6parts[m]["ranking"][f"core|{split}"]["rows"])
            for fs in ("raw18", "raw18+rel18"):
                p = json.loads((out / "parts" / f"{m}__{fs}.json").read_text(encoding="utf-8"))
                rows[(m, fs, split)] = rows_in(p[split]["rows"])
    res = {"ranking": {f"{m}|{fs}|{split}": summarize(r) for (m, fs, split), r in rows.items()}, "paired": {}}
    for m in ("rf", "lgbm"):
        for split in ("loso", "rep"):
            res["paired"][f"{m}|{split}|rel18 - raw18"] = paired_diff(rows[(m, "rel18", split)], rows[(m, "raw18", split)])
            res["paired"][f"{m}|{split}|rel18 - raw18+rel18"] = paired_diff(rows[(m, "rel18", split)], rows[(m, "raw18+rel18", split)])
            res["paired"][f"{m}|{split}|core35 - raw18"] = paired_diff(rows[(m, "core35", split)], rows[(m, "raw18", split)])
    det = json.loads((out / "parts" / "detection_lgbm.json").read_text(encoding="utf-8"))
    ds = {k: np.array(v["scores"], dtype=float) for k, v in det.items()}
    res["detection"] = {k: {**M.detection_summary(D7["target"], s), "AUROC_ci95": det_ci(D7, s)} for k, s in ds.items()}
    res["paired_detection"] = {"rel18 - raw18": det_paired(D7, ds["rel18"], ds["raw18"])}
    services = sorted({meta["root_cause"] for *_, meta in rows[("rf", "rel18", "loso")]})
    res["loso_by_service"] = {f"{m}|{fs}": {s: M.ranking_summary([(sc, i) for _, sc, i, meta in rows[(m, fs, "loso")]
                                                                  if meta["root_cause"] == s])["Avg@5"] for s in services}
                              for m in ("rf", "lgbm") for fs in ("raw18", "core35", "rel18", "raw18+rel18")}
    v = res["paired"]["rf|loso|rel18 - raw18"]
    res["Q1_answer"] = {"better": "SentriX processing helps RF (LOSO)", "worse": "raw values better than SentriX features for RF (LOSO)",
                        "no difference": "no difference between raw and SentriX features for RF (LOSO)"}[v["verdict"]]
    (out / "results.json").write_text(json.dumps(res, indent=2, default=float), encoding="utf-8")
    write_md(res, services, out)
    print("Q1:", res["Q1_answer"], v, flush=True)


def write_md(res, services, out):
    r, p = res["ranking"], res["paired"]
    L = ["# R7 results (RE2-OB, raw-value ablation)", "", f"- Q1 (pre-registered primary): **{res['Q1_answer']}**", "",
         "## Ablation (Random Forest = SentriX base model)", "",
         "| step | features | LOSO Avg@5 (95% CI) | LOSO AC@1 | rep Avg@5 (95% CI) |", "|---|---|---|---|---|"]
    steps = [("base model + raw values", "raw18"), ("+ baseline normalisation, identity features kept", "core35"),
             ("+ identity features removed = SentriX-model", "rel18"), ("(alt) raw values added back", "raw18+rel18")]
    for m in ("rf", "lgbm"):
        if m == "lgbm":
            L += ["", "## Same ablation with LightGBM (secondary)", "",
                  "| step | features | LOSO Avg@5 (95% CI) | LOSO AC@1 | rep Avg@5 (95% CI) |", "|---|---|---|---|---|"]
        for label, fs in steps:
            lo, rp = r[f"{m}|{fs}|loso"], r[f"{m}|{fs}|rep"]
            L.append(f"| {label} | {fs} | {fmt(lo['Avg@5'])} ({ci(lo['Avg@5_ci95'])}) | {fmt(lo['AC@1'])} | "
                     f"{fmt(rp['Avg@5'])} ({ci(rp['Avg@5_ci95'])}) |")
    L += ["", "## Paired differences (Avg@5, case bootstrap 95% CI)", "", "| model | split | comparison | mean diff | 95% CI | verdict |",
          "|---|---|---|---|---|---|"]
    for k, v in p.items():
        m, split, comp = k.split("|")
        L.append(f"| {m} | {split} | {comp} | {fmt(v['mean_diff'])} | {ci(v['ci95'])} | {v['verdict']} |")
    L += ["", "## Detection (LightGBM, repetition 3-fold)", "", "| inputs | AUROC (95% CI) | AUPRC |", "|---|---|---|"]
    for k, d in res["detection"].items():
        L.append(f"| {k} aggregates | {fmt(d['AUROC'])} ({ci(d['AUROC_ci95'])}) | {fmt(d['AUPRC'])} |")
    v = res["paired_detection"]["rel18 - raw18"]
    L.append(f"\nrel18 - raw18 AUROC: {fmt(v['mean_diff'])} ({ci(v['ci95'])}) {v['verdict']}")
    L += ["", "## LOSO Avg@5 by held-out root-cause service", "", "| model / features | " + " | ".join(services) + " |",
          "|---|" + "---|" * len(services)]
    for k, d in res["loso_by_service"].items():
        L.append(f"| {k} | " + " | ".join(fmt(d[s]) for s in services) + " |")
    (out / "results.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
