import os
import json
import time
import unittest
from data_pipeline.stock_screener import StockScreener, CACHE_FILE

class TestScreenerCache(unittest.TestCase):
    def setUp(self):
        self.screener = StockScreener()

    def test_cache_hit_within_7_days(self):
        candidates = self.screener.get_top_candidates(count=15, cache_ttl_days=7)
        self.assertGreaterEqual(len(candidates), 10)
        self.assertIn("symbol", candidates[0])
        self.assertIn("rank", candidates[0])
        self.assertIn("momentum", candidates[0])
        self.assertIn("rvol", candidates[0])

    def test_select_active_targets(self):
        targets = self.screener.select_active_targets(n=2, count=15)
        self.assertEqual(len(targets), 2)
        self.assertIsInstance(targets[0], str)
        self.assertIsInstance(targets[1], str)

    def test_cache_file_format(self):
        self.assertTrue(os.path.exists(CACHE_FILE))
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        self.assertIn("last_updated", data)
        self.assertIn("expires_at", data)
        self.assertIn("top_candidates", data)
        self.assertGreaterEqual(len(data["top_candidates"]), 10)

if __name__ == "__main__":
    unittest.main()
