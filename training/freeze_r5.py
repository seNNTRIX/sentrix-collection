"""R5 method freeze: final hyperparameters and models trained on all 90 RE2-OB cases.

  python -m training.freeze_r5 --out experiments/20261027-re2ob-r5-freeze

Choices fixed before running (docs/METHOD-FREEZE.md):
- ranking: V4 = LightGBM LambdaRank on the 18 rel features, rank-averaged per case with stat_combined.
  Hyperparameters: inner LOSO over all 5 root-cause services (LOSO_GRID), max mean Avg@5, ties -> smaller.
- detection: LightGBM binary on the rel aggregates (max/mean over candidates of the rel features).
  Hyperparameters: inner repetition CV over all 3 repetitions (DET_GRID), max mean AUROC, ties -> smaller.
  Its out-of-fold RE2-OB performance is computed only to document it; it does not change the choice.
"""
import argparse
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import sklearn

from evaluation import metrics as M
from training import lgbm
from training.run_r4b import rel_cols


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel_detection_cols(D, rel):
    return [c for c in D.columns if c.rsplit("__", 1)[0] in rel]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="data/features/re2ob-v0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    feat, out = Path(args.features), Path(args.out)
    (out / "models").mkdir(parents=True, exist_ok=True)
    R = pd.read_parquet(feat / "ranking.parquet")
    D = pd.read_parquet(feat / "detection.parquet")
    rel = rel_cols(R)
    dcols = rel_detection_cols(D, rel)

    services = sorted(R["meta_root_cause"].unique())
    rank_params, rank_inner = lgbm.select_params(R, rel, services, lgbm.LOSO_GRID, lgbm.fit_ranker, lgbm.rank_avg5,
                                                 key="meta_root_cause")
    ranker = lgbm.fit_ranker(R, rel, rank_params)
    ranker.booster_.save_model(str(out / "models" / "ranker.txt"))
    print("ranker", rank_params, round(rank_inner, 3), flush=True)

    folds = sorted(D["meta_fold"].unique())
    det_params, det_inner = lgbm.select_params(D, dcols, folds, lgbm.DET_GRID, lgbm.fit_detector, lgbm.det_auroc)
    detector = lgbm.fit_detector(D, dcols, det_params)
    detector.booster_.save_model(str(out / "models" / "detector.txt"))
    print("detector", det_params, round(det_inner, 3), flush=True)

    # documentation only: out-of-fold detection with the frozen feature set (nested, as in R4)
    scored, chosen = lgbm.cv_detector(D, dcols)
    det_oof = M.detection_summary(scored["target"], scored["s_model"].to_numpy())
    rng = np.random.default_rng(0)
    ids = scored["meta_case_id"].unique()
    groups = {c: np.flatnonzero(scored["meta_case_id"].to_numpy() == c) for c in ids}
    boots = []
    for _ in range(300):
        idx = np.concatenate([groups[c] for c in rng.choice(ids, len(ids))])
        boots.append(M.detection_summary(scored["target"].to_numpy()[idx], scored["s_model"].to_numpy()[idx])["AUROC"])
    det_oof["AUROC_ci95"] = (float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975)))
    det_oof["chosen_per_fold"] = chosen
    print("detector oof", round(det_oof["AUROC"], 3), flush=True)

    frozen = {
        "ranking": {"method": "V4 hybrid: per-case rank average of LightGBM LambdaRank (rel) and stat_combined",
                    "features": rel, "params": rank_params, "inner_loso_avg5": rank_inner,
                    "selection": "inner LOSO over all 5 root-cause services, LOSO_GRID, max mean Avg@5, ties -> smaller",
                    "grid": lgbm.LOSO_GRID, "model_file": "models/ranker.txt",
                    "model_sha256": sha256(out / "models" / "ranker.txt")},
        "detection": {"method": "LightGBM binary on rel aggregates", "features": dcols, "params": det_params,
                      "inner_rep_cv_auroc": det_inner,
                      "selection": "inner repetition CV over all 3 repetitions, DET_GRID, max mean AUROC, ties -> smaller",
                      "grid": lgbm.DET_GRID, "model_file": "models/detector.txt",
                      "model_sha256": sha256(out / "models" / "detector.txt"), "re2ob_oof": det_oof},
        "common_params": lgbm.COMMON,
        "data": {"features": str(feat).replace("\\", "/"), "ranking_sha256": sha256(feat / "ranking.parquet"),
                 "detection_sha256": sha256(feat / "detection.parquet"), "n_cases": int(R["meta_case_id"].nunique())},
        "versions": {"lightgbm": lgb.__version__, "scikit-learn": sklearn.__version__, "pandas": pd.__version__,
                     "numpy": np.__version__},
    }
    (out / "frozen.json").write_text(json.dumps(frozen, indent=2, default=float), encoding="utf-8")
    print("done", out)


if __name__ == "__main__":
    main()
