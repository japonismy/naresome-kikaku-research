import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import refresh_youtube_current_stats as refresh


class CurrentStatsRegistryTests(unittest.TestCase):
    def read(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=["channel_name", "portal_scope"])
                writer.writeheader()
                writer.writerows(rows)
            with patch.object(refresh, "BASELINE_CHANNELS_CSV", path):
                return refresh.read_allowed_channels()

    def test_registry_can_grow_and_shrink(self):
        for count in (1, 31, 32, 34, 35):
            with self.subTest(count=count):
                self.assertEqual(len(self.read([{"channel_name": f"Channel{i}"} for i in range(count)])), count)

    def test_exclusions_and_normalization(self):
        self.assertEqual(self.read([
            {"channel_name": " Channel ONE "},
            {"channel_name": "", "portal_scope": "exclude_adult"},
        ]), {"channelone"})

    def test_empty_and_blank_names_are_rejected(self):
        for rows in ([], [{"channel_name": " "}], [{"channel_name": "x", "portal_scope": "exclude"}]):
            with self.subTest(rows=rows), self.assertRaises(SystemExit):
                self.read(rows)

    def test_normalized_duplicates_are_rejected(self):
        with self.assertRaisesRegex(SystemExit, "duplicate"):
            self.read([{"channel_name": "Channel One"}, {"channel_name": "CHANNELONE"}])

    def test_checked_in_registry_is_valid(self):
        self.assertTrue(refresh.read_allowed_channels())
