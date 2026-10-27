"""Guards for training/lgbm.py cross-validation: no test-fold use in selection or fitting."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.schema import CANDIDATES  # noqa: E402
from training import lgbm  # noqa: E402


def toy_ranking(n_cases_per_fold=4, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    roots = ["checkoutservice", "currencyservice", "emailservice", "productcatalogservice"]
    for fold in (1, 2, 3):
        for c in range(n_cases_per_fold):
            root = roots[c % len(roots)]
            cid = f"case_f{fold}_{c}"
            for w, rel in enumerate(range(60, 300, 10)):
                for cand in CANDIDATES:
                    sig = 3.0 if cand == root else 0.0
                    rows.append({"meta_case_id": cid, "meta_window": w, "meta_rel": rel, "meta_candidate": cand,
                                 "meta_root_cause": root, "meta_fault": "cpu", "meta_fold": fold,
                                 "target": int(cand == root), "f_cm_x": sig + rng.normal(0, 1),
                                 "f_ct_y": rng.normal(0, 1)})
    return pd.DataFrame(rows)


class CvGuardTests(unittest.TestCase):
    def test_fit_and_selection_never_see_test_fold(self):
        df = toy_ranking()
        seen = []
        real_fit = lgbm.fit_ranker

        def spy(train, cols, params):
            seen.append(set(train["meta_fold"].unique()))
            return real_fit(train, cols, params)

        small = {"num_leaves": [3], "n_estimators": [10, 20], "min_child_samples": [5]}
        with patch.object(lgbm, "fit_ranker", side_effect=spy), patch.object(lgbm, "RANK_GRID", small):
            rows, chosen, _, scored = lgbm.cv_ranker(df, ["f_cm_x", "f_ct_y"])
        # 3 outer folds x (2 params x 2 inner splits + 1 final fit)
        self.assertEqual(len(seen), 3 * (2 * 2 + 1))
        calls = iter(seen)
        for test in (1, 2, 3):
            for _ in range(2 * 2 + 1):
                self.assertNotIn(test, next(calls))
        self.assertEqual(len(rows), 12)                          # one out-of-fold ranking per case
        self.assertEqual(len({r[0] for r in rows}), 12)
        self.assertEqual(set(scored["meta_fold"]), {1, 2, 3})

    def test_learns_signal_column(self):
        df = toy_ranking()
        rows, *_ = lgbm.cv_ranker(df, ["f_cm_x", "f_ct_y"],
                                  fixed_params={"num_leaves": 3, "n_estimators": 30, "min_child_samples": 5})
        from evaluation import metrics as M
        self.assertGreater(M.ranking_summary([(s, i) for _, s, i, _ in rows])["AC@1"], 0.9)


if __name__ == "__main__":
    unittest.main()
