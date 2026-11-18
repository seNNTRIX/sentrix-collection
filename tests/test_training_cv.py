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

    def test_loso_never_uses_held_out_root_cause(self):
        df = toy_ranking()
        fit_roots, val_roots = [], []
        real_fit, real_eval = lgbm.fit_ranker, lgbm.rank_avg5

        def spy_fit(train, cols, params):
            fit_roots.append(set(train["meta_root_cause"].unique()))
            return real_fit(train, cols, params)

        def spy_eval(model, va, cols):
            val_roots.append(set(va["meta_root_cause"].unique()))
            return real_eval(model, va, cols)

        small = {"num_leaves": [3], "n_estimators": [10, 20], "min_child_samples": [5]}
        with patch.object(lgbm, "fit_ranker", side_effect=spy_fit), patch.object(lgbm, "rank_avg5", side_effect=spy_eval):
            rows, chosen = lgbm.loso_ranker(df, ["f_cm_x", "f_ct_y"], grid_def=small)
        services = sorted(df["meta_root_cause"].unique())
        per_held = 2 * 3 + 1                                     # 2 params x 3 inner services + final fit
        self.assertEqual(len(fit_roots), len(services) * per_held)
        for k, held in enumerate(services):
            for roots in fit_roots[k * per_held:(k + 1) * per_held]:
                self.assertNotIn(held, roots)
            for roots in val_roots[k * 6:(k + 1) * 6]:
                self.assertNotIn(held, roots)
        self.assertEqual(sorted(chosen), services)
        self.assertEqual(len(rows), 12)
        for _, _, i, meta in rows:                               # each case scored by the model that held its root out
            self.assertEqual(CANDIDATES[i], meta["root_cause"])

    def test_rel_bundle_and_monotone(self):
        from training import run_r4b
        cols = ["f_cm_cpu_cores_dmean", "f_cm_cpu_cores_n", "f_cm_cpu_cores_zero_iqr", "f_cm_mem_limit_ratio_mean",
                "f_cm_net_rx_pkts_dmax", "f_ct_mask", "f_ct_in_err", "f_ct_in_err_d", "f_ct_out_err", "f_ct_out_p90_lr",
                "f_ct_in_edge_p90_lr", "meta_case_id"]
        rel = run_r4b.rel_cols(pd.DataFrame(columns=cols))
        self.assertEqual(rel, ["f_cm_cpu_cores_dmean", "f_cm_net_rx_pkts_dmax", "f_ct_in_err_d", "f_ct_out_p90_lr",
                               "f_ct_in_edge_p90_lr"])
        self.assertEqual(run_r4b.monotone(rel), [1, 0, 1, 0, 1])

    def test_hybrid_ranks(self):
        from training import run_r4b
        a = [("c", np.array([3.0, 2.0, np.nan]), 1, {})]
        b = [("c", np.array([0.1, 0.9, 0.5]), 1, {})]
        (_, s, i, _), = run_r4b.hybrid(a, b)
        np.testing.assert_allclose(s, [-(1 + 3) / 2, -(2 + 1) / 2, -(3 + 2) / 2])


if __name__ == "__main__":
    unittest.main()
