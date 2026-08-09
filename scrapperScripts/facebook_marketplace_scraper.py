#!/usr/bin/env python3
"""Collect Facebook Marketplace ad links with Selenium."""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Mapping
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from . import helper
except ImportError:
    import helper


DEFAULT_URL = (
    "https://www.facebook.com/marketplace/jakarta/search"
    "?sortBy=creation_time_descend&query=iphone&exact=false"
)
ITEM_LINK_SELECTOR = 'a[href*="/marketplace/item/"]'
ITEM_PATH_PATTERN = re.compile(r"^/marketplace/item/([^/?#]+)")
CLOSE_OVERLAY_XPATH = "//div[@aria-label='Close']"
TITLE_CLASS = (
    "x193iq5w xeuugli x13faqbe x1vvkbs xlh3980 xvmahel x1n0sxbx "
    "x1lliihq x1s928wv xhkezso x1gmr53x x1cpjm7i x1fgarty x1943h6x "
    "xtoi2st x41vudc xngnso2 x1qb5hxa x1xlr1w8 xzsf02u"
)
TITLE_XPATH = f"//span[@class='{TITLE_CLASS}']"
DESCRIPTION_SELECTOR = 'span[dir="auto"] > span'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DETAIL_DRIVER_FACTORY = partial(helper.build_driver, language="en-US")


def normalize_csv_row(row: Mapping[str, str], canonical: str) -> dict[str, str]:
    """Normalize a Facebook row and enforce its unavailable-price marker."""
    return {
        "link": canonical,
        "title": row.get("title", ""),
        "price": "NaN",
        "description": row.get("description", ""),
        "timestamp": row.get("timestamp", ""),
    }

def canonical_item_url(value: str) -> str | None:
    """Return a canonical Marketplace item URL, or None for unrelated input."""
    absolute = urljoin("https://www.facebook.com", value.strip())
    match = ITEM_PATH_PATTERN.match(urlparse(absolute).path)
    if not match:
        return None
    return f"https://www.facebook.com/marketplace/item/{match.group(1)}/"


def collect_links(
    driver: webdriver.Chrome,
    url: str,
    pause: float,
) -> list[str]:
    driver.get(url)
    try:
        WebDriverWait(driver, 360).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
    except TimeoutException as exc:
        raise RuntimeError("Facebook did not finish loading.") from exc

    time.sleep(pause)
    links = {
        canonical
        for element in driver.find_elements(By.CSS_SELECTOR, ITEM_LINK_SELECTOR)
        if (href := element.get_attribute("href"))
        and (canonical := canonical_item_url(href)) is not None
    }
    print(f"Collected {len(links)} unique links from the initial results.")
    return sorted(links)


def close_listing_overlay(driver: webdriver.Chrome, timeout: float = 10.0) -> bool:
    """Close the Marketplace overlay exposed by the detail-page flow."""
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, CLOSE_OVERLAY_XPATH))
        )
        element.click()
        return True
    except TimeoutException:
        return False


def extract_title(driver: webdriver.Chrome, timeout: float = 10.0) -> str:
    element = WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.XPATH, TITLE_XPATH))
    )
    return (element.get_attribute("innerText") or "").strip()


def extract_full_description(
    driver: webdriver.Chrome, timeout: float = 15.0
) -> str:
    """Return the longest rendered description candidate used by Facebook."""
    elements = WebDriverWait(driver, timeout).until(
        EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, DESCRIPTION_SELECTOR)
        )
    )
    texts = [element.text.strip() for element in elements if element.text.strip()]
    return max(texts, key=len) if texts else ""


def scrape_ad_details(driver: webdriver.Chrome, link: str) -> dict[str, str]:
    print(f"Opening ad: {link}")
    driver.get(link)
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    close_listing_overlay(driver)
    return {
        "link": link,
        "title": extract_title(driver),
        "price": "NaN",
        "description": extract_full_description(driver),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def load_links_with_incomplete_details(csv_output: Path) -> set[str]:
    return {
        link
        for link, row in helper.read_csv_rows(
            csv_output, canonical_item_url, normalize_csv_row
        ).items()
        if not row.get("title", "").strip()
        or not row.get("description", "").strip()
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Marketplace search URL")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "links" / "facebook_marketplace_links.txt",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=PROJECT_ROOT / "data" / "facebook_marketplace_ads.csv",
        help="Pipe-delimited CSV file for Facebook ad details",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=2.0,
        help="Seconds to let the initial results finish rendering",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=4,
        help="Chrome worker processes used to scrape ad details",
    )
    parser.add_argument("--headless", action="store_true", help="Run Chrome headlessly")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.pause < 0 or args.detail_workers < 1:
        raise SystemExit("pause must be >= 0 and detail workers must be >= 1")

    known_links = helper.load_existing_links(args.output, canonical_item_url)

    csv_links = helper.load_csv_links(
        args.csv_output, canonical_item_url, normalize_csv_row
    )

    incomplete_links = load_links_with_incomplete_details(args.csv_output)

    helper.store_links(args.output, known_links, [])

    driver = helper.build_driver(headless=args.headless, language="en-US")

    try:
        links = collect_links(driver, args.url, args.pause)
        new_count = helper.store_links(args.output, known_links, links)

    finally:
        driver.quit()

    detail_links = sorted((set(links) - csv_links) | incomplete_links)
    print(
        f"Scraping details for {len(detail_links)} ads with "
        f"up to {args.detail_workers} worker processes."
    )
    rows, errors = helper.scrape_details_parallel(
        detail_links,
        args.detail_workers,
        args.headless,
        DETAIL_DRIVER_FACTORY,
        scrape_ad_details,
    )
    for number, row in enumerate(rows, start=1):
        helper.upsert_csv_row(
            args.csv_output,
            row,
            canonical_item_url,
            normalize_csv_row,
        )
        print(
            f"Saved ad details {number}/{len(rows)}: "
            f"{row['title'] or '[title unavailable]'}"
        )
    for link, error in errors:
        print(f"Warning: could not scrape {link}: {error}")

    print(
        f"Saved {new_count} new links. "
        f"{len(known_links)} unique Facebook Marketplace links are stored in "
        f"{args.output}. Ad details are stored in {args.csv_output}."
    )


if __name__ == "__main__":
    main()
