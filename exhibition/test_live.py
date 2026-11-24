from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

import live
from visitor import location_rank


ZERO = datetime(2026, 11, 24, tzinfo=timezone.utc)


def at(seconds):
    return (ZERO + timedelta(seconds=seconds)).isoformat()


def window(end, decision="NORMAL", incident=None):
    return {"windowStart": at(end-30), "windowEnd": at(end), "createdAt": at(end+10), "finishedAt": at(end+33),
            "status":"SUCCEEDED", "decision":decision, "jobId":f"job{end}", "modelVersion":"model", "incidentId":incident}


def opening(w):
    return {"incidentId":w["incidentId"],"result":{**w,"score":0.8,"candidates":[{"kind":"NODE","service":"emailservice","rank":1}]}}


class FirstAlarmTest(unittest.TestCase):
    def read(self, rows, api):
        return live.model_observation(rows, at(37), at(217), window(30), api, "paymentservice", location_rank)

    def test_first_partial_uses_stored_result_without_counting_it_as_full_exposure(self):
        early, late = window(60,"ANOMALY","i"), window(120,"ANOMALY","i")
        api=Mock(return_value=opening(early))
        result=self.read([late, window(90), early],api)
        self.assertEqual((result["job"],result["window"],result["detected"]),(early["jobId"],at(60),at(93)))
        self.assertTrue(result["partialWindow"])
        self.assertEqual(result["windowsChecked"],0)
        self.assertIsNone(result["locationRank"])
        api.assert_called_once_with(live.CORE+"/incidents/i/rca?at=first")

    def test_waits_for_earlier_pending_job_and_rechecks_first_result(self):
        early,late=window(60,"ANOMALY","i"),window(90,"ANOMALY","i")
        api=Mock(return_value=opening(early))
        self.assertNotIn("job",self.read([late,dict(early,decision=None,status="RUNNING")],api))
        api.assert_not_called()
        self.assertNotIn("job",self.read([late],api))
        self.assertEqual(self.read([late,early],api)["job"],early["jobId"])

    def test_recovery_overlap_can_alarm_but_normal_counts_need_both_exposed_windows(self):
        rows=[window(30),window(60),window(90),window(120,"ABSTAIN"),window(240),window(270,"ANOMALY","post")]
        api=Mock()
        counts=self.read(rows,api)
        self.assertEqual((counts["normalWindows"],counts["abstainedWindows"],counts["windowsChecked"]),(1,1,2))
        api.assert_not_called()
        last=window(240,"ANOMALY","tail")
        api.return_value=opening(last)
        result=self.read([last,*rows[:-2]],api)
        self.assertTrue(result["partialWindow"])
        self.assertEqual(result["job"],"job240")

    def test_existing_incident_is_not_attributed_to_experiment(self):
        stale=window(60,"ANOMALY","old")
        fresh=window(120,"ANOMALY","new")
        results={"old":opening(window(30,"ANOMALY","old")), "new":opening(fresh)}
        def api(key): return results[key.split("/incidents/")[1].split("/")[0]]
        result=self.read([fresh,stale],api)
        self.assertEqual(result["job"],fresh["jobId"])
        self.assertEqual(result["beforeJob"],"job30")
        self.assertFalse(result["partialWindow"])

    @patch.object(live, "active_experiments", return_value=[])
    @patch.object(live, "kube")
    @patch.object(live.time, "time", return_value=ZERO.timestamp()+34)
    def test_normal_preflight_refuses_still_open_incident(self, _clock,kube,_active):
        settings={"enabled":True,"executionStatus":"SCHEDULED"}
        normal=window(30)
        api=Mock(side_effect=[settings,{"openIncidents":1,"recentWindows":[normal]}])
        with self.assertRaisesRegex(ValueError,"진행 중인 장애"):
            live.observe(live.build("pod_failure","","paymentservice","test"),api,Mock(),location_rank)
        kube.assert_not_called()
