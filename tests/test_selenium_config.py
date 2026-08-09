import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scrapperScripts import facebook_marketplace_scraper as facebook
from scrapperScripts import helper
from scrapperScripts import olx_scraper as olx


class SeleniumDockerConfigTest(unittest.TestCase):
    def assert_uses_docker_binaries(self, **kwargs) -> None:
        fake_driver = MagicMock()
        environment = {
            "CHROME_BINARY": "/usr/bin/chromium",
            "CHROMEDRIVER_PATH": "/usr/bin/chromedriver",
        }
        fake_service = MagicMock()
        with patch.dict(helper.os.environ, environment, clear=False), patch.object(
            helper, "Service", return_value=fake_service
        ) as service_class, patch.object(
            helper.webdriver, "Chrome", return_value=fake_driver
        ) as chrome:
            result = helper.build_driver(headless=True, **kwargs)

        self.assertIs(result, fake_driver)
        options = chrome.call_args.kwargs["options"]
        self.assertEqual(options.binary_location, "/usr/bin/chromium")
        service_class.assert_called_once_with(executable_path="/usr/bin/chromedriver")
        self.assertIs(chrome.call_args.kwargs["service"], fake_service)
        self.assertIn("--headless=new", options.arguments)
        self.assertIn("--no-sandbox", options.arguments)
        self.assertIn("--disable-dev-shm-usage", options.arguments)
        fake_driver.execute_cdp_cmd.assert_called_once()

    def test_facebook_uses_explicit_docker_binaries(self) -> None:
        self.assert_uses_docker_binaries(language="en-US")

    def test_olx_uses_explicit_docker_binaries(self) -> None:
        self.assert_uses_docker_binaries(profile_dir=None, language="id-ID")


class FacebookDetailExtractionTest(unittest.TestCase):
    def test_uses_longest_description_candidate(self) -> None:
        short = MagicMock(text="Short text")
        full = MagicMock(text="Complete Facebook Marketplace description")
        wait = MagicMock()
        wait.until.return_value = [short, full]

        with patch.object(facebook, "WebDriverWait", return_value=wait):
            description = facebook.extract_full_description(MagicMock())

        self.assertEqual(description, full.text)

    def test_scraped_price_is_always_nan(self) -> None:
        driver = MagicMock()
        wait = MagicMock()
        with patch.object(facebook, "WebDriverWait", return_value=wait), patch.object(
            facebook, "close_listing_overlay"
        ), patch.object(facebook, "extract_title", return_value="iPhone 13"), patch.object(
            facebook,
            "extract_full_description",
            return_value="Full description",
        ):
            row = facebook.scrape_ad_details(
                driver, "https://www.facebook.com/marketplace/item/123/"
            )

        self.assertEqual(row["price"], "NaN")
        self.assertEqual(row["title"], "iPhone 13")
        self.assertEqual(row["description"], "Full description")

    def test_csv_upsert_forces_nan_price(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "facebook.csv"
            link = "https://www.facebook.com/marketplace/item/123/"
            helper.upsert_csv_row(
                output,
                {
                    "link": link,
                    "title": "Old title",
                    "price": "Rp 1",
                    "description": "Old description",
                    "timestamp": "old",
                },
                facebook.canonical_item_url,
                facebook.normalize_csv_row,
            )
            helper.upsert_csv_row(
                output,
                {
                    "link": link,
                    "title": "New title",
                    "price": "Rp 2",
                    "description": "Full description",
                    "timestamp": "new",
                },
                facebook.canonical_item_url,
                facebook.normalize_csv_row,
            )

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="|"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["price"], "NaN")
            self.assertEqual(rows[0]["title"], "New title")


class OlxDescriptionExtractionTest(unittest.TestCase):
    def test_collects_visible_links_without_scrolling_or_clicking(self) -> None:
        driver = MagicMock()
        first = MagicMock()
        first.get_attribute.return_value = (
            "https://www.olx.co.id/item/iphone-iid-123?tracking=ignored"
        )
        duplicate = MagicMock()
        duplicate.get_attribute.return_value = (
            "https://www.olx.co.id/item/iphone-iid-123"
        )
        driver.find_elements.return_value = [first, duplicate]

        with patch.object(olx.time, "sleep") as sleep:
            links = olx.collect_visible_links(driver, pause=2.0)

        self.assertEqual(
            links, ["https://www.olx.co.id/item/iphone-iid-123"]
        )
        sleep.assert_called_once_with(2.0)
        driver.execute_script.assert_not_called()
        first.click.assert_not_called()
        duplicate.click.assert_not_called()

    def test_skips_onboarding_popup_before_collection(self) -> None:
        driver = MagicMock()
        skip_button = MagicMock()
        wait = MagicMock()
        wait.until.return_value = skip_button

        with patch.object(olx, "WebDriverWait", return_value=wait):
            skipped = olx.skip_onboarding_popup(driver)

        self.assertTrue(skipped)
        skip_button.click.assert_called_once_with()
        driver.execute_script.assert_not_called()

    def test_missing_onboarding_popup_does_not_block_collection(self) -> None:
        driver = MagicMock()
        with patch.object(olx, "WebDriverWait") as wait_class:
            wait_class.return_value.until.side_effect = olx.TimeoutException()
            skipped = olx.skip_onboarding_popup(driver)

        self.assertFalse(skipped)

    def test_onboarding_is_checked_only_once_per_browser(self) -> None:
        driver = MagicMock()
        skip_button = MagicMock()
        wait = MagicMock()
        wait.until.return_value = skip_button

        with patch.object(olx, "WebDriverWait", return_value=wait):
            self.assertTrue(olx.skip_onboarding_popup(driver))
            self.assertFalse(olx.skip_onboarding_popup(driver))

        wait.until.assert_called_once()

    def test_clicks_see_more_and_reads_description_from_modal(self) -> None:
        driver = MagicMock()
        button = MagicMock()
        modal = MagicMock()
        modal.get_attribute.return_value = "Complete modal description"
        wait = MagicMock()
        wait.until.side_effect = [button, modal]

        with patch.object(olx, "WebDriverWait", return_value=wait) as wait_class:
            description = olx.extract_full_description(driver)

        self.assertEqual(description, "Complete modal description")
        button.click.assert_called_once_with()
        modal.get_attribute.assert_called_once_with("innerText")
        self.assertEqual(wait_class.call_count, 2)

    def test_falls_back_to_inline_description_when_button_is_absent(self) -> None:
        driver = MagicMock()
        inline = MagicMock()
        inline.text = "Inline description"
        driver.find_elements.return_value = [inline]

        with patch.object(olx, "WebDriverWait") as wait_class:
            wait_class.return_value.until.side_effect = [
                olx.TimeoutException(),
                olx.TimeoutException(),
            ]
            description = olx.extract_full_description(driver)

        self.assertEqual(description, "Inline description")
        driver.find_elements.assert_called_with(
            olx.By.CSS_SELECTOR,
            olx.DETAIL_SELECTORS["description"][0],
        )

    def test_incomplete_description_is_retried_and_upserted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "olx.csv"
            link = "https://www.olx.co.id/item/iphone-iid-123"
            old_row = {
                "link": link,
                "title": "iPhone 13",
                "price": "Rp 7.000.000",
                "description": "Truncated description...",
                "timestamp": "old",
            }
            new_row = {
                **old_row,
                "description": "Complete modal description with all details",
                "timestamp": "new",
            }
            helper.upsert_csv_row(output, old_row, olx.canonical_item_url)
            self.assertEqual(
                olx.load_links_with_incomplete_description(output),
                {link},
            )
            helper.upsert_csv_row(output, new_row, olx.canonical_item_url)

            with output.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="|"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["description"], new_row["description"])
            self.assertEqual(
                olx.load_links_with_incomplete_description(output), set()
            )


if __name__ == "__main__":
    unittest.main()
