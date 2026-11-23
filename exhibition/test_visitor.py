import unittest
from visitor import location_rank


class LocationRankTest(unittest.TestCase):
    def test_distinguishes_node_and_directed_edge(self):
        candidates = [
            {"kind": "EDGE", "source": "frontend", "target": "catalog", "rank": 1},
            {"kind": "NODE", "service": "catalog", "rank": 3},
        ]
        self.assertEqual(location_rank(candidates, "frontend->catalog"), 1)
        self.assertEqual(location_rank(candidates, "catalog"), 3)
        self.assertIsNone(location_rank(candidates, "catalog->frontend"))
        self.assertIsNone(location_rank([], "catalog"))

class ExperimentTest(unittest.TestCase):
    def test_every_declared_subject(self):
        from visitor import selection
        from live import SERVICES, EDGES
        self.assertEqual(len(SERVICES), 11)
        self.assertEqual(sum(map(len, EDGES.values())), 15)
        for fault in ("cpu_saturation","pod_failure"):
            for node in SERVICES:
                spec=selection({"mode":"live","case":fault,"source":"","target":node}, "test")[0]["spec"]
                self.assertEqual(spec["selector"]["labelSelectors"]["app"],node)
        for fault in ("network_delay","packet_loss"):
            for source,targets in EDGES.items():
                for target in targets:
                    spec=selection({"mode":"live","case":fault,"source":source,"target":target}, "test")[0]["spec"]
                    self.assertEqual(spec["target"]["selector"]["labelSelectors"]["app"],target)
                    self.assertEqual(spec["selector"]["labelSelectors"]["app"],source)
                    self.assertEqual(spec["direction"],"to")

    def test_invalid_or_unrecorded_path(self):
        from visitor import selection
        for mode,source,target in [("live","productcatalogservice","frontend"),("replay","checkoutservice","productcatalogservice")]:
            with self.assertRaises(ValueError):
                selection({"mode":mode,"case":"network_delay","source":source,"target":target}, "test")

    def test_replay_samples_keep_gaps(self):
        from visitor import DEMO,CASES
        from series import replay_series
        if not CASES: self.skipTest("No replay fixtures installed")
        samples=replay_series({"fault":"network_delay"},CASES,DEMO)
        self.assertEqual(samples["subject"],"frontend->productcatalogservice")
        self.assertTrue(any(v is None for _,v in samples["points"]))
        import json
        t=CASES["network_delay"]["during"]["windowEnd_unix"]
        features=json.loads((DEMO/"replay"/"1"/(str(t)+".json")).read_text())["features"]
        edge=next(e for e in features["edges"] if e["source"]=="frontend" and e["target"]=="productcatalogservice")
        self.assertAlmostEqual(dict(samples["points"])[t],edge["p90"]*1000)

    def test_zero_and_missing_service_metrics(self):
        from series import live_series
        def api(url):
            self.assertIn("service=checkoutservice",url)
            return {"environmentId":1,"service":"checkoutservice","metric":"error_ratio","points":[
                {"timestamp":"2026-11-23T00:00:10Z","value":None},
                {"timestamp":"2026-11-23T00:00:20Z","value":0.0},
                {"timestamp":"2026-11-23T00:00:30Z","value":0.04}]}
        actual=live_series({"location":"checkoutservice->paymentservice","fault":"packet_loss"},api)
        self.assertEqual([p[1] for p in actual["points"]],[None,0,4])
