"""evaluation/edge_rank.py: statistical edge ranking frozen in R5."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import metrics as M  # noqa: E402
from evaluation.edge_rank import edge_case_rankings  # noqa: E402


def toy_edges(slow=("frontend", "productcatalogservice"), err_edge=None):
    rows = []
    edges = [("frontend", "productcatalogservice"), ("frontend", "currencyservice"), ("checkoutservice", "paymentservice")]
    for w, rel in enumerate(range(-400, 300, 10)):
        label = "baseline_stats" if rel < -120 else ("normal" if rel < 0 else ("transition" if rel < 60 else "fault_active"))
        for src, dst in edges:
            p90, err = 0.05 + 0.001 * (w % 3), 0.0
            if label == "fault_active" and (src, dst) == slow:
                p90 = 0.5
            if label == "fault_active" and (src, dst) == err_edge:
                err = 0.3
            rows.append({"meta_case_id": "c1", "meta_window": w, "meta_rel": float(rel), "meta_label": label,
                         "meta_src": src, "meta_dst": dst, "calls": 2.0, "err": err, "p90": p90})
    return pd.DataFrame(rows)


class EdgeRankTests(unittest.TestCase):
    def test_slow_edge_ranked_first(self):
        (cid, s, i, meta), = edge_case_rankings(toy_edges(), {"c1": "frontend->productcatalogservice"})
        self.assertEqual(len(s), 3)
        self.assertEqual(M.case_hit_at(s, i, 1), 1.0)

    def test_error_edge_ranked_first(self):
        (_, s, i, _), = edge_case_rankings(toy_edges(slow=None, err_edge=("checkoutservice", "paymentservice")),
                                          {"c1": "checkoutservice->paymentservice"})
        self.assertEqual(M.case_hit_at(s, i, 1), 1.0)

    def test_unobserved_true_edge_is_last(self):
        (_, s, i, meta), = edge_case_rankings(toy_edges(), {"c1": "recommendationservice->productcatalogservice"})
        self.assertEqual(len(s), 4)
        self.assertEqual(i, 3)
        self.assertTrue(np.isnan(s[i]))
        self.assertEqual(M.case_hit_at(s, i, 3), 0.0)


if __name__ == "__main__":
    unittest.main()
