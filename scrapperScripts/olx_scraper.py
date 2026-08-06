#!/usr/bin/env python3
"""Collect unique OLX item links with Selenium."""

from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_URL = (
    "https://www.olx.co.id/jakarta-dki_g2000007/handphone_c208/q-iphone"
    "?filter=condition_eq_bekas%2Cmake_eq_elektronik-gadget-handphone-apple_and_"
    "elektronik-gadget-handphone-samsung"
)
ITEM_SELECTOR = 'a[href*="/item/"]'
LOAD_MORE_SELECTOR = '[data-aut-id="btnLoadMore"]'
DETAIL_SELECTORS = {
    "title": ('[data-aut-id="itemTitle"]', "main h1", "h1"),
    "price": ('[data-aut-id="itemPrice"]', '[data-testid="ad-price"]'),
    "description": (
        '[data-aut-id="itemDescriptionContent"]',
        '[data-aut-id="itemDescription"]',
        '[data-testid="ad-description"]',
    ),
}
CSV_FIELDS = ("link", "title", "price", "description", "timestamp")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_driver(headless: bool, profile_dir: Path | None) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    if profile_dir:
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument("--lang=id-ID")
    return webdriver.Chrome(options=options)


def canonical_item_url(value: str) -> str | None:
    absolute = urljoin("https://www.olx.co.id", value.strip())
    parsed = urlparse(absolute)
    if "/item/" not in parsed.path:
        return None
    # Query strings commonly contain tracking data and are not part of identity.
    return f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.olx.co.id'}{parsed.path}"


def collect_visible_links(driver: webdriver.Chrome, links: set[str]) -> int:
    before = len(links)
    for element in driver.find_elements(By.CSS_SELECTOR, ITEM_SELECTOR):
        href = element.get_attribute("href")
        if href and (canonical := canonical_item_url(href)):
            links.add(canonical)
    return len(links) - before


def expand_and_collect(
    driver: webdriver.Chrome,
    pause: float,
    min_load_more_clicks: int,
    stable_rounds: int,
    max_load_more: int,
) -> list[str]:
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    successful_clicks = 0
    unavailable_rounds = 0

    for round_number in range(1, max_load_more + 1):
        driver.execute_script("window.scrollTo(0, document.documentElement.scrollHeight)")
        time.sleep(pause)

        buttons = driver.find_elements(By.CSS_SELECTOR, LOAD_MORE_SELECTOR)
        clickable = next(
            (button for button in buttons if button.is_displayed() and button.is_enabled()),
            None,
        )
        if clickable is not None:
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", clickable
                )
                clickable.click()
                successful_clicks += 1
                unavailable_rounds = 0
                time.sleep(pause)
            except (ElementClickInterceptedException, StaleElementReferenceException):
                # Re-find on the next round; banners and rerenders can briefly
                # intercept or replace OLX's button.
                pass
        else:
            unavailable_rounds += 1

        print(
            f"Load round {round_number}/{max_load_more}: "
            f"Muat Lainnya clicks {successful_clicks}/{min_load_more_clicks}"
        )
        # The requested click count is exact: do not keep clicking merely
        # because OLX still shows another load-more button.
        if successful_clicks >= min_load_more_clicks:
            break
        if unavailable_rounds >= stable_rounds:
            break

    if successful_clicks < min_load_more_clicks:
        raise RuntimeError(
            f"OLX only provided {successful_clicks} successful 'Muat Lainnya' clicks; "
            f"at least {min_load_more_clicks} were required."
        )

    # Extraction deliberately starts only after the requested number of
    # successful load-more clicks is complete.
    links: set[str] = set()
    collect_visible_links(driver, links)
    print(f"Expansion complete. Collected {len(links)} unique item links.")
    return sorted(links)


def load_existing_links(output: Path) -> set[str]:
    if not output.exists():
        return set()
    return {
        canonical
        for line in output.read_text(encoding="utf-8").splitlines()
        if (canonical := canonical_item_url(line)) is not None
    }


def store_links(output: Path, known: set[str], found: list[str]) -> int:
    before = len(known)
    known.update(found)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{link}\n" for link in sorted(known)), encoding="utf-8")
    return len(known) - before


def first_element_text(driver: webdriver.Chrome, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            text = element.text.strip()
            if text:
                return text
    return ""


def scrape_ad_details(driver: webdriver.Chrome, link: str) -> dict[str, str]:
    print(f"Opening ad: {link}")
    driver.get(link)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))

    # Give client-rendered detail fields a short opportunity to appear.
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
        "description": first_element_text(driver, DETAIL_SELECTORS["description"]),
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def load_csv_links(csv_output: Path) -> set[str]:
    if not csv_output.exists() or csv_output.stat().st_size == 0:
        return set()

    first_line = csv_output.read_text(encoding="utf-8").splitlines()[0]
    existing_delimiter = "|" if "|" in first_line else ","
    with csv_output.open("r", encoding="utf-8", newline="") as file:
        rows_by_link: dict[str, dict[str, str]] = {}
        for row in csv.DictReader(file, delimiter=existing_delimiter):
            canonical = canonical_item_url(row.get("link", ""))
            if canonical is not None:
                rows_by_link[canonical] = {
                    "link": canonical,
                    "title": row.get("title", ""),
                    "price": row.get("price", ""),
                    "description": row.get("description", ""),
                    "timestamp": row.get("timestamp", ""),
                }

    # Normalize older comma-delimited files and remove any duplicate rows.
    with csv_output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, delimiter="|")
        writer.writeheader()
        writer.writerows(rows_by_link.values())
    return set(rows_by_link)


def append_csv_row(csv_output: Path, row: dict[str, str]) -> None:
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not csv_output.exists() or csv_output.stat().st_size == 0
    with csv_output.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, delimiter="|")
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def scrape_ad_chunk(
    links: list[str], headless: bool
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Scrape one link chunk in a dedicated process and Chrome instance."""
    rows: list[dict[str, str]] = []
    errors: list[tuple[str, str]] = []
    driver = build_driver(headless=headless, profile_dir=None)
    try:
        for link in links:
            try:
                rows.append(scrape_ad_details(driver, link))
            except Exception as exc:
                errors.append((link, str(exc)))
    finally:
        driver.quit()
    return rows, errors


def scrape_details_parallel(
    links: list[str], workers: int, headless: bool
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    if not links:
        return [], []
    worker_count = min(workers, len(links))
    chunks = [links[index::worker_count] for index in range(worker_count)]
    rows: list[dict[str, str]] = []
    errors: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(scrape_ad_chunk, chunk, headless) for chunk in chunks
        ]
        for future in as_completed(futures):
            chunk_rows, chunk_errors = future.result()
            rows.extend(chunk_rows)
            errors.extend(chunk_errors)
    return rows, errors


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
        help="CSV file for ad details",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=4,
        help="Chrome worker processes used to scrape ad details",
    )
    parser.add_argument("--pause", type=float, default=2.0, help="Load/click pause")
    parser.add_argument(
        "--min-load-more-clicks",
        "--load-more-clicks",
        dest="min_load_more_clicks",
        type=int,
        default=2,
        help="Exact number of successful Muat Lainnya clicks per refresh",
    )
    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=3,
        help="Fail after this many rounds without an available load-more button",
    )
    parser.add_argument(
        "--max-load-more",
        type=int,
        default=5,
        help="Maximum Muat Lainnya attempts per refresh",
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
    if (
        args.pause < 0
        or args.detail_workers < 1
        or args.min_load_more_clicks < 1
        or args.stable_rounds < 1
        or args.max_load_more < 1
        or args.max_load_more < args.min_load_more_clicks
    ):
        raise SystemExit(
            "pause must be >= 0; detail workers and round limits must be >= 1, and max-load-more "
            "must be at least the requested clicks"
        )

    known_links = load_existing_links(args.output)
    csv_links = load_csv_links(args.csv_output)
    store_links(args.output, known_links, [])
    driver = build_driver(args.headless, args.profile_dir)

    try:
        print("Starting OLX search")
        driver.get(args.url)
        found = expand_and_collect(
            driver,
            args.pause,
            args.min_load_more_clicks,
            args.stable_rounds,
            args.max_load_more,
        )
        # Persist the URL set before navigating away from the search results.
        new_count = store_links(args.output, known_links, found)
    finally:
        driver.quit()

    detail_links = sorted(set(found) - csv_links)
    print(
        f"Scraping details for {len(detail_links)} ads with "
        f"up to {args.detail_workers} worker processes."
    )
    rows, errors = scrape_details_parallel(
        detail_links, args.detail_workers, args.headless
    )
    for number, row in enumerate(rows, start=1):
        append_csv_row(args.csv_output, row)
        csv_links.add(row["link"])
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
