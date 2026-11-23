"""Save the Method B model of one held-out fold, for the exhibition demo (not a new result).

Method B (evaluation/run_linux_v1.py method_b, the main result) trains, for each held-out linux-v1 repetition f,
  ranking  : RandomForestClassifier(frozen v2 params) on rel18, NaN -> 0, rows = RE2-OB ranking + linux-v1 ranking
             rows of the other folds;
  detection: LGBMClassifier(binary, frozen v2 params) on all58, rows = RE2-OB detection + linux-v1 detection rows of
             the other folds; operating threshold = 95th percentile of its training normal-window scores.
method_b keeps these models in memory only. This script retrains exactly the same two models for one fold (same
code path, same row order, deterministic params), checks them against the recorded Method B results, and writes
them in the format the model server loads (frozen.json + models/ + calibration.json).

Checks (all must pass, otherwise nothing is written):
  - threshold equals results.json method_b.folds[f].threshold (abs diff < 1e-12)
  - held-out RF rel18 fold Avg@5 equals results.json method_b.fold_avg5.rf18[f]
  - the saved LightGBM text model predicts the same probabilities as the in-memory classifier

  python -m evaluation.export_b_fold_model --fold 2 --re2ob data/features/re2ob-v0 \
      --features data/features/linux-v1-v0 --results experiments/20261123-linux-v1-eval-b/results.json \
      --out ../sentrix-model-server/demo/model-b-fold2
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from evaluation import metrics as M
from evaluation.aggregate import case_rankings
from evaluation.run_linux_v1 import THRESHOLD_Q, V2


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fold", type=int, required=True, help="held-out linux-v1 repetition (meta_fold)")
    ap.add_argument("--re2ob", default="data/features/re2ob-v0")
    ap.add_argument("--features", default="data/features/linux-v1-v0")
    ap.add_argument("--results", default="experiments/20261123-linux-v1-eval-b/results.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    f, re2, feat, out = a.fold, Path(a.re2ob), Path(a.features), Path(a.out)

    v2 = json.loads((V2 / "frozen.json").read_text(encoding="utf-8"))
    rp, dp = dict(v2["ranking"]["params"]), dict(v2["detection"]["params"])
    rel18, dcols = v2["ranking"]["features"], v2["detection"]["features"]
    R2 = pd.read_parquet(re2 / "ranking.parquet")
    D2 = pd.read_parquet(re2 / "detection.parquet")
    R = pd.read_parquet(feat / "ranking.parquet")
    D = pd.read_parquet(feat / "detection.parquet")
    rec = json.loads(Path(a.results).read_text(encoding="utf-8"))["method_b"]
    folds = sorted(R["meta_fold"].unique())
    if f not in folds:
        raise SystemExit(f"fold {f} not in {folds}")
    rec_thr = next(x["threshold"] for x in rec["folds"] if x["fold"] == f)
    rec_avg5 = rec["fold_avg5"]["rf18"][folds.index(f)]

    # identical to method_b
    trR = pd.concat([R2[rel18 + ["target"]], R.loc[R["meta_fold"] != f, rel18 + ["target"]]], ignore_index=True)
    rf = RandomForestClassifier(n_jobs=4, **rp).fit(trR[rel18].astype(float).fillna(0.0).to_numpy(), trR["target"])
    teR = R["meta_fold"] == f
    R["s_rf18"] = np.nan
    R.loc[teR, "s_rf18"] = rf.predict_proba(R.loc[teR, rel18].astype(float).fillna(0.0).to_numpy())[:, 1]
    rows = [r for r in case_rankings(R, "s_rf18") if r[3]["fold"] == f]
    avg5 = M.ranking_summary([(s, i) for _, s, i, _ in rows]).get("Avg@5")
    trD = pd.concat([D2[dcols + ["target"]], D.loc[D["meta_fold"] != f, dcols + ["target"]]], ignore_index=True)
    det = lgb.LGBMClassifier(objective="binary", **dp).fit(trD[dcols], trD["target"])
    normal = det.predict_proba(trD.loc[trD["target"] == 0, dcols])[:, 1]
    thr = float(np.quantile(normal, THRESHOLD_Q))

    checks = {"threshold": [thr, rec_thr, abs(thr - rec_thr) < 1e-12],
              "fold_avg5_rf18": [avg5, rec_avg5, abs(avg5 - rec_avg5) < 1e-12]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "models").mkdir(exist_ok=True)
    det_path, rf_path = out / "models" / "detector_lgbm.txt", out / "models" / "ranker_rf.joblib"
    det.booster_.save_model(str(det_path))
    reloaded = lgb.Booster(model_file=str(det_path)).predict(D.loc[D["meta_fold"] == f, dcols], num_threads=1)
    direct = det.predict_proba(D.loc[D["meta_fold"] == f, dcols])[:, 1]
    checks["saved_detector_matches"] = [float(np.max(np.abs(reloaded - direct))), 0.0,
                                        bool(np.max(np.abs(reloaded - direct)) < 1e-12)]
    print(json.dumps(checks, indent=1))
    if not all(c[2] for c in checks.values()):
        det_path.unlink()
        raise SystemExit("check failed: the retrained model is not the recorded Method B model; nothing written")
    joblib.dump({"model": rf, "features": rel18, "nan_fill": 0.0}, rf_path)

    held_out = sorted(R.loc[teR, "meta_case_id"].unique()) if "meta_case_id" in R else None
    manifest = {
        "model_version": f"linuxv1-b-fold{f}",
        "purpose": "exhibition demo: Method B (main result) model of held-out repetition "
                   f"{f}; use it only on linux-v1 runs of repetition {f} (never seen in training)",
        "ranking": {"method": v2["ranking"]["method"], "params": rp, "features": rel18,
                    "model_file": "models/ranker_rf.joblib", "model_sha256": sha256(rf_path),
                    "train_rows": int(len(trR))},
        "detection": {"method": v2["detection"]["method"], "params": dp, "features": dcols,
                      "model_file": "models/detector_lgbm.txt", "model_sha256": sha256(det_path),
                      "train_rows": int(len(trD))},
        "data": {"re2ob_ranking_sha256": sha256(re2 / "ranking.parquet"),
                 "re2ob_detection_sha256": sha256(re2 / "detection.parquet"),
                 "linux_v1_ranking_sha256": sha256(feat / "ranking.parquet"),
                 "linux_v1_detection_sha256": sha256(feat / "detection.parquet"),
                 "held_out_fold": f, "held_out_ranking_cases": held_out},
        "checks": checks,
        "versions": {p: importlib.metadata.version(p) for p in ("scikit-learn", "lightgbm", "pandas", "numpy", "joblib")},
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "frozen.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    calib = {"threshold": thr, "quantile": THRESHOLD_Q,
             "rule": "run alarm when 2 consecutive 30 s windows (10 s apart) score above the threshold",
             "detector_sha256": manifest["detection"]["model_sha256"], "model_version": manifest["model_version"],
             "source": {"rows": "Method B fold training normal windows (RE2-OB + linux-v1 other folds)",
                        "n_normal_windows": int(len(normal))},
             "normal_score_summary": {"median": float(np.median(normal)), "p90": float(np.quantile(normal, 0.9)),
                                      "p99": float(np.quantile(normal, 0.99)), "max": float(normal.max())},
             "created_at": manifest["created_at"]}
    (out / "calibration.json").write_text(json.dumps(calib, indent=1), encoding="utf-8")
    print(f"wrote {out}: threshold {thr:.6g}, fold Avg@5 {avg5:.3f}")


if __name__ == "__main__":
    main()
