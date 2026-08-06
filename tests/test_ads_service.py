import csv
import tempfile
import unittest
from pathlib import Path
from mcp_server.repositories import AdsRepository, DatasetNotFoundError
from mcp_server.services import AdsService

class AdsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.temp_dir.name) / "ads.csv"
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            fields = ["link", "title", "description", "source", "condition_rating"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="|")
            writer.writeheader()
            writer.writerows([
                {"link": "https://example/1", "title": "iPhone 15", "description": "Clean", "source": "facebook.csv", "condition_rating": "Good"},
                {"link": "https://example/2", "title": "iPhone 12", "description": "Cracked screen", "source": "olx.csv", "condition_rating": "Poor"},
                {"link": "https://example/3", "title": "iPhone 13", "description": "Clean", "source": "olx.csv", "condition_rating": "Good"},
            ])
        self.service = AdsService(AdsRepository(self.csv_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fetch_filters_and_paginates(self) -> None:
        result = self.service.fetch_ads(source="OLX.CSV", limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertTrue(result["has_more"])

    def test_text_search_is_case_insensitive(self) -> None:
        result = self.service.fetch_ads(query="CRACKED")
        self.assertEqual([row["link"] for row in result["items"]], ["https://example/2"])

    def test_get_ad_by_exact_link(self) -> None:
        self.assertEqual(self.service.get_ad("https://example/3")["title"], "iPhone 13")

    def test_rejects_invalid_pagination(self) -> None:
        with self.assertRaises(ValueError):
            self.service.fetch_ads(limit=0)

    def test_missing_file_has_clear_error(self) -> None:
        service = AdsService(AdsRepository(Path(self.temp_dir.name) / "missing.csv"))
        with self.assertRaises(DatasetNotFoundError):
            service.fetch_ads()
