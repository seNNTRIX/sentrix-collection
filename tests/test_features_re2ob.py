"""R2 feature pipeline: labels, resampling, leakage guards, fold integrity.

Uses small synthetic cases written in the RE2-OB Zenodo layout, so it runs
without the real dataset.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from features import schema  # noqa: E402
from features.adapters import re2ob  # noqa: E402
from features.build_re2ob import build_case  # noqa: E402
from features.windows import label_re2ob  # noqa: E402

ONSET = 1_000_000_720
SERVICES = ("frontend", "checkoutservice", "currencyservice")


def write_case(base, service="checkoutservice", fault="cpu", rep=1, onset=ONSET):
    d = base / f"{service}_{fault}" / str(rep)
    d.mkdir(parents=True)
    (d / "inject_time.txt").write_text(str(onset))
    t = np.arange(onset - 720, onset + 721)
    rng = np.random.default_rng(rep)
    cols = {"time": t}
    for s in SERVICES:
        cpu = 1.0 + rng.normal(0, 0.05, len(t))
        if s == service and fault == "cpu":
            cpu = np.where(t >= onset, 20.0, cpu)
        cols[f"{s}_container-cpu-usage-seconds-total"] = cpu
        cols[f"{s}_container-spec-cpu-quota"] = 20000
        cols[f"{s}_container-memory-working-set-bytes"] = 1e7 + rng.normal(0, 1e4, len(t))
        cols[f"{s}_container-spec-memory-limit-bytes"] = 1.34e8
        for d_ in ("receive", "transmit"):
            cols[f"{s}_container-network-{d_}-packets-total"] = 10 + rng.normal(0, 0.5, len(t))
            cols[f"{s}_container-network-{d_}-packets-dropped-total"] = 0.0
    cols["frontend-external_istio-request-total"] = 5.0   # not a candidate
    pd.DataFrame(cols).to_csv(d / "metrics.csv", index=False)

    rows = []
    for i, ts in enumerate(t):
        us = int(ts * 1_000_000)
        slow = 0.050 if (ts >= onset and service == "currencyservice" and fault == "delay") else 0.002
        rows += [
            (f"r{i}", "", "frontendservice", us, 10_000, ""),
            (f"c{i}", f"r{i}", "frontendservice", us + 10, int(slow * 1e6) + 1_000, "0.0"),
            (f"s{i}", f"c{i}", "currencyservice", us + 20, int(slow * 1e6), "0.0"),
            (f"k{i}", f"r{i}", "checkoutservice", us + 30, 4_000, "0.0"),
        ]
    tr = pd.DataFrame(rows, columns=["spanID", "parentSpanID", "serviceName", "startTime", "duration", "statusCode"])
    tr["time"], tr["traceID"], tr["methodName"], tr["operationName"] = "00:00", "x", "m", "op"
    tr["startTimeMillis"] = tr["startTime"] // 1000
    tr.to_csv(d / "traces.csv", index=False)
    lg = pd.DataFrame({"time": "00:00", "timestamp": (t * 1e9).astype("int64"), "container_name": "currencyservice",
                       "message": "ok", "level": "info", "error": ""})
    lg.to_csv(d / "logs.csv", index=False)
    return d


class LabelTests(unittest.TestCase):
    def test_lifecycle_boundaries(self):
        self.assertEqual(label_re2ob(-720), "baseline_stats")
        self.assertEqual(label_re2ob(-450), "baseline_stats")
        self.assertEqual(label_re2ob(-440), "excluded")       # crosses -420
        self.assertEqual(label_re2ob(-420), "normal")
        self.assertEqual(label_re2ob(-30), "normal")
        self.assertEqual(label_re2ob(-20), "transition")      # crosses injection
        self.assertEqual(label_re2ob(50), "transition")
        self.assertEqual(label_re2ob(60), "fault_active")

    def test_resample_takes_last_fresh_value(self):
        times = np.array([0.0, 1, 2, 3, 4, 5, 6])
        vals = times * 10
        out = re2ob.resample(times, vals, np.array([5.0, 20.0]))
        self.assertEqual(out[0], 50.0)
        self.assertTrue(np.isnan(out[1]))                     # older than 5 s: not forward-filled


class CaseListingTests(unittest.TestCase):
    def test_excludes_sample_folder_and_parses_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "checkoutservice_cpu" / "multi-source-data").mkdir(parents=True)
            (base / "checkoutservice_cpu" / "multi-source-data" / "inject_time.txt").write_text("1")
            write_case(base, "productcatalogservice", "loss", 2)
            cases = re2ob.list_cases(base)
            self.assertEqual([c.case_id for c in cases], ["re2ob_productcatalogservice_loss_2"])
            self.assertEqual((cases[0].root_cause, cases[0].fault, cases[0].repetition), ("productcatalogservice", "loss", 2))
            self.assertEqual(re2ob.canonical("frontendservice"), "frontend")
            self.assertEqual(re2ob.canonical("redis"), "redis-cart")
            self.assertIsNone(re2ob.canonical("frontend-external"))


class BuildCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        write_case(Path(cls.tmp.name), "checkoutservice", "cpu", 1)
        write_case(Path(cls.tmp.name), "currencyservice", "delay", 2)
        cases = re2ob.list_cases(cls.tmp.name)
        cls.cpu = build_case(cases[0])
        cls.delay = build_case(cases[1])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_feature_columns_do_not_leak_identity_or_time(self):
        for table in (self.cpu[0], self.cpu[1]):
            fcols = [c for c in table.columns if c.startswith(schema.FEATURE_PREFIX)]
            self.assertTrue(fcols)
            for c in fcols:
                for part in schema.FORBIDDEN_NAME_PARTS:
                    self.assertNotIn(part, c.lower(), f"{c} contains {part}")
            others = [c for c in table.columns if not c.startswith(schema.FEATURE_PREFIX)]
            self.assertTrue(all(c.startswith(schema.META_PREFIX) or c == schema.TARGET_COLUMN for c in others), others)
            # no feature column is a copy of the identity or time columns
            for c in fcols:
                col = table[c]
                if col.dtype == object:
                    self.fail(f"non-numeric feature {c}")

    def test_exactly_one_target_per_window_and_only_fault_active(self):
        ranking = self.cpu[0]
        self.assertTrue((ranking["meta_label"] == "fault_active").all())
        per_window = ranking.groupby("meta_window")[schema.TARGET_COLUMN].sum()
        self.assertTrue((per_window == 1).all())
        self.assertEqual(set(ranking.loc[ranking[schema.TARGET_COLUMN] == 1, "meta_candidate"]), {"checkoutservice"})
        self.assertEqual(set(ranking["meta_candidate"]), set(schema.CANDIDATES))

    def test_signal_points_at_root_cause(self):
        r = self.cpu[0]
        med = r.groupby("meta_candidate")["f_cm_cpu_cores_dmean"].median()
        self.assertEqual(med.idxmax(), "checkoutservice")
        d = self.delay[0]
        lat = d.groupby("meta_candidate")["f_ct_in_p90_lr"].median()
        self.assertEqual(lat.idxmax(), "currencyservice")
        out = d.groupby("meta_candidate")["f_ct_out_p90_lr"].median()
        self.assertGreater(out["frontend"], 1.0)              # caller sees the slow edge

    def test_detection_labels(self):
        det = self.cpu[1]
        self.assertEqual(set(det["meta_label"]), {"normal", "fault_active"})
        self.assertTrue(((det["meta_label"] == "fault_active") == (det[schema.TARGET_COLUMN] == 1)).all())

    def test_untraced_candidate_is_masked_not_zero(self):
        r = self.cpu[0]
        ad = r[r["meta_candidate"] == "adservice"]
        self.assertTrue((ad["f_ct_mask"] == 0).all())
        self.assertTrue(ad["f_ct_in_p90_lr"].isna().all())


class FoldTests(unittest.TestCase):
    def test_build_cli_folds_are_case_disjoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "RE2-OB"
            for rep in (1, 2, 3):
                write_case(base, "checkoutservice", "cpu", rep)
            out = Path(tmp) / "out"
            subprocess.run([sys.executable, "-m", "features.build_re2ob", "--root", str(base), "--out", str(out),
                            "--workers", "1"], cwd=ROOT, check=True, capture_output=True)
            folds = json.loads((out / "folds.json").read_text())
            ids = [c for v in folds.values() for c in v]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(sorted(folds), ["1", "2", "3"])
            ranking = pd.read_parquet(out / "ranking.parquet")
            self.assertTrue((ranking.groupby("meta_case_id")["meta_fold"].nunique() == 1).all())
            for k, v in folds.items():
                self.assertTrue((ranking[ranking["meta_case_id"].isin(v)]["meta_fold"] == int(k)).all())
            # outputs are never overwritten
            again = subprocess.run([sys.executable, "-m", "features.build_re2ob", "--root", str(base), "--out", str(out)],
                                   cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)


if __name__ == "__main__":
    unittest.main()
