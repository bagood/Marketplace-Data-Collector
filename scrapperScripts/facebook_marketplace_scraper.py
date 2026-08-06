#!/usr/bin/env python3
"""Collect Facebook Marketplace links with Selenium."""

from __future__ import annotations

import argparse
import csv
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_URL = "https://www.facebook.com/marketplace/jakarta/search?sortBy=creation_time_descend&query=iphone&exact=false"
CLASS_SELECTOR = ".x1mfogq2.xsfy40s.x1cnzs8.xshsftc.x1cbb1x2"
ITEM_LINK_SELECTOR = 'a[href*="/marketplace/item/"]'
ITEM_PATH_PATTERN = re.compile(r"^/marketplace/item/([^/?#]+)")
PRICE_PATTERN = re.compile(r"^(?:Rp|IDR)\s*[\d.,]+", re.IGNORECASE)
CSV_FIELDS = ("link", "title", "price", "description")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument("--lang=en-US")
    return webdriver.Chrome(options=options)


def collect_links(
    driver: webdriver.Chrome,
    url: str,
    pause: float,
) -> list[str]:
    driver.get(url)
    wait = WebDriverWait(driver, 360)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException as exc:
        raise RuntimeError("Facebook did not finish loading.") from exc

    # Let the initially visible, client-rendered listing cards settle. This
    # scraper intentionally does not scroll or request additional results.
    time.sleep(pause)
    links: set[str] = set()
    for element in driver.find_elements(By.CSS_SELECTOR, ITEM_LINK_SELECTOR):
        href = element.get_attribute("href")
        if href:
            absolute = urljoin("https://www.facebook.com", href)
            match = ITEM_PATH_PATTERN.match(urlparse(absolute).path)
            if match:
                links.add(f"https://www.facebook.com/marketplace/item/{match.group(1)}/")

    print(f"Collected {len(links)} unique links from the initial results.")
    return sorted(links)


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
        help="Pipe-delimited CSV file for ad details",
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
    return parser.parse_args()


def canonical_item_url(value: str) -> str | None:
    """Return a canonical Marketplace item URL, or None for unrelated input."""
    absolute = urljoin("https://www.facebook.com", value.strip())
    match = ITEM_PATH_PATTERN.match(urlparse(absolute).path)
    if not match:
        return None
    return f"https://www.facebook.com/marketplace/item/{match.group(1)}/"


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
    # Rewriting the complete set also cleans up duplicates from older runs.
    output.write_text("".join(f"{link}\n" for link in sorted(known)), encoding="utf-8")
    return len(known) - before


def first_text(driver: webdriver.Chrome, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            text = element.text.strip()
            if text:
                return text
    return ""


def meta_content(driver: webdriver.Chrome, property_name: str) -> str:
    elements = driver.find_elements(
        By.CSS_SELECTOR, f'meta[property="{property_name}"][content]'
    )
    return elements[0].get_attribute("content").strip() if elements else ""


def extract_price(driver: webdriver.Chrome) -> str:
    candidates: list[str] = []
    for element in driver.find_elements(By.XPATH, "//*[self::span or self::div]"):
        text = element.text.strip()
        if text and "\n" not in text and PRICE_PATTERN.match(text):
            candidates.append(text)
    return min(candidates, key=len) if candidates else ""


def extract_description(driver: webdriver.Chrome) -> str:
    description = driver.execute_script(
        r"""
        const headings = new Set([
          "description", "seller's description", "deskripsi", "deskripsi penjual"
        ]);
        const candidates = [];
        for (const element of document.querySelectorAll('span, h2, h3, div')) {
          const heading = (element.innerText || '').trim().toLowerCase();
          if (!headings.has(heading)) continue;
          let container = element.parentElement;
          for (let level = 0; container && level < 4; level++, container = container.parentElement) {
            const text = (container.innerText || '').trim();
            if (text.length > heading.length && text.length < 5000) {
              const lines = text.split('\n').map(x => x.trim()).filter(Boolean);
              const value = lines.filter(x => x.toLowerCase() !== heading).join('\n');
              if (value) candidates.push(value);
            }
          }
        }
        candidates.sort((a, b) => a.length - b.length);
        return candidates[0] || '';
        """
    )
    return description.strip() if description else meta_content(driver, "og:description")


def scrape_ad_details(driver: webdriver.Chrome, link: str) -> dict[str, str]:
    print(f"Opening ad: {link}")
    driver.get(link)
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    try:
        WebDriverWait(driver, 10).until(
            lambda browser: first_text(browser, ("main h1", "h1"))
            or meta_content(browser, "og:title")
        )
    except TimeoutException:
        pass

    return {
        "link": link,
        "title": first_text(driver, ("main h1", "h1"))
        or meta_content(driver, "og:title"),
        "price": extract_price(driver),
        "description": extract_description(driver),
    }


def load_csv_links(csv_output: Path) -> set[str]:
    if not csv_output.exists() or csv_output.stat().st_size == 0:
        return set()

    first_line = csv_output.read_text(encoding="utf-8").splitlines()[0]
    delimiter = "|" if "|" in first_line else ","
    with csv_output.open("r", encoding="utf-8", newline="") as file:
        rows_by_link: dict[str, dict[str, str]] = {}
        for row in csv.DictReader(file, delimiter=delimiter):
            canonical = canonical_item_url(row.get("link", ""))
            if canonical:
                rows_by_link[canonical] = {
                    "link": canonical,
                    "title": row.get("title", ""),
                    "price": row.get("price", ""),
                    "description": row.get("description", ""),
                }

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


def scrape_ad_chunk(links: list[str]) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Scrape one link chunk in a dedicated process and Chrome instance."""
    rows: list[dict[str, str]] = []
    errors: list[tuple[str, str]] = []
    driver = build_driver()
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
    links: list[str], workers: int
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    if not links:
        return [], []
    worker_count = min(workers, len(links))
    chunks = [links[index::worker_count] for index in range(worker_count)]
    rows: list[dict[str, str]] = []
    errors: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(scrape_ad_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            chunk_rows, chunk_errors = future.result()
            rows.extend(chunk_rows)
            errors.extend(chunk_errors)
    return rows, errors


def main() -> None:
    args = parse_args()
    if args.pause < 0 or args.detail_workers < 1:
        raise SystemExit("pause must be >= 0 and detail workers must be >= 1")

    known_links = load_existing_links(args.output)
    csv_links = load_csv_links(args.csv_output)
    # Normalize/deduplicate an existing file before the first browser search.
    store_links(args.output, known_links, [])
    driver = build_driver()
    try:
        links = collect_links(
            driver,
            args.url,
            args.pause,
        )
        new_count = store_links(args.output, known_links, links)
    finally:
        driver.quit()

    detail_links = sorted(set(links) - csv_links)
    print(
        f"Scraping details for {len(detail_links)} ads with "
        f"up to {args.detail_workers} worker processes."
    )
    rows, errors = scrape_details_parallel(detail_links, args.detail_workers)
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
        f"{len(known_links)} unique links are stored in {args.output}. "
        f"Ad details are stored in {args.csv_output}."
    )


if __name__ == "__main__":
    main()
