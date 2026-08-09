import argparse
import unittest
from unittest.mock import MagicMock, patch

import collect_analyze_data


class CollectDataTest(unittest.TestCase):
    @staticmethod
    def args() -> argparse.Namespace:
        return argparse.Namespace(
            headless=True,
            facebook_workers=2,
            olx_workers=3,
            model="test-model",
            batch_size=10,
            timeout=60.0,
            google_spreadsheet_id="spreadsheet-123",
            google_worksheet="Phone Ads",
        )

    def test_commands_include_both_scrapers_and_analyzer(self) -> None:
        scrapers, analyzer = collect_analyze_data.build_commands(self.args())
        self.assertEqual(set(scrapers), {"facebook", "olx"})
        self.assertIn("--headless", scrapers["facebook"])
        self.assertIn("--headless", scrapers["olx"])
        self.assertIn("analyze_data.py", " ".join(analyzer))
        self.assertIn("--google-spreadsheet-id", analyzer)
        self.assertIn("spreadsheet-123", analyzer)
        self.assertIn("--google-worksheet", analyzer)
        self.assertIn("Phone Ads", analyzer)

    @patch("collect_analyze_data.subprocess.run")
    @patch("collect_analyze_data.run_scrapers")
    def test_analysis_runs_after_scrapers(self, run_scrapers: MagicMock, run: MagicMock) -> None:
        collect_analyze_data.run_pipeline(self.args())
        run_scrapers.assert_called_once()
        run.assert_called_once()
        self.assertTrue(run.call_args.kwargs["check"])

    @patch("collect_analyze_data.subprocess.run")
    @patch("collect_analyze_data.run_scrapers", side_effect=RuntimeError("failed"))
    def test_analysis_does_not_run_after_scraper_failure(
        self, run_scrapers: MagicMock, run: MagicMock
    ) -> None:
        with self.assertRaises(RuntimeError):
            collect_analyze_data.run_pipeline(self.args())
        run.assert_not_called()
