import unittest
from unittest.mock import MagicMock, patch

from scrapperScripts import facebook_marketplace_scraper as facebook
from scrapperScripts import olx_scraper as olx


class SeleniumDockerConfigTest(unittest.TestCase):
    def assert_uses_docker_binaries(self, module, *args) -> None:
        fake_driver = MagicMock()
        environment = {
            "CHROME_BINARY": "/usr/bin/chromium",
            "CHROMEDRIVER_PATH": "/usr/bin/chromedriver",
        }
        fake_service = MagicMock()
        with patch.dict(module.os.environ, environment, clear=False), patch.object(
            module, "Service", return_value=fake_service
        ) as service_class, patch.object(
            module.webdriver, "Chrome", return_value=fake_driver
        ) as chrome:
            result = module.build_driver(*args)

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
        self.assert_uses_docker_binaries(facebook, True)

    def test_olx_uses_explicit_docker_binaries(self) -> None:
        self.assert_uses_docker_binaries(olx, True, None)


if __name__ == "__main__":
    unittest.main()
