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
