"""Method freeze v2: final models trained on all 90 RE2-OB cases (docs/METHOD-FREEZE-v2.md).

  .venv-r6/Scripts/python -m training.freeze_v2 --out experiments/20261028-re2ob-v2-freeze

Choices fixed before running (R6 pre-registered rule, 3595be4; R6b kept the picks, e7114c6):
- ranking: Random Forest on the 18 rel features (R6 "rf|rel|pure"), pointwise on (window, candidate) rows,
  NaN -> 0. Hyperparameters: inner LOSO over all 5 root-cause services (R6 RANK_GRIDS["rf"]), max mean Avg@5,
  ties -> earlier (simpler) setting. Same code path as R6 (training/run_r6.py).
- detection: LightGBM binary on all 58 detection aggregates (R6 "lgbm|all|pure"). Hyperparameters: inner
  repetition CV over all 3 repetitions (R6 DET_GRIDS["lgbm"]), max mean AUROC, ties -> simpler.
Out-of-fold RE2-OB numbers are copied from the R6 results; this script does not evaluate.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier

from training import lgbm
from training import run_r6 as r6


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--r6", default="experiments/20261027-re2ob-r6-models")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    feat, out = Path(args.features), Path(args.out)
    (out / "models").mkdir(parents=True, exist_ok=True)
    R = pd.read_parquet(feat / "ranking.parquet")
    D = pd.read_parquet(feat / "detection.parquet")
    rel = r6.rank_fsets(R)["rel"]
    dcols = r6.det_fsets(D, R)["all"]

    services = sorted(R["meta_root_cause"].unique())
    fit_rank = lambda d, c, p: r6.fit_rank("rf", d, c, p)  # noqa: E731
    rank_params, rank_inner = r6.select(R, rel, services, "meta_root_cause", r6.RANK_GRIDS["rf"], fit_rank, r6.rank_avg5)
    print("ranker", rank_params, round(rank_inner, 3), flush=True)
    ranker = RandomForestClassifier(n_estimators=300, random_state=r6.SEED, n_jobs=4, **rank_params)
    ranker.fit(r6.dense(R[rel]), R["target"])
    joblib.dump({"model": ranker, "features": rel, "nan_fill": 0.0}, out / "models" / "ranker_rf.joblib")

    folds = sorted(D["meta_fold"].unique())
    fit_det = lambda d, c, p: r6.fit_det("lgbm", d, c, p)  # noqa: E731
    det_params, det_inner = r6.select(D, dcols, folds, "meta_fold", r6.DET_GRIDS["lgbm"], fit_det, r6.det_auroc)
    print("detector", det_params, round(det_inner, 3), flush=True)
    detector = lgb.LGBMClassifier(objective="binary", **lgbm.COMMON, min_child_samples=20, **det_params)
    detector.fit(D[dcols], D["target"])
    detector.booster_.save_model(str(out / "models" / "detector_lgbm.txt"))

    r6res = json.loads((Path(args.r6) / "results.json").read_text(encoding="utf-8"))
    frozen = {
        "ranking": {"method": "Random Forest on rel18, pointwise (window, candidate) rows, NaN -> 0, score = P(root cause)",
                    "features": rel, "params": {"n_estimators": 300, "random_state": r6.SEED, **rank_params},
                    "inner_loso_avg5": rank_inner, "grid": r6.RANK_GRIDS["rf"],
                    "selection": "inner LOSO over all 5 root-cause services, max mean Avg@5, ties -> earlier setting",
                    "model_file": "models/ranker_rf.joblib", "model_sha256": sha256(out / "models" / "ranker_rf.joblib"),
                    "re2ob_oof": {"loso": r6res["ranking_loso"]["rf|rel|pure"], "rep": r6res["ranking_rep"]["rf|rel|pure"]}},
        "detection": {"method": "LightGBM binary on all 58 detection aggregates", "features": dcols,
                      "params": {**lgbm.COMMON, "min_child_samples": 20, **det_params}, "inner_rep_cv_auroc": det_inner,
                      "grid": r6.DET_GRIDS["lgbm"],
                      "selection": "inner repetition CV over all 3 repetitions, max mean AUROC, ties -> earlier setting",
                      "model_file": "models/detector_lgbm.txt", "model_sha256": sha256(out / "models" / "detector_lgbm.txt"),
                      "re2ob_oof": r6res["detection"]["lgbm|all|pure"]},
        "data": {"features": str(feat).replace("\\", "/"), "ranking_sha256": sha256(feat / "ranking.parquet"),
                 "detection_sha256": sha256(feat / "detection.parquet"), "n_cases": int(R["meta_case_id"].nunique())},
        "versions": {"scikit-learn": sklearn.__version__, "lightgbm": lgb.__version__, "pandas": pd.__version__,
                     "numpy": np.__version__, "joblib": joblib.__version__},
    }
    (out / "frozen.json").write_text(json.dumps(frozen, indent=2, default=float), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
