#!/usr/bin/env python3
"""Collect unique OLX item links with Selenium."""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from . import helper
except ImportError:  # Direct execution: python scrapperScripts/<script>.py
    import helper


DEFAULT_URL = (
    "https://www.olx.co.id/jakarta-dki_g2000007/handphone_c208/q-iphone"
    "?filter=condition_eq_bekas%2Cmake_eq_elektronik-gadget-handphone-apple_and_"
    "elektronik-gadget-handphone-samsung"
)
ITEM_SELECTOR = 'a[href*="/item/"]'
ONBOARDING_SKIP_SELECTOR = '[data-aut-id="onBoardingPopUpBtnSkip"]'
SEE_MORE_DESCRIPTION_SELECTOR = '[data-aut-id="seeMoreButtonDescription"]'
MODAL_DESCRIPTION_SELECTOR = '[data-aut-id="modalDescriptionContent"]'
DETAIL_SELECTORS = {
    "title": ('[data-aut-id="itemTitle"]', "main h1", "h1"),
    "price": ('[data-aut-id="itemPrice"]', '[data-testid="ad-price"]'),
    "description": (
        '[data-aut-id="itemDescriptionContent"]',
        '[data-aut-id="itemDescription"]',
        '[data-testid="ad-description"]',
    ),
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DETAIL_DRIVER_FACTORY = partial(
    helper.build_driver, profile_dir=None, language="id-ID"
)

def canonical_item_url(value: str) -> str | None:
    absolute = urljoin("https://www.olx.co.id", value.strip())
    parsed = urlparse(absolute)
    if "/item/" not in parsed.path:
        return None
    # Query strings commonly contain tracking data and are not part of identity.
    return f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.olx.co.id'}{parsed.path}"


def collect_visible_links(driver: webdriver.Chrome, pause: float) -> list[str]:
    """Collect only item links currently rendered on the search page."""
    time.sleep(pause)
    links: set[str] = set()
    for element in driver.find_elements(By.CSS_SELECTOR, ITEM_SELECTOR):
        href = element.get_attribute("href")
        if href and (canonical := canonical_item_url(href)):
            links.add(canonical)
    print(f"Collected {len(links)} unique links from the visible results.")
    return sorted(links)


def skip_onboarding_popup(driver: webdriver.Chrome, timeout: float = 5.0) -> bool:
    """Dismiss OLX's onboarding popup at most once for each browser."""
    if driver.__dict__.get("_olx_onboarding_checked", False):
        return False
    driver.__dict__["_olx_onboarding_checked"] = True
    try:
        button = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ONBOARDING_SKIP_SELECTOR))
        )
        button.click()
        return True
    except TimeoutException:
        return False


def first_element_text(driver: webdriver.Chrome, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            text = element.text.strip()
            if text:
                return text
    return ""


def extract_full_description(driver: webdriver.Chrome) -> str:
    """Expand an OLX description and return its complete modal text when possible."""
    try:
        button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SEE_MORE_DESCRIPTION_SELECTOR))
        )
        button.click()
    except TimeoutException:
        pass
    except (ElementClickInterceptedException, StaleElementReferenceException):
        buttons = driver.find_elements(By.CSS_SELECTOR, SEE_MORE_DESCRIPTION_SELECTOR)
        if buttons:
            driver.execute_script("arguments[0].click();", buttons[0])

    # The modal may already be open even if the button disappeared during a rerender.
    try:
        modal = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, MODAL_DESCRIPTION_SELECTOR)
            )
        )
        return (modal.get_attribute("innerText") or "").strip()
    except TimeoutException:
        return first_element_text(driver, DETAIL_SELECTORS["description"])


def scrape_ad_details(driver: webdriver.Chrome, link: str) -> dict[str, str]:
    print(f"Opening ad: {link}")
    driver.get(link)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    skip_onboarding_popup(driver)

    try:
        WebDriverWait(driver, 10).until(
            lambda browser: first_element_text(browser, DETAIL_SELECTORS["title"])
        )
    except TimeoutException:
        pass

    return {
        "link": link,
        "title": first_element_text(driver, DETAIL_SELECTORS["title"]),
        "price": first_element_text(driver, DETAIL_SELECTORS["price"]),
        "description": extract_full_description(driver),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def description_is_incomplete(description: str) -> bool:
    value = description.strip()
    return not value or value.endswith(("...", "…"))


def load_links_with_incomplete_description(csv_output: Path) -> set[str]:
    return {
        link
        for link, row in helper.read_csv_rows(
            csv_output, canonical_item_url
        ).items()
        if description_is_incomplete(row.get("description", ""))
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="OLX search URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "links" / "olx_item_links.txt",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "olx_ads.csv",
        help="Pipe-delimited CSV file for ad details",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=4,
        help="Chrome worker processes used to scrape ad details",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Seconds to let the initially visible results finish rendering",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=PROJECT_ROOT / ".olx-chrome-profile",
        help="Persistent Chrome profile directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.pause < 0 or args.detail_workers < 1:
        raise SystemExit("pause must be >= 0 and detail workers must be >= 1")

    known_links = helper.load_existing_links(args.output, canonical_item_url)
    csv_links = helper.load_csv_links(args.csv_output, canonical_item_url)
    incomplete_description_links = load_links_with_incomplete_description(
        args.csv_output
    )
    helper.store_links(args.output, known_links, [])
    driver = helper.build_driver(
        args.headless, profile_dir=args.profile_dir, language="id-ID"
    )

    try:
        print("Starting OLX search")
        driver.get(args.url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        skip_onboarding_popup(driver)
        found = collect_visible_links(driver, args.pause)
        new_count = helper.store_links(args.output, known_links, found)
    finally:
        driver.quit()

    detail_links = sorted((set(found) - csv_links) | incomplete_description_links)
    print(
        f"Scraping details for {len(detail_links)} ads with "
        f"up to {args.detail_workers} worker processes."
    )
    if incomplete_description_links:
        print(
            "Retrying full description extraction for "
            f"{len(incomplete_description_links)} existing ads."
        )
    rows, errors = helper.scrape_details_parallel(
        detail_links,
        args.detail_workers,
        args.headless,
        DETAIL_DRIVER_FACTORY,
        scrape_ad_details,
    )
    for number, row in enumerate(rows, start=1):
        helper.upsert_csv_row(args.csv_output, row, canonical_item_url)
        print(
            f"Saved ad details {number}/{len(rows)}: "
            f"{row['title'] or '[title unavailable]'}"
        )
    for link, error in errors:
        print(f"Warning: could not scrape {link}: {error}")

    print(
        f"Saved {new_count} new links. "
        f"{len(known_links)} unique OLX links are stored in {args.output}. "
        f"Ad details are stored in {args.csv_output}."
    )


if __name__ == "__main__":
    main()
