import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_radar_measurement import (
    _bucket_for,
    _parse_dataset_payload,
    _parse_top_payload,
    build_radar_entries,
    fetch_ranking,
    main,
)
from unittest import mock


class CloudflareRadarPipelineTests(unittest.TestCase):
    def test_bucket_selection_uses_smallest_supported_bucket(self):
        self.assertEqual(_bucket_for(101), 200)
        self.assertEqual(_bucket_for(1000), 1000)
        self.assertEqual(_bucket_for(1001), 2000)

    def test_top_payload_keeps_ordered_rank_and_deduplicates_www(self):
        payload = {
            "success": True,
            "result": {"top_0": [
                {"rank": 1, "domain": "www.Example.com"},
                {"rank": 2, "domain": "example.com"},
                {"rank": 3, "domain": "test.cn"},
            ]},
        }
        result = _parse_top_payload(payload, 2)
        self.assertEqual(result, [
            {"domain": "example.com", "rank": 1},
            {"domain": "test.cn", "rank": 3},
        ])

    def test_bucket_payload_does_not_fabricate_popularity_rank(self):
        body = b"domain\nfoo.com\nhttps://www.bar.cn/path\nfoo.com\n"
        result = _parse_dataset_payload(body, 2)
        self.assertEqual(result[0]["domain"], "foo.com")
        self.assertIsNone(result[0]["rank"])
        self.assertEqual(result[1]["bucket_position"], 2)

    def test_fetch_top_uses_ordered_radar_endpoint(self):
        body = json.dumps({
            "success": True,
            "result": {"top_0": [
                {"rank": 1, "domain": "one.com"},
                {"rank": 2, "domain": "two.cn"},
            ]},
        }).encode("utf-8")
        with mock.patch(
                "scripts.run_radar_measurement._download", return_value=body) as download:
            domains, provenance = fetch_ranking("token", 2, location="CN")

        self.assertEqual([item["domain"] for item in domains], ["one.com", "two.cn"])
        self.assertTrue(provenance["ordered_rank"])
        self.assertIn("/radar/ranking/top?", download.call_args.args[0])
        self.assertIn("location=CN", download.call_args.args[0])

    def test_fetch_bucket_uses_unordered_dataset_endpoint(self):
        body = "\n".join(
            "site{}.example".format(index) for index in range(101)).encode()
        with mock.patch(
                "scripts.run_radar_measurement._download",
                return_value=body) as download:
            domains, provenance = fetch_ranking("token", 101)

        self.assertEqual(len(domains), 101)
        self.assertFalse(provenance["ordered_rank"])
        self.assertIn("/radar/datasets/ranking_top_200", download.call_args.args[0])

    def test_entries_label_radar_and_supplement_sources(self):
        entries = build_radar_entries(
            [{"domain": "example.com", "rank": None,
              "bucket_position": 1}],
            [("extra.cn", "cn.txt")])
        self.assertEqual(entries[0]["source"], "cloudflare_radar")
        self.assertEqual(entries[0]["rank"], None)
        self.assertEqual(entries[1]["source"], "supplement")

    def test_snapshot_shape_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps({
                "provenance": {"kind": "ordered_top"},
                "ranked": [{"domain": "example.com", "rank": 1}],
            }), encoding="utf-8")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[
                "ranked"][0]["domain"], "example.com")

    def test_skip_preflight_requires_a_snapshot(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--top", "1", "--skip-preflight"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
