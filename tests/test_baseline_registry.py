import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import refresh_baseline_channel_status as refresh


class RegistryTests(unittest.TestCase):
    def read(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.csv"
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=[
                    "canonical_channel_id", "channel_name", "handle", "portal_scope"
                ])
                writer.writeheader()
                writer.writerows(rows)
            with patch.object(refresh, "REGISTRY_CSV", path):
                return refresh.read_registry()

    def test_registry_can_grow_and_shrink(self):
        for count in (1, 31, 32, 34, 35):
            with self.subTest(count=count):
                rows = [{"canonical_channel_id": f"UC{i:022d}"} for i in range(count)]
                self.assertEqual(len(self.read(rows)), count)

    def test_exclusions_are_not_refreshed(self):
        rows = [
            {"canonical_channel_id": "UC" + "a" * 22},
            {"canonical_channel_id": "", "portal_scope": "exclude_adult"},
        ]
        self.assertEqual(len(self.read(rows)), 1)

    def test_empty_public_registry_is_rejected(self):
        for rows in ([], [{"canonical_channel_id": "x", "portal_scope": "exclude"}]):
            with self.subTest(rows=rows), self.assertRaises(SystemExit):
                self.read(rows)

    def test_blank_id_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.read([{"canonical_channel_id": "  "}])

    def test_duplicate_normalized_ids_are_rejected(self):
        with self.assertRaisesRegex(SystemExit, "duplicate"):
            self.read([{"canonical_channel_id": "UC123"}, {"canonical_channel_id": " UC123 "}])

    def test_ids_are_normalized_for_api_and_lookup(self):
        self.assertEqual(self.read([{"canonical_channel_id": " UC123 "}])[0]["canonical_channel_id"], "UC123")

    def test_checked_in_registry_is_valid(self):
        self.assertTrue(refresh.read_registry())


if __name__ == "__main__":
    unittest.main()
