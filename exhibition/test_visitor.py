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

    def test_replay_preserves_features_and_does_not_show_future(self):
        from playback import prepare,observation,epoch
        from visitor import DEMO,CASES
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json
        if not CASES: self.skipTest("Archive not installed")
        case=next(c for c in CASES if c["fault"]=="network_delay")
        with TemporaryDirectory() as temp:
            folder=Path(temp)/"8"
            last=prepare(DEMO,folder,case,1800000000)
            meta=json.loads((folder/"source.json").read_text())
            self.assertEqual(last,meta["last"]+meta["offset"])
            for path in folder.glob("[0-9]*.json"):
                end=int(path.stem)
                raw=json.loads((DEMO/"replay"/"1"/f"{end-meta['offset']}.json").read_text())
                rebased=json.loads(path.read_text())
                self.assertEqual(raw["features"],rebased["features"])
                self.assertEqual(epoch(rebased["windowEnd"]),end)
            now=1800000050
            rows=observation(folder,now,"frontend")
            self.assertTrue(all(epoch(r["timestamp"])<=now-30 for r in rows))
            self.assertTrue(any(r["p90"] is None for r in rows))
            self.assertTrue(any(r["p90"] is not None for r in rows))
            self.assertTrue(all(epoch(w["time"])<=now-30 for w in observation(folder,now)["history"]))
