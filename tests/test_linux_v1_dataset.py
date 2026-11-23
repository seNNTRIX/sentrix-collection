"""linux-v1 dataset builder (features/adapters/linux_v1.py, features/build_linux_v1.py).

Synthetic dataset roots in the collection layout (runs/, incidents/, audits/, canonical parquet), so the
tests run without real linux-v1 data. Rules: docs/LINUX-V1-DATA-TRANSLATION.md.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from features import build_linux_v1 as B  # noqa: E402
from features import windows  # noqa: E402
from features.adapters import linux_v1 as L  # noqa: E402
from features.schema import CANDIDATES  # noqa: E402

RUN_S = 1200
ONSET_OFF = 600.3          # started_at offset in the fault run
REMOVAL_OFF = 900.4
VIEW = "canonical-v2-test"
HEADER = ("schedule_index,pair_id,fault_type,target_kind,target_id,repetition,pair_order,onset_offset_seconds,"
          "workload_seed,fault_run_id,control_run_id,fault_profile,control_profile")


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric_rows(t0, target=None, pod_down=None, ready_zero=None, gap=None, extra_app=None):
    """Canonical metrics rows on a 5 s grid. pod_down=(a, b): target app series missing in [a, b).
    ready_zero=(a, b): target Ready = 0 in [a, b). gap=(service, t): cpu point missing (tolerated gap)."""
    rows = []
    grid = t0 + np.arange(0, RUN_S + 1, 5, dtype=float)

    def add(group, name, svc, lab, values, raw=None, canon=True):
        for t, v in zip(grid, values):
            if v is None:
                continue
            rows.append({"telemetry_source": "metrics", "timestamp_unix": float(t),
                         "raw_service_id": raw or lab.get("pod"), "canonical_service_id": svc if canon else None,
                         "identity_resolution_method": "x", "mapping_version": 1, "metric_group": group,
                         "metric_name": name, "value": float(v), "labels_json": json.dumps(lab)})

    for i, svc in enumerate(CANDIDATES):
        pod = f"{svc}-5c676694c8-ab{i:03d}"
        app = {"container": "redis" if svc == "redis-cart" else "server", "pod": pod, "namespace": "sentrix"}
        podlab = {"pod": pod, "namespace": "sentrix"}
        down = np.zeros(len(grid), bool)
        if svc == target and pod_down:
            down = (grid >= t0 + pod_down[0]) & (grid < t0 + pod_down[1])
        cpu = [None if d else 0.1 + 0.001 * (k % 7) for k, d in enumerate(down)]
        if gap and gap[0] == svc:
            cpu = [None if abs(t - gap[1]) < 1e-6 else v for t, v in zip(grid, cpu)]
        add(L.G_CPU, L.G_CPU, svc, app, cpu)
        add(L.G_CPU, L.G_CPU, svc, podlab, [0.5] * len(grid))                     # pod-level: excluded
        add(L.G_CPU, L.G_CPU, svc, {**podlab, "container": "POD"}, [0.5] * len(grid))   # pause: excluded
        add(L.G_MEM, L.G_MEM, svc, app, [None if d else 1e8 for d in down])
        add(L.G_QUOTA, L.G_QUOTA, svc, app, [50000] * len(grid))
        add(L.G_PERIOD, L.G_PERIOD, svc, app, [100000] * len(grid))
        add(L.G_MEM_LIMIT, "kube_pod_container_resource_limits", svc, app, [2e8] * len(grid))
        add(L.G_RX_DROP, L.G_RX_DROP, svc, {**podlab, "interface": "eth0"}, [0.0] * len(grid))
        add(L.G_TX_DROP, L.G_TX_DROP, svc, {**podlab, "interface": "eth0"}, [0.0] * len(grid))
        ready = [1.0] * len(grid)
        if svc == target and ready_zero:
            ready = [0.0 if t0 + ready_zero[0] <= t < t0 + ready_zero[1] else 1.0 for t in grid]
        add(L.G_READY, "kube_pod_container_status_ready", svc, app, ready)
        if extra_app and extra_app == svc:
            add(L.G_CPU, L.G_CPU, svc, {**app, "container": "second"}, [0.2] * len(grid))
    # unresolved observability component and a raw-only pod name (resolved by the fallback)
    add(L.G_CPU, L.G_CPU, None, {"container": "loki", "pod": "loki-0"}, [9.0] * len(grid), canon=False)
    return pd.DataFrame(rows)


def span_rows(t0, err_from=None):
    rows = []
    for k, t in enumerate(np.arange(t0 + 1, t0 + RUN_S, 1.0)):
        base = f"{k:012x}"
        status = "STATUS_CODE_ERROR" if err_from is not None and t >= t0 + err_from and k % 2 else None
        for sid, parent, svc, kind, dur in (("a" + base[1:], None, None, "SPAN_KIND_CLIENT", 0.05),     # k6
                                            ("b" + base[1:], "a" + base[1:], "frontend", "SPAN_KIND_SERVER", 0.04),
                                            ("c" + base[1:], "b" + base[1:], "frontend", "SPAN_KIND_CLIENT", 0.02),
                                            ("d" + base[1:], "c" + base[1:], "checkoutservice", "SPAN_KIND_SERVER", 0.01)):
            start = int(t * 1e9)
            rows.append({"telemetry_source": "traces", "trace_id": base.zfill(32), "span_id": sid.zfill(16),
                         "parent_span_id": parent.zfill(16) if parent else None, "raw_span_json": "{}",
                         "raw_resource_json": "{}", "raw_service_id": svc or "k6", "canonical_service_id": svc,
                         "identity_resolution_method": "x", "mapping_version": 1, "span_name": "x", "span_kind": kind,
                         "start_time_unix_nano": start, "end_time_unix_nano": start + int(dur * 1e9),
                         "timestamp_valid": True, "status_code": status if svc == "checkoutservice" else None,
                         "resource_attributes_json": "{}", "span_attributes_json": "{}"})
    return pd.DataFrame(rows)


def log_rows(t0):
    msgs = [('{"severity":"info","message":"ok"}', "frontend", "info"),
            ('{"severity":"error","message":"bad"}', "currencyservice", "info"),
            ('{"level":"warn","message":"w"}', "adservice", "unknown"),
            ('{"level":50,"message":"pino"}', "paymentservice", "unknown"),
            ('{"severity":"info","error":"rpc failed"}', "checkoutservice", "info"),
            ("plain text line", "cartservice", "error"),
            ("plain text line", "cartservice", "info")]
    rows = []
    for k, t in enumerate(np.arange(t0 + 1, t0 + RUN_S, 2.0)):
        m, svc, lvl = msgs[k % len(msgs)]
        rows.append({"telemetry_source": "logs", "timestamp_unix_nano": int(t * 1e9), "raw_service_id": svc,
                     "canonical_service_id": svc, "identity_resolution_method": "x", "mapping_version": 1,
                     "message": m, "labels_json": json.dumps({"detected_level": lvl, "service_name": svc})})
    rows.append({"telemetry_source": "logs", "timestamp_unix_nano": int((t0 + 5) * 1e9), "raw_service_id": None,
                 "canonical_service_id": None, "identity_resolution_method": "unresolved", "mapping_version": 1,
                 "message": "other ns", "labels_json": "{}"})
    return pd.DataFrame(rows)


def write_run(root, run_id, t0, env, fault=None, metrics_kw=None, gaps=None, err_from=None):
    d = root / "runs" / run_id
    v = d / VIEW
    v.mkdir(parents=True)
    metric_rows(t0, **(metrics_kw or {})).to_parquet(v / "metrics.parquet", index=False)
    span_rows(t0, err_from).to_parquet(v / "traces.parquet", index=False)
    log_rows(t0).to_parquet(v / "logs.parquet", index=False)
    summ = {"metrics": {"rows": 1}}
    if gaps:
        summ["metrics"]["tolerated_missing_points_unix"] = gaps
    (v / "canonicalize-summary.json").write_text(json.dumps(summ))
    hashes = {f"{VIEW}/{n}.parquet": sha(v / f"{n}.parquet") for n in ("metrics", "traces", "logs")}
    (d / "pipeline-v2.json").write_text(json.dumps({"complete": True, "views": {"canonical": VIEW}, "hashes": hashes}))
    (d / "runtime.json").write_text(json.dumps({"run_id": run_id, "workload_started_at": iso(t0), "environment_id": env}))
    if fault:
        (d / "fault-record.json").write_text(json.dumps(fault))
    return d


def write_incident(root, fault_id, control_id, valid=True, impact=True, recovery=None):
    rec = "null" if recovery is None else f"'{iso(recovery)}'"
    (root / "incidents").mkdir(exist_ok=True)
    (root / "incidents" / f"inc-{fault_id}.yaml").write_text(f"""incident_id: inc-{fault_id}
run_id: {fault_id}
control_run_id: {control_id}
impact:
  confirmed: {str(impact).lower()}
recovery:
  transaction_observation:
    stable_at: {rec}
status: recovered
validity:
  injector_succeeded: true
  removal_confirmed: true
  runtime_assessment:
    phase_plan:
    - !!python/tuple
      - warmup
      - 180
  is_valid_run: {str(valid).lower()}
""")


def fault_record(t0, ftype, src=None, dst=None):
    return {"type": ftype, "started_at": iso(t0 + ONSET_OFF), "ended_at": iso(t0 + REMOVAL_OFF),
            "injection_requested_at": iso(t0 + ONSET_OFF - 1.0), "injector_status": "succeeded",
            "source_service": src, "destination_service": dst}


def make_pair(root, env, pair_id, ftype, kind, target, rep, t_fault, t_control, attempt=1, impact=True,
              metrics_kw=None, gaps=None):
    suffix = "" if attempt == 1 else f"-a{attempt}"
    f_id = pair_id + suffix
    c_id = pair_id.replace("linux-v1-", "linux-v1-control-", 1) + suffix
    src, dst = (target.split("->") if kind == "dependency_edge" else (None, None))
    write_run(root, f_id, t_fault, env, fault_record(t_fault, ftype, src, dst), metrics_kw, gaps,
              err_from=ONSET_OFF + 10)
    write_run(root, c_id, t_control, env)
    write_incident(root, f_id, c_id, impact=impact, recovery=t_fault + REMOVAL_OFF + 5)
    (root / "audits" / f"pair-{f_id}").mkdir(parents=True)
    return f_id, c_id


def make_dataset(base):
    """Two roots, 4 schedule pairs: A has #1 (cpu, eligible) and #2 (pod, attempt 1 failed -> attempt 2);
    B has #3 (delay edge, no impact -> ineligible) and #4 (traffic surge, eligible)."""
    a, b = base / "rootA", base / "rootB"
    T = 1_800_000_000.0
    make_pair(a, "206-40", "linux-v1-cpu-checkoutservice-r01", "cpu_saturation", "service_node", "checkoutservice",
              1, T, T + 3000)
    # pod pair: attempt 1 has only a control run folder and an incomplete audit, no incident
    (a / "runs" / "linux-v1-control-pod-checkoutservice-r01").mkdir(parents=True)
    (a / "audits" / "pair-linux-v1-pod-checkoutservice-r01").mkdir(parents=True)
    make_pair(a, "206-40", "linux-v1-pod-checkoutservice-r01", "pod_failure", "service_node", "checkoutservice",
              1, T + 6000, T + 9000, attempt=2,
              metrics_kw={"target": "checkoutservice", "pod_down": (615, 905), "ready_zero": (615, 905)})
    make_pair(b, "206-39", "linux-v1-delay-frontend-checkout-r02", "network_delay", "dependency_edge",
              "frontend->checkoutservice", 2, T + 12000, T + 15000, impact=False)
    make_pair(b, "206-39", "linux-v1-surge-l2-r03", "traffic_surge", "workload_entrypoint", "l2", 3,
              T + 18000, T + 21000)
    dec = a / "runs" / "_campaign" / "linux-v1"
    dec.mkdir(parents=True)
    (dec / "decisions.yaml").write_text("""retry_pairs:
  - pair_id: linux-v1-pod-checkoutservice-r01
    attempt: 2
    failure_cause: >-
      synthetic control export incomplete
    failed_audit: audits/pair-linux-v1-pod-checkoutservice-r01
    decided_on: "2026-11-18"
""")
    sched = base / "schedule.csv"
    lines = [HEADER]
    for i, (pid, ft, kind, tid, rep) in enumerate([
            ("linux-v1-cpu-checkoutservice-r01", "cpu_saturation", "service_node", "checkoutservice", 1),
            ("linux-v1-pod-checkoutservice-r01", "pod_failure", "service_node", "checkoutservice", 1),
            ("linux-v1-delay-frontend-checkout-r02", "network_delay", "dependency_edge", "frontend-checkout", 2),
            ("linux-v1-surge-l2-r03", "traffic_surge", "workload_entrypoint", "l2", 3)], 1):
        cid = pid.replace("linux-v1-", "linux-v1-control-", 1)
        lines.append(f"{i},{pid},{ft},{kind},{tid},{rep},fault_then_control,600,1,{pid},{cid},x,y")
    sched.write_text("\n".join(lines) + "\n")
    roots = [{"name": "206-40", "path": str(a), "environment_id": "206-40"},
             {"name": "206-39", "path": str(b), "environment_id": "206-39"}]
    roots_yaml = base / "roots.yaml"
    roots_yaml.write_text(json.dumps({"roots": roots}))   # JSON is valid YAML
    return roots_yaml, sched, T


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lv1-"))
        cls.roots, cls.sched, cls.T = make_dataset(cls.tmp)
        cls.cases = {c.case_id: c for c in L.list_cases(cls.roots, cls.sched, expected_pairs=4)}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def case(self, run_id):
        return self.cases[L.CASE_PREFIX + run_id]


class AdapterTests(Base):
    def test_name_mapping(self):
        self.assertEqual(L.service_name("checkoutservice", "x"), "checkoutservice")
        self.assertEqual(L.service_name(None, "redis-cart-7d8f9c6b5d-x2k4q"), "redis-cart")
        self.assertEqual(L.service_name(None, "frontendservice"), "frontend")
        self.assertEqual(L.service_name(None, "redis"), "redis-cart")
        self.assertIsNone(L.service_name(None, "loki-0"))
        self.assertIsNone(L.service_name(None, None))
        m = L.load_metrics(self.case("linux-v1-cpu-checkoutservice-r01"))
        self.assertEqual(set(m["service"]), set(CANDIDATES))           # loki dropped, all 11 present
        # pod-level and POD rows excluded from CPU: app container value only (~0.1, not +0.5 +0.5)
        self.assertLess(m[m["signal"] == "cpu_cores"]["value"].max(), 0.2)
        sp = L.load_spans(self.case("linux-v1-cpu-checkoutservice-r01"))
        self.assertEqual(set(sp["service"]), {"frontend", "checkoutservice"})   # k6 spans dropped
        root_spans = sp[sp["parent_service"].isna()]
        self.assertTrue((root_spans["service"] == "frontend").all())
        edge = sp[(sp["service"] == "checkoutservice")]
        self.assertTrue((edge["parent_service"] == "frontend").all())
        self.assertAlmostEqual(edge["parent_dur_s"].iloc[0], 0.02, places=6)

    def test_signals_and_rx_tx_not_collected(self):
        m = L.load_metrics(self.case("linux-v1-cpu-checkoutservice-r01"))
        self.assertEqual(set(m["signal"]), {"cpu_cores", "cpu_limit_ratio", "mem_limit_ratio", "net_drop_pkts"})
        lim = m[(m["signal"] == "cpu_limit_ratio")]["value"].dropna()
        self.assertTrue(np.allclose(lim, m[(m["signal"] == "cpu_cores")]["value"].dropna() / 0.5))
        self.assertTrue(np.allclose(m[m["signal"] == "mem_limit_ratio"]["value"].dropna(), 0.5))

    def test_pod_nan_kept(self):
        c = self.case("linux-v1-pod-checkoutservice-r01-a2")
        m = L.load_metrics(c)
        cpu = m[(m["signal"] == "cpu_cores") & (m["service"] == "checkoutservice")]
        rel = cpu["t"] - c.run_start
        down = cpu[(rel >= 620) & (rel < 900)]["value"]
        self.assertTrue(len(down) > 40 and down.isna().all())          # NaN, not 0 and not forward-filled
        self.assertTrue(cpu[(rel > 300) & (rel < 600)]["value"].notna().all())
        self.assertTrue(cpu[(rel > 910) & (rel < 1100)]["value"].notna().all())

    def test_tolerated_gap_nan(self):
        base = self.tmp / "gap"
        t0 = self.T
        gap_t = t0 + 300.0
        d = write_run(base, "linux-v1-x", t0, "206-40", metrics_kw={"gap": ("frontend", gap_t), "extra_app": "frontend"},
                      gaps={L.G_CPU: {"frontend": [gap_t]}})
        c = L.LinuxV1Case(case_id="x", root_cause="frontend", fault="cpu_saturation", repetition=1, onset=t0 + 600.3,
                          path=d, run_start=t0, view=VIEW)
        m = L.load_metrics(c)
        f = m[m["service"] == "frontend"].pivot(index="t", columns="signal", values="value")
        hit = f.index[(f.index >= gap_t) & (f.index < gap_t + 5)]
        self.assertEqual(len(hit), 1)
        # the second container still had a point there; the tolerated gap forces NaN anyway
        self.assertTrue(np.isnan(f.loc[hit[0], "cpu_cores"]) and np.isnan(f.loc[hit[0], "cpu_limit_ratio"]))
        self.assertFalse(np.isnan(f.loc[hit[0], "mem_limit_ratio"]))      # other group unaffected
        self.assertFalse(np.isnan(f.loc[hit[0] - 5, "cpu_cores"]))
        self.assertFalse(np.isnan(f.loc[hit[0] + 5, "cpu_cores"]))

    def test_logs_keep_text_and_err(self):
        lg = L.load_logs(self.case("linux-v1-cpu-checkoutservice-r01"))
        self.assertEqual(list(lg.columns), ["t", "service", "err", "message", "labels_json"])
        by = lg.groupby(["service", "message"])["err"].first()
        self.assertEqual(by[("frontend", '{"severity":"info","message":"ok"}')], 0)
        self.assertEqual(by[("currencyservice", '{"severity":"error","message":"bad"}')], 1)
        self.assertEqual(by[("adservice", '{"level":"warn","message":"w"}')], 1)
        self.assertEqual(by[("paymentservice", '{"level":50,"message":"pino"}')], 1)
        self.assertEqual(by[("checkoutservice", '{"severity":"info","error":"rpc failed"}')], 1)
        cart = lg[lg["service"] == "cartservice"]
        self.assertEqual(sorted(cart["err"].unique()), [0, 1])           # detected_level label for text lines
        self.assertNotIn(None, set(lg["service"]))
        self.assertEqual(list(L.load_logs(self.case("linux-v1-cpu-checkoutservice-r01"), keep_text=False).columns),
                         ["t", "service", "err"])


class CaseTests(Base):
    def test_times_and_ids(self):
        c = self.case("linux-v1-cpu-checkoutservice-r01")
        self.assertEqual(c.case_id, "lv1_linux-v1-cpu-checkoutservice-r01")
        self.assertAlmostEqual(c.onset - c.run_start, ONSET_OFF, places=3)
        self.assertEqual(c.onset_source, "started_at")
        self.assertAlmostEqual(c.injection - c.run_start, ONSET_OFF - 1.0, places=3)
        self.assertAlmostEqual(c.removal - c.run_start, REMOVAL_OFF, places=3)
        self.assertTrue(c.eligible)
        e = self.case("linux-v1-delay-frontend-checkout-r02")
        self.assertEqual((e.root_cause, e.edge_src, e.edge_dst), ("frontend->checkoutservice", "frontend", "checkoutservice"))
        self.assertFalse(e.eligible)
        self.assertEqual(len(self.cases), 8)
        s = self.case("linux-v1-surge-l2-r03")
        self.assertEqual((s.root_cause, s.target_kind, s.onset_source), ("workload->frontend", "workload_entrypoint", "started_at"))

    def test_sham_times_copied(self):
        for f_id, c_id in (("linux-v1-cpu-checkoutservice-r01", "linux-v1-control-cpu-checkoutservice-r01"),
                           ("linux-v1-pod-checkoutservice-r01-a2", "linux-v1-control-pod-checkoutservice-r01-a2")):
            f, c = self.case(f_id), self.case(c_id)
            self.assertEqual(c.kind, "control")
            self.assertEqual(c.onset_source, "sham_of_fault")
            self.assertAlmostEqual(c.run_start - f.run_start, 3000.0, places=3)
            for attr in ("onset", "injection", "removal", "recovery", "started_at"):
                self.assertAlmostEqual(getattr(c, attr) - c.run_start, getattr(f, attr) - f.run_start, places=6, msg=attr)
            self.assertEqual((c.pair_id, c.repetition, c.fault, c.root_cause), (f.pair_id, f.repetition, f.fault, f.root_cause))

    def test_pod_onset_ready_and_fallback(self):
        f = self.case("linux-v1-pod-checkoutservice-r01-a2")
        self.assertEqual(f.onset_source, "ready_zero")
        self.assertAlmostEqual(f.onset - f.run_start, 615.0, places=3)   # first 5 s grid point with Ready 0
        self.assertAlmostEqual(f.started_at - f.run_start, ONSET_OFF, places=3)
        # no Ready = 0 inside [started_at, ended_at] -> started_at, flagged
        self.assertIsNone(L.ready_onset(self.case("linux-v1-cpu-checkoutservice-r01").path, VIEW,
                                        "checkoutservice", f.started_at, f.removal))
        base = self.tmp / "podfb"
        t0 = self.T
        f_id, c_id = make_pair(base, "206-40", "linux-v1-pod-paymentservice-r03", "pod_failure", "service_node",
                               "paymentservice", 3, t0, t0 + 3000,
                               metrics_kw={"target": "paymentservice", "ready_zero": (950, 1000)})  # after ended_at
        pair = {"pair_id": "linux-v1-pod-paymentservice-r03", "fault_type": "pod_failure", "target_kind": "service_node",
                "target_id": "paymentservice", "repetition": 3, "schedule_index": 1, "attempt": 1, "fault_id": f_id,
                "control_id": c_id, "root": L.Root("206-40", base, "206-40"),
                "incident": L._incident(L.Root("206-40", base, "206-40"), f_id)}
        fc, cc = L.pair_cases(pair)
        self.assertEqual(fc.onset_source, "fallback_started_at")
        self.assertAlmostEqual(fc.onset - fc.run_start, ONSET_OFF, places=3)
        self.assertAlmostEqual(cc.onset - cc.run_start, ONSET_OFF, places=3)


class CheckTests(Base):
    def resolve(self, roots=None, expected=4, sched=None):
        return L.resolve_pairs(L.load_roots(roots or self.roots), L.read_schedule(sched or self.sched), expected)

    def test_adopted_attempt_excludes_failed(self):
        adopted, excluded = self.resolve()
        by = {a["pair_id"]: a for a in adopted}
        self.assertEqual(by["linux-v1-pod-checkoutservice-r01"]["attempt"], 2)
        self.assertEqual(by["linux-v1-pod-checkoutservice-r01"]["fault_id"], "linux-v1-pod-checkoutservice-r01-a2")
        self.assertEqual(len(excluded), 1)
        e = excluded[0]
        self.assertEqual((e["attempt"], e["fault_run_id"]), (1, "linux-v1-pod-checkoutservice-r01"))
        self.assertEqual(e["run_folders"], {"linux-v1-control-pod-checkoutservice-r01": "206-40"})
        self.assertIn("synthetic control export incomplete", e["failure_cause"])
        self.assertNotIn("lv1_linux-v1-pod-checkoutservice-r01", self.cases)

    def copy(self, name):
        dst = self.tmp / name
        shutil.copytree(self.tmp / "rootA", dst / "rootA")
        shutil.copytree(self.tmp / "rootB", dst / "rootB")
        roots = [{"name": "206-40", "path": str(dst / "rootA")}, {"name": "206-39", "path": str(dst / "rootB")}]
        return dst, roots

    def test_two_valid_attempts_refused(self):
        dst, roots = self.copy("twovalid")
        a = dst / "rootA"
        (a / "runs" / "linux-v1-pod-checkoutservice-r01").mkdir()
        write_incident(a, "linux-v1-pod-checkoutservice-r01", "linux-v1-control-pod-checkoutservice-r01")
        with self.assertRaisesRegex(ValueError, "valid attempts"):
            self.resolve(roots)

    def test_missing_failure_cause_stops(self):
        dst, roots = self.copy("nocause")
        (dst / "rootA" / "runs" / "_campaign" / "linux-v1" / "decisions.yaml").unlink()
        with self.assertRaisesRegex(L.DatasetCheckError, "failure cause"):
            self.resolve(roots)

    def test_run_id_collision_stops(self):
        dst, roots = self.copy("collision")
        (dst / "rootB" / "runs" / "linux-v1-control-cpu-checkoutservice-r01").mkdir()
        with self.assertRaisesRegex(L.DatasetCheckError, "collision"):
            self.resolve(roots)
        with self.assertRaisesRegex(L.DatasetCheckError, "collision"):
            B.main(["--roots", str(self._roots_file(dst, roots)), "--schedule", str(self.sched),
                    "--expected-pairs", "4", "--check-only"])

    def _roots_file(self, dst, roots):
        p = dst / "roots.yaml"
        p.write_text(json.dumps({"roots": roots}))
        return p

    def test_schedule_count_check(self):
        with self.assertRaisesRegex(L.DatasetCheckError, "expected 69"):
            self.resolve(expected=69)
        sched = self.tmp / "sched4.csv"
        sched.write_text(self.sched.read_text() + "5,linux-v1-cpu-paymentservice-r01,cpu_saturation,service_node,"
                         "paymentservice,1,fault_then_control,600,1,linux-v1-cpu-paymentservice-r01,"
                         "linux-v1-control-cpu-paymentservice-r01,x,y\n")
        with self.assertRaisesRegex(L.DatasetCheckError, "no valid attempt"):
            self.resolve(expected=5, sched=sched)

    def test_stray_run_folder_stops(self):
        dst, roots = self.copy("stray")
        (dst / "rootB" / "runs" / "linux-v1-cpu-adservice-r09").mkdir()
        with self.assertRaisesRegex(L.DatasetCheckError, "not belonging"):
            self.resolve(roots)

    def test_compute_hash(self):
        self.assertEqual(B.check_compute_hash(), B.FROZEN_COMPUTE_SHA256)
        fake = self.tmp / "compute.py"
        fake.write_text("# changed\n")
        with self.assertRaisesRegex(L.DatasetCheckError, "frozen"):
            B.check_compute_hash(fake)


class BuildTests(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.built = {cid: B.build_case(c) for cid, c in cls.cases.items()}

    def test_label_linux_v1_identity(self):
        self.assertIs(B.label_linux_v1, windows.label_linux_v1)
        for cid, (ranking, nodeview, det, det_in, edges, info) in self.built.items():
            c = self.cases[cid]
            for df in (det, det_in, edges):
                if len(df):
                    got = df[["meta_rel", "meta_label"]].drop_duplicates()
                    want = got["meta_rel"].map(lambda r: windows.label_linux_v1(r, c))
                    self.assertTrue((got["meta_label"].to_numpy() == want.to_numpy()).all(), cid)
            labels = set(edges["meta_label"])
            self.assertIn("baseline_stats", labels)
            self.assertIn("sham_active" if c.kind == "control" else "fault_active", labels)

    def test_detection_positive_negative_split(self):
        cpu = self.built["lv1_linux-v1-cpu-checkoutservice-r01"]
        det = cpu[2]
        pos = det[det["target"] == 1]
        self.assertTrue(len(pos) > 0 and (pos["meta_label"] == "fault_active").all())
        self.assertTrue((pos["meta_detection_role"] == "positive").all())
        self.assertEqual(set(det.loc[det["target"] == 0, "meta_label"]), {"normal", "recovered"})
        self.assertEqual(len(cpu[3]), 0)
        ctrl = self.built["lv1_linux-v1-control-cpu-checkoutservice-r01"][2]
        self.assertEqual(set(ctrl["meta_label"]), {"normal", "sham_active", "recovered"})
        self.assertTrue((ctrl["target"] == 0).all() and ctrl["meta_eligible"].all())
        inel = self.built["lv1_linux-v1-delay-frontend-checkout-r02"]
        self.assertNotIn("fault_active", set(inel[2]["meta_label"]))      # not in training/AUROC table
        self.assertTrue(len(inel[3]) > 0 and (inel[3]["meta_label"] == "fault_active").all())
        self.assertFalse(inel[3]["meta_eligible"].any())
        self.assertTrue((inel[3]["meta_detection_role"] == "ineligible").all())
        self.assertTrue(len(inel[2]) > 0 and (inel[2]["target"] == 0).all())  # its negatives stay
        for _, _, det, _, _, _ in self.built.values():
            self.assertFalse(set(det["meta_label"]) & {"transition", "recovering", "baseline_stats", "excluded"})
            self.assertTrue((det["meta_dataset"] == "linux-v1").all())

    def test_ranking_rows(self):
        r = self.built["lv1_linux-v1-cpu-checkoutservice-r01"][0]
        self.assertEqual(set(r["meta_label"]), {"fault_active"})
        self.assertEqual(set(r.loc[r["target"] == 1, "meta_candidate"]), {"checkoutservice"})
        self.assertEqual(r.groupby("meta_window")["target"].sum().unique().tolist(), [1])
        self.assertEqual(len(self.built["lv1_linux-v1-delay-frontend-checkout-r02"][0]), 0)   # ineligible
        self.assertEqual(len(self.built["lv1_linux-v1-delay-frontend-checkout-r02"][1]), 0)   # ineligible: no nodeview
        self.assertEqual(len(self.built["lv1_linux-v1-control-cpu-checkoutservice-r01"][0]), 0)

    def test_ranking_only_cpu_pod_one_target_per_window(self):
        ranking = pd.concat([b[0] for b in self.built.values() if len(b[0])], ignore_index=True)
        self.assertEqual(set(ranking["meta_fault"]), {"cpu_saturation", "pod_failure"})
        self.assertEqual(set(ranking["meta_target_kind"]), {"service_node"})
        per_window = ranking.groupby(["meta_case_id", "meta_window"])
        self.assertTrue((per_window["target"].sum() == 1).all())
        self.assertTrue((per_window.size() == len(CANDIDATES)).all())
        self.assertEqual(set(ranking["meta_case_id"]), {"lv1_linux-v1-cpu-checkoutservice-r01",
                                                        "lv1_linux-v1-pod-checkoutservice-r01-a2"})
        for cid, b in self.built.items():
            if len(b[0]):
                self.assertEqual(b[0].loc[b[0]["target"] == 1, "meta_candidate"].unique().tolist(),
                                 [self.cases[cid].root_cause])

    def test_nodeview_holds_edge_and_surge_only(self):
        nv = self.built["lv1_linux-v1-surge-l2-r03"][1]
        self.assertTrue(len(nv) > 0 and (nv["meta_label"] == "fault_active").all())
        self.assertTrue((nv["target"] == 0).all())
        self.assertEqual(len(self.built["lv1_linux-v1-surge-l2-r03"][0]), 0)
        for cid in ("lv1_linux-v1-cpu-checkoutservice-r01", "lv1_linux-v1-pod-checkoutservice-r01-a2"):
            self.assertEqual(len(self.built[cid][1]), 0)

    def test_rx_tx_features_nan(self):
        r, _, det = self.built["lv1_linux-v1-cpu-checkoutservice-r01"][:3]
        for col in ("f_cm_net_rx_pkts_dmean", "f_cm_net_rx_pkts_dmax", "f_cm_net_tx_pkts_dmean", "f_cm_net_tx_pkts_dmax"):
            self.assertIn(col, r.columns)
            self.assertTrue(r[col].isna().all(), col)
            for s in ("max", "mean"):
                self.assertTrue(det[f"{col}__{s}"].isna().all(), col)
        self.assertTrue(r["f_cm_net_drop_pkts_dmean"].notna().any() or r["f_cm_net_drop_pkts_zero_iqr"].notna().any())
        self.assertEqual(len([c for c in det.columns if c.startswith("f_")]), 58)

    def test_pod_case_metric_nan_in_features(self):
        r = self.built["lv1_linux-v1-pod-checkoutservice-r01-a2"][0]
        tgt = r[r["meta_candidate"] == "checkoutservice"]
        self.assertTrue(len(tgt) > 0 and tgt["f_cm_cpu_cores_dmean"].isna().all())   # NaN kept, RF maps to 0 later


class MainTests(Base):
    def test_build_resume_and_no_overwrite(self):
        out = self.tmp / "out"
        argv = ["--roots", str(self.roots), "--schedule", str(self.sched), "--out", str(out),
                "--expected-pairs", "4", "--workers", "2"]
        s = B.main(argv)
        for f in ("cases.parquet", "ranking.parquet", "ranking-nodeview.parquet", "detection.parquet", "detection-ineligible.parquet",
                  "edges.parquet", "folds.json", "build-summary.json", "build-progress.log"):
            self.assertTrue((out / f).exists(), f)
        self.assertEqual((s["cases"], s["fault_runs"], s["eligible_fault_runs"]), (8, 4, 3))
        rk, nv = pd.read_parquet(out / "ranking.parquet"), pd.read_parquet(out / "ranking-nodeview.parquet")
        self.assertEqual(set(rk["meta_fault"]), {"cpu_saturation", "pod_failure"})
        self.assertEqual(set(nv["meta_fault"]), {"traffic_surge"})
        self.assertEqual(s["ranking_nodeview_rows"], len(nv))
        self.assertEqual(s["excluded_attempts"][0]["fault_run_id"], "linux-v1-pod-checkoutservice-r01")
        self.assertEqual(s["onset_source"]["ready_zero"], 1)
        folds = json.loads((out / "folds.json").read_text())
        cases = pd.read_parquet(out / "cases.parquet")
        for _, g in cases.groupby("pair_id"):
            self.assertEqual(g["fold"].nunique(), 1)
            self.assertEqual(sorted(g["kind"]), ["control", "fault"])
        self.assertEqual(sorted(folds), ["1", "2", "3"])
        self.assertTrue(all(cid.startswith("lv1_") for ids in folds.values() for cid in ids))
        with self.assertRaises(SystemExit):
            B.main(argv)
        # resume: drop one finished part and the final outputs, rebuild only that case
        out2 = self.tmp / "out2"
        shutil.copytree(out / "_parts", out2 / "_parts")
        shutil.rmtree(out2 / "_parts" / "lv1_linux-v1-cpu-checkoutservice-r01")
        with self.assertRaises(SystemExit):
            B.main(argv[:5] + [str(out2)] + argv[6:])                   # not empty, no --resume
        s2 = B.main(argv[:5] + [str(out2)] + argv[6:] + ["--resume"])
        self.assertIn("1 to build", (out2 / "build-progress.log").read_text())
        pd.testing.assert_frame_equal(pd.read_parquet(out / "ranking.parquet"), pd.read_parquet(out2 / "ranking.parquet"))
        self.assertEqual(s2["detection"], s["detection"])

    def test_input_hash_verified(self):
        c = self.case("linux-v1-cpu-checkoutservice-r01")
        bad = L.LinuxV1Case(**{**c.__dict__, "view_hashes": {"metrics.parquet": "0" * 64}})
        with self.assertRaisesRegex(L.DatasetCheckError, "sha256"):
            B.build_case(bad)


if __name__ == "__main__":
    unittest.main()
