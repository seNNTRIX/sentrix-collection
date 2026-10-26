"""Profiles from scripts/generate-campaign.py through the recording stage, offline.

For every fault type (cpu, pod, delay, loss) and every surge level (l1-l3), a
generated linux-v1 profile is given fake fault/control run folders (no cluster,
no k6) and passed through the same consumers as a real pair: the fault record
as run-attended.py builds it (fault_manifest.render / workload_evidence.
confirm_surge), scripts/evaluate-pair.py and scripts/generate-incident-record.py.
The generator's scope_kind / target_kind / fault type values must be accepted
everywhere and come out in a yaml.safe_load-able incident record.
"""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from test_data_views import module
from evaluation_v2 import phase_plan
import fault_manifest
from view_integrity import file_hash
from workload_evidence import confirm_surge

ROOT = Path(__file__).resolve().parents[1]
gen = module("generate-campaign")
evaluate_pair = module("evaluate-pair")
incident = module("generate-incident-record")
ORDERS = ("control_then_fault", "fault_then_control")
EXPECTED = {  # fault type -> (target_kind, scope_kind, cause_family)
    "cpu_saturation": ("service_node", "service_instance", "resource"),
    "pod_failure": ("service_node", "service_instance", "availability"),
    "network_delay": ("dependency_edge", "dependency_edge", "network"),
    "packet_loss": ("dependency_edge", "dependency_edge", "network"),
    "traffic_surge": ("workload_entrypoint", "workload_entrypoint", "workload"),
}


def generated_cases():
    """One frozen linux-v1 fault profile per fault type and per surge level."""
    plan = yaml.safe_load((ROOT / "campaigns/linux-v1/campaign-plan.yaml").read_text(encoding="utf-8"))
    params = yaml.safe_load((ROOT / "campaigns/linux-v1/fault-params.yaml").read_text(encoding="utf-8"))
    profiles, schedule, _ = gen.build(plan, params, 20261023)
    cases = {}
    for row in sorted(schedule, key=lambda r: r["pair_id"]):
        key = row["target_id"] if row["fault_type"] == "traffic_surge" else row["fault_type"]
        cases.setdefault(key, (row, profiles[row["fault_run_id"]], profiles[row["control_run_id"]]))
    return cases


def transactions(run_id, profile, start, fail_fault_phase):
    rows, at = [], start
    for phase, duration, rate in phase_plan(profile):
        for i in range(round(duration * rate)):
            rows.append({"stage": "TRANSACTION_SUMMARY", "run_id": run_id, "transaction_id": f"{run_id}-{len(rows)}",
                         "event_time": (at + timedelta(seconds=i / rate)).isoformat(),
                         "success": not (fail_fault_phase and phase == "fault"), "duration_ms": 100,
                         "workload_scenario": "browse_cart_checkout_" + phase, "scenario_start_time": at.isoformat()})
        at += timedelta(seconds=duration)
    return rows


def write_run(runs, run_id, profile, start, fault_record_of=None):
    """A run folder that passes assess_run/validate_views; returns the run's end."""
    run = runs / run_id
    (run / "raw").mkdir(parents=True)
    duration = sum(d for _, d, _ in phase_plan(profile))
    rows = transactions(run_id, profile, start, fault_record_of is not None)
    end = start + timedelta(seconds=duration)
    (run / "transaction-results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    record = fault_record_of(run, rows) if fault_record_of else None
    if record:
        (run / "fault-record.json").write_text(json.dumps(record))
    manifest = {"run_id": run_id, "workload": {"profile": profile}, "evaluation_policy_version": "v3",
                "fault": {"injected": record is not None}}
    (run / "run-manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (run / "runtime.json").write_text(json.dumps({
        "run_id": run_id, "started_at": start.isoformat(), "finished_at": (end + timedelta(seconds=30)).isoformat(),
        "workload_rc": 0, "errors": [], "workload_elapsed_s": duration, "environment_id": "test-pc"}))
    (run / "workload-timeseries.json").write_text(json.dumps([{"dropped_iterations": 0}]))
    (run / "quality-report.json").write_text(json.dumps({
        "m1a_overall": "PASS", "m1a_gate_a_transaction_telemetry": {"status": "PASS"},
        "m1a_gate_b_k8s_event_pipeline": {"status": "PASS"}}))
    env = json.dumps({"fingerprint": "same-environment", "healthy": True, "restarts": {}})
    (run / "environment-before.json").write_text(env)
    (run / "environment-after.json").write_text(env)
    views = {"raw": "raw", "canonical": "canonical", "re2_compatible": "re2-compatible"}
    files = {"raw/export-manifest.json": json.dumps({"complete": True, "schema_version": 2}),
             "canonical/canonicalize-summary.json": "{}", "re2-compatible/projection-summary.json": "{}"}
    files.update({f"{v}/{n}.parquet": n for v in ("canonical", "re2-compatible") for n in ("metrics", "traces", "logs")})
    for rel, text in files.items():
        (run / rel).parent.mkdir(exist_ok=True)
        (run / rel).write_text(text)
    hashes = {rel: file_hash(run / rel) for rel in [*files, "transaction-results.jsonl", "run-manifest.yaml"]}
    (run / "pipeline-v2.json").write_text(json.dumps({"run_id": run_id, "generation": "v2", "complete": True,
                                                      "views": views, "hashes": hashes}))
    return end + timedelta(seconds=30)


def fault_record_like_run_attended(profile, run_id):
    """Same fields run-attended.py writes, per fault kind."""
    fault = profile["fault"]
    onset = profile["warmup_seconds"] + profile["baseline_seconds"]

    def build(run, rows):
        start = datetime.fromisoformat(rows[0]["event_time"])
        fs = start + timedelta(seconds=onset)
        fe = fs + timedelta(seconds=profile["fault_seconds"])
        name = run_id + "-fault"
        if fault["type"] == "traffic_surge":
            record = {"fault_kind": "workload", "fault_name": name, "type": fault["type"],
                      "root_cause_service": fault["root_cause_service"], "started_at": fs.isoformat(),
                      "ended_at": None, "removal_confidence": "scheduled_pending_actual_rate_validation",
                      "injector_status": "succeeded", "target_pod_uid": None}
            return confirm_surge(record, rows, profile)
        template, _ = fault_manifest.render((ROOT / fault["template"]).read_text(), fault, name,
                                            profile["fault_seconds"], cluster_ip_of=lambda svc: "10.43.0.10")
        return {"fault_kind": yaml.safe_load(template)["kind"].lower(), "fault_name": name, "type": fault["type"],
                "root_cause_service": fault["root_cause_service"], "started_at": fs.isoformat(),
                "ended_at": fe.isoformat(), "removal_confidence": "confirmed", "injector_status": "succeeded",
                "target_pod_uid": "pod-uid", "target_kind": fault.get("target_kind", "service_node"),
                "edge_id": fault.get("edge_id"), "source_service": fault.get("source_service"),
                "destination_service": fault.get("destination_service"), "params": fault.get("params", {})}
    return build


class IncidentPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = generated_cases()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_pair(self, row, fault_profile, control_profile, order):
        runs, incidents = self.root / order / "runs", self.root / order / "incidents"
        fault_profile = {**fault_profile, "pair_order": order}
        control_profile = {**control_profile, "pair_order": order}
        fault_id, control_id = row["fault_run_id"], row["control_run_id"]
        builder = fault_record_like_run_attended(fault_profile, fault_id)
        t0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
        if order == "control_then_fault":
            write_run(runs, fault_id, fault_profile, write_run(runs, control_id, control_profile, t0), builder)
        else:
            write_run(runs, control_id, control_profile, write_run(runs, fault_id, fault_profile, t0, builder))
        pair = evaluate_pair.evaluate(runs, fault_id, control_id, order)
        self.assertTrue(pair["valid"], pair["errors"])
        with redirect_stdout(io.StringIO()):
            incident.main(["--run-id", fault_id, "--incident-id", "inc-" + fault_id, "--experiment-id", "exp-" + fault_id,
                           "--control-run-id", control_id, "--runs-dir", str(runs), "--incidents-dir", str(incidents)])
        return yaml.safe_load((incidents / f"inc-{fault_id}.yaml").read_text(encoding="utf-8"))

    def test_generator_covers_four_fault_types_and_three_surge_levels(self):
        self.assertEqual(sorted(self.cases), ["cpu_saturation", "l1", "l2", "l3", "network_delay",
                                              "packet_loss", "pod_failure"])

    def test_every_generated_kind_reaches_a_valid_incident_record(self):
        for key, (row, fault_profile, control_profile) in self.cases.items():
            target_kind, scope_kind, family = EXPECTED[row["fault_type"]]
            self.assertEqual((row["target_kind"], fault_profile["fault"]["target_kind"],
                              fault_profile["fault"]["scope_kind"]), (target_kind, target_kind, scope_kind))
            for order in ORDERS:
                with self.subTest(case=key, order=order):
                    record = self.run_pair(row, fault_profile, control_profile, order)
                    self.assertTrue(record["validity"]["is_valid_run"], record["validity"])
                    self.assertEqual(record["fault"]["type"], row["fault_type"])
                    self.assertEqual(record["fault"]["scope_kind"], scope_kind)
                    self.assertEqual(record["fault"]["cause_family"], family)
                    self.assertEqual(record["status"], "recovered")
                    self.assertTrue(record["validity"]["control_match"]["valid"])

    def test_surge_profile_records_workload_entrypoint_like_entrypoint(self):
        row, fault_profile, control_profile = self.cases["l3"]
        record = self.run_pair(row, fault_profile, control_profile, "fault_then_control")
        fault = record["fault"]
        self.assertEqual((fault["scope_kind"], fault["cause_family"], fault["injection_layer"]),
                         ("workload_entrypoint", "workload", "Workload / L7"))
        self.assertIsNone(fault["chaos_mesh_object"])
        self.assertEqual(record["workload"]["target_rps"], fault_profile["target_rps"])

    def test_scope_that_does_not_fit_the_fault_type_is_refused(self):
        row, fault_profile, control_profile = self.cases["l1"]
        wrong = {**fault_profile, "fault": {**fault_profile["fault"], "scope_kind": "service_instance"}}
        with self.assertRaisesRegex(ValueError, "does not fit"):
            self.run_pair(row, wrong, control_profile, "control_then_fault")
        row, fault_profile, control_profile = self.cases["pod_failure"]
        unknown = {**fault_profile, "fault": {**fault_profile["fault"], "scope_kind": "service_node"}}
        with self.assertRaisesRegex(ValueError, "Unsupported root-cause scope"):
            self.run_pair(row, unknown, control_profile, "fault_then_control")


if __name__ == "__main__":
    unittest.main()
