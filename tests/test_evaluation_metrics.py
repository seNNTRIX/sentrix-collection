"""Hand-computed checks for evaluation/metrics.py and evaluation/aggregate.py."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import metrics as M  # noqa: E402
from evaluation.aggregate import case_rankings  # noqa: E402


class RankingMetricTests(unittest.TestCase):
    def test_hand_example_three_cases(self):
        # case A: root at rank 1, case B: rank 2, case C: rank 4 (of 5)
        cases = [
            (np.array([0.9, 0.1, 0.2, 0.3, 0.0]), 0),
            (np.array([0.5, 0.9, 0.1, 0.0, 0.2]), 0),
            (np.array([0.5, 0.9, 0.1, 0.8, 0.7]), 0),
        ]
        s = M.ranking_summary(cases)
        self.assertAlmostEqual(s["AC@1"], 1 / 3)
        self.assertAlmostEqual(s["AC@3"], 2 / 3)
        self.assertAlmostEqual(s["AC@5"], 1.0)
        # AC@1..5 = 1/3, 2/3, 2/3, 1, 1 -> mean 11/15
        self.assertAlmostEqual(s["Avg@5"], (1 / 3 + 2 / 3 + 2 / 3 + 1 + 1) / 5)
        self.assertAlmostEqual(s["MRR"], (1 + 1 / 2 + 1 / 4) / 3)

    def test_ties_use_expected_rank(self):
        # all equal among 4 -> rank uniform over 1..4
        s = np.zeros(4)
        self.assertAlmostEqual(M.case_hit_at(s, 2, 1), 0.25)
        self.assertAlmostEqual(M.case_hit_at(s, 2, 3), 0.75)
        self.assertAlmostEqual(M.case_reciprocal_rank(s, 2), (1 + 1 / 2 + 1 / 3 + 1 / 4) / 4)
        # one strictly higher, tie of two -> rank 2 or 3
        s = np.array([5.0, 1.0, 1.0, 0.0])
        self.assertAlmostEqual(M.case_hit_at(s, 1, 1), 0.0)
        self.assertAlmostEqual(M.case_hit_at(s, 1, 2), 0.5)
        self.assertAlmostEqual(M.case_hit_at(s, 1, 3), 1.0)

    def test_nan_is_ranked_last(self):
        s = np.array([np.nan, 0.1, np.nan])
        self.assertAlmostEqual(M.case_hit_at(s, 1, 1), 1.0)
        self.assertAlmostEqual(M.case_hit_at(s, 0, 1), 0.0)
        self.assertAlmostEqual(M.case_hit_at(s, 0, 2), 0.5)   # tied with the other NaN for ranks 2-3

    def test_bootstrap_ci_brackets_mean(self):
        per = [{"AC@1": v} for v in [1, 0, 1, 1, 0, 1, 0, 1, 1, 1]]
        lo, hi = M.bootstrap_ci(per, "AC@1", n_boot=500, seed=1)
        self.assertLessEqual(lo, 0.7)
        self.assertGreaterEqual(hi, 0.7)

    def test_detection_hand_example(self):
        d = M.detection_summary([0, 0, 1, 1], [0.1, 0.4, 0.35, 0.8])
        self.assertAlmostEqual(d["AUROC"], 0.75)
        # AP: ranks 0.8(+) 0.4(-) 0.35(+) 0.1(-) -> (1/1 + 2/3)/2
        self.assertAlmostEqual(d["AUPRC"], (1 + 2 / 3) / 2)


class AggregationTests(unittest.TestCase):
    def test_horizon_mean_and_alignment(self):
        rows = []
        for rel, a, b in [(30, 100, 0), (60, 1, 2), (290, 3, 4), (300, 100, 0)]:
            rows += [{"meta_case_id": "c1", "meta_rel": rel, "meta_window": rel, "meta_candidate": "frontend",
                      "meta_root_cause": "cartservice", "meta_fault": "cpu", "meta_fold": 1, "s": a},
                     {"meta_case_id": "c1", "meta_rel": rel, "meta_window": rel, "meta_candidate": "cartservice",
                      "meta_root_cause": "cartservice", "meta_fault": "cpu", "meta_fold": 1, "s": b}]
        out = list(case_rankings(pd.DataFrame(rows), "s", candidates=("cartservice", "frontend", "adservice")))
        self.assertEqual(len(out), 1)
        _, scores, true_idx, meta = out[0]
        self.assertEqual(true_idx, 0)
        np.testing.assert_allclose(scores[:2], [3.0, 2.0])     # only rel 60 and 290 are inside [60, 300)
        self.assertTrue(np.isnan(scores[2]))
        self.assertEqual(meta["n_windows"], 2)


if __name__ == "__main__":
    unittest.main()
