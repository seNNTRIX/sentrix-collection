"""Pre-pair reset of leaking services: fingerprint stability, Ready wait, queue order."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_data_views import module
import pod_reset

attended = module("run-attended")
campaign = module("run-campaign")
ROOT = Path(__file__).resolve().parents[1]
CFG = {"namespace": "sentrix", "services": ["currencyservice", "paymentservice"],
       "ready_timeout_seconds": 300, "poll_seconds": 2}


def pod(app, n, ready=True, restarts=0, terminating=False):
    meta = {"name": f"{app}-rs-{n}", "uid": f"{app}-uid-{n}", "labels": {"app": app, "pod-template-hash": "rs"}}
    if terminating:
        meta["deletionTimestamp"] = "2026-10-26T00:00:00Z"
    return {"metadata": meta, "status": {"phase": "Running", "containerStatuses": [
        {"name": "server", "ready": ready, "restartCount": restarts, "imageID": f"img/{app}@sha256:1"}]}}


class FakeCluster:
    """kubectl for run-attended.snapshot and pod_reset: delete replaces a pod by
    a new one (new name/uid, same image) from the unchanged template."""

    def __init__(self):
        self.pods = {app: [pod(app, 1, restarts=11)] for app in ("currencyservice", "paymentservice", "frontend")}
        self.deployment = {"kind": "Deployment", "metadata": {"name": "currencyservice"},
                           "spec": {"replicas": 1, "template": {"metadata": {"labels": {"app": "currencyservice"}},
                                                                "spec": {"containers": [{"image": "cur:v1"}]}}}}
        self.deleted = []
        self.not_ready_polls = 0

    def all_pods(self):
        return [p for pods in self.pods.values() for p in pods]

    def kube(self, *args, input=None):
        if args[:2] == ("get", "--raw"):
            return json.dumps({"items": [{"metadata": {"name": p["metadata"]["name"], "labels": p["metadata"]["labels"]},
                                          "timestamp": "t", "window": "15s",
                                          "containers": [{"name": "server", "usage": {"memory": "419430400"}}]}
                                         for p in self.all_pods()]})
        if args[:2] == ("get", "pods"):
            return json.dumps({"items": self.all_pods()})
        if args[:2] == ("get", "namespace"):
            return json.dumps({"metadata": {"uid": "ns-uid"}})
        if args[:2] == ("get", "nodes"):
            return json.dumps({"items": [{"metadata": {"uid": "node-uid"}}]})
        if args[0] == "get":
            return json.dumps({"items": [self.deployment]})
        raise AssertionError(args)

    def kubectl_json(self, *args):
        app = args[args.index("-l") + 1].split("=", 1)[1]
        pods = self.pods[app]
        if self.not_ready_polls and any(p["metadata"]["uid"].endswith("-2") for p in pods):
            self.not_ready_polls -= 1
            return {"items": [pod(app, 1, terminating=True), pod(app, 2, ready=False)]}
        return {"items": copy.deepcopy(pods)}

    def kubectl(self, *args):
        self.deleted.append(args)
        for name in args[args.index("--wait=false") + 1:]:
            app = name.split("-rs-")[0]
            self.pods[app] = [pod(app, 2)]
        return ""


class FingerprintTests(unittest.TestCase):
    def test_pod_delete_keeps_fingerprint_but_rollout_restart_would_not(self):
        cluster = FakeCluster()
        with patch.object(attended, "kube", cluster.kube):
            before = attended.snapshot()
            pod_reset.reset(CFG, cluster.kubectl_json, cluster.kubectl, sleep=lambda s: None, note=lambda m: None)
            after = attended.snapshot()
            self.assertNotEqual(before["restarts"], after["restarts"])  # new pods, new uids
            self.assertEqual(before["fingerprint"], after["fingerprint"])
            cluster.deployment["spec"]["template"]["metadata"]["annotations"] = {
                "kubectl.kubernetes.io/restartedAt": "2026-10-26T00:00:00Z"}
            self.assertNotEqual(attended.snapshot()["fingerprint"], before["fingerprint"])

    def test_snapshot_records_pod_memory_outside_fingerprint(self):
        cluster = FakeCluster()
        with patch.object(attended, "kube", cluster.kube):
            snap = attended.snapshot()
        mem = snap["pod_memory"]["pods"]["currencyservice-rs-1"]
        self.assertEqual((mem["app"], mem["total_mib"]), ("currencyservice", 400.0))
        self.assertEqual(attended.quantity_bytes("110620Ki"), 110620 * 1024)
        self.assertEqual(attended.quantity_bytes("409Mi"), 409 * 2**20)

    def test_metrics_api_error_is_recorded_not_raised(self):
        cluster = FakeCluster()

        def kube(*args, input=None):
            if args[:2] == ("get", "--raw"):
                raise RuntimeError("metrics API unavailable")
            return cluster.kube(*args)
        with patch.object(attended, "kube", kube):
            self.assertIn("unavailable", attended.snapshot()["pod_memory"]["error"])


class ResetTests(unittest.TestCase):
    def test_waits_until_new_pods_ready_and_old_gone(self):
        cluster = FakeCluster()
        cluster.not_ready_polls = 3
        sleeps, notes = [], []
        record = pod_reset.reset(CFG, cluster.kubectl_json, cluster.kubectl, sleep=sleeps.append, note=notes.append)
        self.assertEqual(len(cluster.deleted), 2)
        self.assertGreaterEqual(len(sleeps), 2)  # not-ready / terminating polls were waited out
        for svc in CFG["services"]:
            r = record["services"][svc]
            self.assertEqual([p["name"] for p in r["deleted"]], [f"{svc}-rs-1"])
            self.assertEqual([p["name"] for p in r["new"]], [f"{svc}-rs-2"])
            self.assertTrue(r["deleted_at"] <= r["ready_at"])
        self.assertEqual(sum("deleted" in n for n in notes), 2)
        self.assertEqual(sum("ready with new pod" in n for n in notes), 2)
        self.assertNotIn("frontend", record["services"])

    def test_timeout_raises(self):
        cluster = FakeCluster()
        cluster.not_ready_polls = 10**6
        ticks = iter(range(0, 10**6, 100))
        with self.assertRaisesRegex(TimeoutError, "not Ready within"):
            pod_reset.reset(CFG, cluster.kubectl_json, cluster.kubectl, clock=lambda: next(ticks),
                            sleep=lambda s: None, note=lambda m: None)

    def test_config_file(self):
        cfg = pod_reset.load_config(ROOT / "campaigns/linux-v1/pre-pair-reset.yaml")
        self.assertEqual(cfg["services"], ["currencyservice", "paymentservice"])
        self.assertIsNone(pod_reset.load_config(ROOT / "campaigns/linux-v1/missing.yaml"))
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp, "r.yaml")
            bad.write_text("services: []\n")
            with self.assertRaises(ValueError):
                pod_reset.load_config(bad)


class QueueOrderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.schedule = self.root / "schedule.json"
        pair = {"schedule_index": 1, "pair_id": "p1", "fault_type": "cpu_saturation", "fault_run_id": "f1",
                "control_run_id": "c1", "fault_profile": "x.json", "control_profile": "y.json",
                "pair_order": "control_then_fault", "onset_offset_seconds": 480}
        self.schedule.write_text(json.dumps({"campaign_id": "t", "draft": False, "pairs": [pair]}))
        (self.root / "pre-pair-reset.yaml").write_text("services: [currencyservice, paymentservice]\n")
        p = patch.object(campaign, "ROOT", self.root)
        p.start()
        self.addCleanup(p.stop)

    def run_queue(self, reset):
        events = []
        with patch.object(campaign, "gate", side_effect=lambda: events.append("gate") or []), \
             patch.object(campaign, "low_disk", return_value=[]), \
             patch.object(campaign.pod_reset, "reset", side_effect=reset(events)), \
             patch.object(campaign.time, "sleep", side_effect=lambda s: events.append(f"sleep {s}")), \
             patch.object(campaign.subprocess, "run",
                          side_effect=lambda cmd, **k: events.append(("pair", cmd)) or SimpleNamespace(returncode=0)), \
             redirect_stdout(io.StringIO()):
            rc = campaign.main(["--schedule", str(self.schedule)])
        return rc, events

    def test_reset_finishes_before_settle_and_is_logged(self):
        def reset(events):
            def fake(cfg, kubectl_json, kubectl, note=print, **kw):
                note("pre-pair reset: deleted currencyservice pod(s) cur-1 at T")
                events.append("reset done")
                return {"namespace": "sentrix", "services": {}, "started_at": "T"}
            return fake
        rc, events = self.run_queue(reset)
        self.assertEqual(rc, 0)
        self.assertEqual(events[:4], ["gate", "reset done", "sleep 300", "gate"])
        cmd = events[4][1]
        record = Path(cmd[cmd.index("--pre-pair-reset") + 1])
        self.assertEqual(json.loads(record.read_text())["pair_id"], "p1")
        log = (self.root / "runs/_campaign/t/queue.log").read_text()
        self.assertLess(log.index("pre-pair reset: deleted"), log.index("settle 300s"))

    def test_reset_timeout_stops_before_settle_and_pair(self):
        def reset(events):
            def fake(*a, **kw):
                raise TimeoutError("pre-pair reset: currencyservice not Ready within 300s")
            return fake
        rc, events = self.run_queue(reset)
        self.assertEqual(rc, 5)
        self.assertEqual(events, ["gate"])

    def test_matched_pair_copies_reset_record_into_audit(self):
        pair = module("run-matched-pair")
        record = {"services": {"currencyservice": {"deleted": [{"name": "cur-1"}], "deleted_at": "T1",
                                                   "new": [{"name": "cur-2"}], "ready_at": "T2"}}}
        reset_path = self.root / "reset.json"
        reset_path.write_text(json.dumps(record))
        profile = self.root / "p.json"
        profile.write_text(json.dumps({"pair_order": "control_then_fault"}))
        with patch.object(pair, "ROOT", self.root), \
             patch.object(pair.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            (self.root / "runs").mkdir()
            rc = pair.main(["--control-id", "c1", "--fault-id", "f1", "--control-profile", str(profile),
                            "--fault-profile", str(profile), "--pre-pair-reset", str(reset_path)])
        self.assertEqual(rc, 0)
        audit = self.root / "audits/pair-f1"
        self.assertEqual(json.loads((audit / "pre-pair-reset.json").read_text()), record)
        status = json.loads((audit / "status.json").read_text())
        self.assertEqual(status["pre_pair_reset"]["currencyservice"],
                         {"deleted": ["cur-1"], "deleted_at": "T1", "new": ["cur-2"], "ready_at": "T2"})


if __name__ == "__main__":
    unittest.main()
