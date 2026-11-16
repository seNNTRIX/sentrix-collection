"""features/log_semantic and log_cluster: R8 rules (experiments/20261116-log-semantic-r8/PREREG.md 3-5, 9)."""
import json
from pathlib import Path
import sys
import unittest
import zlib

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.adapters import Case  # noqa: E402
from features.log_cluster import cluster_change  # noqa: E402
from features.log_semantic import (EmbeddingCache, HashingEncoder, extract_text, mask,  # noqa: E402
                                   prepare_logs, semantic_features, split_baseline)
from features.windows import label_linux_v1, make_windows  # noqa: E402

# run starts at 0, onset 600, removal 900, recovery 960. baseline_stats = windows inside [180, 480).
CASE = Case(case_id="lv1_t", root_cause="checkoutservice", fault="pod_failure", repetition=1, onset=600.0,
            path=Path("."), run_start=0.0, injection=595.0, removal=900.0, recovery=960.0)


def windows():
    w = make_windows(CASE.onset, CASE.run_start, 1500)
    w["label"] = [label_linux_v1(r, CASE) for r in w["rel"]]
    return w


class BagEncoder:
    """Deterministic bag-of-words stand-in for MiniLM: one dimension per token (crc32 mod 97)."""

    def __init__(self):
        self.calls = 0
        self.texts = []

    def __call__(self, texts):
        self.calls += 1
        self.texts += list(texts)
        m = np.zeros((len(texts), 97))
        for i, t in enumerate(texts):
            for tok in t.lower().split():
                m[i, zlib.crc32(tok.encode()) % 97] += 1
        return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)


def synthetic_logs():
    rows = []
    for t in np.arange(180, 1500, 0.5):          # frontend: steady normal traffic
        rows.append((t, "frontend", json.dumps({"message": "request complete" if t % 1 else "home",
                                                "severity": "debug"})))
    for t in np.arange(670, 900, 0.5):           # frontend: new error expression during the fault
        rows.append((t, "frontend", json.dumps({"message": "request error",
                                                "error": "rpc error: code = Unavailable desc = "
                                                         "connection refused 10.42.0.17:5050"})))
    for t in np.arange(180, 600, 1.0):           # checkout: logs stop at onset (pod failure)
        rows.append((t, "checkoutservice", json.dumps({"message": "payment went through"})))
    for t in (200, 250, 300, 350, 400):          # adservice: too few reference logs
        rows.append((t, "adservice", "received ad request"))
    rows.append((400.2, "frontend", json.dumps({"message": "rare cache warmup notice"})))
    return pd.DataFrame(rows, columns=["t", "service", "message"])


class TextTests(unittest.TestCase):
    def test_extract_json_with_error_field(self):
        line = json.dumps({"message": "request error", "error": "rpc error: code = Unavailable"})
        self.assertEqual(extract_text(line), "request error | rpc error: code = Unavailable")

    def test_extract_plain_and_error_column(self):
        self.assertEqual(extract_text("GetCartAsync called"), "GetCartAsync called")
        self.assertEqual(extract_text(json.dumps({"msg": "x"}), "boom"), "x | boom")

    def test_extract_error_object(self):
        line = json.dumps({"message": "failed", "error": {"code": 14}})
        self.assertEqual(extract_text(line), 'failed | {"code": 14}')

    def test_mask_identifiers_and_services(self):
        t = mask("order 3f1c2a9e-1b2c-4d5e-8f90-123456789abc for a@b.com via 10.42.0.17:5050 "
                 "pod checkoutservice-7d9c5b8f6d-abcde paymentservice amount 1234 at 2026-10-27T14:43:39Z")
        for bad in ("3f1c2a9e", "a@b.com", "10.42.0.17", "7d9c5b8f6d", "paymentservice", "1234", "14:43"):
            self.assertNotIn(bad, t)
        for good in ("<ID>", "<EMAIL>", "<IP>", "<POD>", "<SERVICE>", "<NUM>", "<TIME>"):
            self.assertIn(good, t)

    def test_mask_keeps_problem_words(self):
        t = mask("rpc error: code = Unavailable 14 UNAVAILABLE: connection refused timeout status 503")
        for good in ("Unavailable", "UNAVAILABLE", "connection refused", "timeout", "status 503"):
            self.assertIn(good, t)

    def test_prepare_drops_non_candidates(self):
        df = pd.DataFrame({"t": [1.0, 2.0], "service": ["loki", "frontend"], "message": ["a", "b"]})
        self.assertEqual(prepare_logs(df)["service"].tolist(), ["frontend"])


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.w = windows()
        self.logs = prepare_logs(synthetic_logs())

    def feats(self, encoder=None, **kw):
        cache = EmbeddingCache(encoder or BagEncoder())
        f = semantic_features(self.logs, self.w, cache, m_min=20, n_min=5, **kw)
        return f.merge(self.w[["w_start", "label"]], on="w_start")

    def test_split_baseline_halves(self):
        a, b, dist = split_baseline(self.w)
        self.assertEqual((a, b), (180.0, 330.0))
        self.assertTrue((dist["w_start"] >= 330).all())
        self.assertGreaterEqual(len(dist), 5)

    def test_new_error_expression_raises_change(self):
        f = self.feats()
        fe = f[f["service"] == "frontend"]
        fault = fe[fe["label"] == "fault_active"]
        normal = fe[fe["label"] == "normal"]
        self.assertTrue((fault["f_lsem_valid"] == 1).all())
        self.assertGreater(fault["f_lsem_dmean"].median(), normal["f_lsem_dmean"].abs().max())
        self.assertGreater(fault["f_lsem_dp90"].median(), 0)

    def test_silence_is_missing_not_large(self):
        f = self.feats()
        ck = f[(f["service"] == "checkoutservice") & (f["label"] == "fault_active")]
        self.assertTrue(ck["f_lsem_dmean"].isna().all())
        self.assertTrue((ck["f_lsem_valid"] == 0).all())

    def test_too_few_reference_logs_invalid(self):
        f = self.feats()
        ad = f[f["service"] == "adservice"]
        self.assertTrue(ad["f_lsem_dmean"].isna().all())
        self.assertTrue((ad["f_lsem_valid"] == 0).all())

    def test_service_without_logs_invalid(self):
        f = self.feats()
        pc = f[f["service"] == "productcatalogservice"]
        self.assertTrue((pc["f_lsem_valid"] == 0).all())

    def test_second_half_logs_are_not_reference(self):
        # "rare cache warmup notice" at 400 s is only in the second half: it must get a distance > 0,
        # which shows in a distribution window covering 400 s (IQR is 0 there, so delta = x - median).
        f = self.feats()
        fe = f[(f["service"] == "frontend") & (f["w_start"] <= 400.2) & (f["w_start"] > 370.2)]
        self.assertTrue((fe["f_lsem_dmean"] > 0).all())

    def test_reference_windows_not_scored(self):
        f = self.feats()
        fe = f[(f["service"] == "frontend") & (f["w_start"] < 330)]
        self.assertTrue(fe["f_lsem_dmean"].isna().all())

    def test_scope_all_and_prefix(self):
        f = self.feats(scope="all", prefix="f_lsemall")
        self.assertIn("f_lsemall_dmean", f)
        fe = f[(f["service"] == "frontend") & (f["label"] == "fault_active")]
        self.assertTrue((fe["f_lsemall_valid"] == 1).all())

    def test_hashing_encoder_same_pipeline(self):
        f = self.feats(encoder=HashingEncoder(), prefix="f_lchr")
        fe = f[(f["service"] == "frontend") & (f["label"] == "fault_active")]
        self.assertGreater(fe["f_lchr_dmean"].median(), 0)
        self.assertEqual(list(f.columns[:5]), ["w_start", "service", "f_lchr_dmean", "f_lchr_dp90", "f_lchr_valid"])

    def test_unique_texts_encoded_once(self):
        enc = BagEncoder()
        cache = EmbeddingCache(enc)
        semantic_features(self.logs, self.w, cache)
        semantic_features(self.logs, self.w, cache, scope="all")
        self.assertEqual(len(enc.texts), len(set(enc.texts)))
        self.assertEqual(len(enc.texts), self.logs["text"].nunique())

    def test_no_baseline_returns_invalid(self):
        w = self.w.copy()
        w["label"] = w["label"].replace("baseline_stats", "excluded")
        f = semantic_features(self.logs, w, EmbeddingCache(BagEncoder()))
        self.assertTrue((f["f_lsem_valid"] == 0).all())


class ClusterChangeTests(unittest.TestCase):
    def test_new_cluster_in_interval(self):
        logs = pd.DataFrame({"t": [1, 2, 3, 11, 12], "service": ["frontend"] * 5,
                             "text": ["home", "home", "home", "home", "request error | Unavailable"]})
        df = cluster_change(logs, {"home": 0, "request error | Unavailable": 1}, (0, 10), (10, 20))
        new = df[df["new_in_interval"]]
        self.assertEqual(new["representative"].tolist(), ["request error | Unavailable"])


if __name__ == "__main__":
    unittest.main()
