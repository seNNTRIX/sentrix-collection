import io
import json
import stat
import unittest
from contextlib import ExitStack
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import visitor


class LiveRunStateTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "last-run.json"
        patches = ExitStack()
        self.addCleanup(patches.close)
        for key, value in (("state_file", self.path), ("state", {"mode":"live", "phase":"idle"}),
                           ("pending_live_write", None)):
            patches.enter_context(patch.object(visitor, key, value))
        self.worker = patches.enter_context(patch.object(visitor.threading, "Thread"))

    def handler(self, path):
        h = object.__new__(visitor.Handler)
        h.path = path
        h.headers = Message()
        h.headers["Host"] = visitor.live.AUTHORITY
        h.headers["Origin"] = visitor.ORIGIN
        h.send = Mock()
        return h

    def start(self, mode="live"):
        h = self.handler("/start")
        payload = json.dumps({"mode":mode, "case":"pod_failure", "source":"", "target":"paymentservice"}).encode()
        h.headers["Content-Type"] = "application/json"
        h.headers["Content-Length"] = str(len(payload))
        h.rfile = io.BytesIO(payload)
        h.do_POST()
        return h.send.call_args.args[0]

    def test_completed_live_run_survives_restart_and_replay(self):
        self.assertEqual(self.start(), 202)
        visitor.update(phase="done", applied="2026-11-24T00:04:00Z", recovered="2026-11-24T00:07:00Z",
                       decision="ANOMALY", job="opening-job", locationRank=2)
        actual = visitor.state.copy()
        self.assertEqual(visitor.restore_live(self.path), actual)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        with patch.object(visitor, "CASES", [{"fault":"pod_failure","root_cause":"paymentservice"}]):
            self.assertEqual(self.start("replay"), 202)
            visitor.update(phase="done", decision="NORMAL")
        self.assertEqual(visitor.restore_live(self.path), actual)

    def test_interrupted_observer_retains_evidence_without_inventing_recovery(self):
        self.assertEqual(self.start(), 202)
        visitor.update(applied="2026-11-24T00:04:00Z", decision="ANOMALY", job="opening-job")
        saved = visitor.restore_live(self.path)
        self.assertEqual(saved["phase"], "failed")
        self.assertIn("관측이 중단", saved["message"])
        self.assertEqual(saved["job"], "opening-job")
        self.assertNotIn("recovered", saved)
        self.worker.return_value.start.assert_called_once()

    def test_checkpoint_failure_preserves_previous_file_and_polls_retry(self):
        self.assertEqual(self.start(), 202)
        previous = self.path.read_bytes()
        with patch.object(visitor.os, "replace", side_effect=OSError("full")), self.assertLogs("visitor"):
            visitor.update(phase="done", decision="NORMAL")
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.handler("/state").do_GET()
        self.assertEqual(visitor.restore_live(self.path)["phase"], "done")
        self.assertIsNone(visitor.pending_live_write)

    def test_no_injection_when_configured_path_cannot_save_initial_request(self):
        with patch.object(visitor, "state_file", self.path / "missing" / "run"), self.assertLogs("visitor"):
            self.assertEqual(self.start(), 503)
        self.worker.assert_not_called()
        self.assertEqual(visitor.state["phase"], "idle")

    def test_missing_corrupt_or_disabled_storage_has_no_execution(self):
        self.assertEqual(visitor.restore_live(self.path)["phase"], "idle")
        self.path.write_text("{")
        with self.assertLogs("visitor"):
            self.assertEqual(visitor.restore_live(self.path)["phase"], "idle")
        with patch.object(visitor, "state_file", None):
            self.assertEqual(self.start(), 202)
            visitor.update(phase="done")
        self.assertEqual(self.path.read_text(), "{")
