#!/usr/bin/env python3
"""Shared Selenium, link-storage, CSV, and worker helpers for marketplace scrapers."""

from __future__ import annotations

import csv
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Mapping

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


CSV_FIELDS = ("link", "title", "price", "description", "timestamp")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
Canonicalizer = Callable[[str], str | None]
Row = dict[str, str]
RowNormalizer = Callable[[Mapping[str, str], str], Row]
DriverFactory = Callable[[bool], webdriver.Chrome]
DetailScraper = Callable[[webdriver.Chrome, str], Row]


def build_driver(
    headless: bool = False,
    profile_dir: Path | None = None,
    language: str = "en-US",
) -> webdriver.Chrome:
    """Create a Chrome driver with the settings shared by both scrapers."""
    options = Options()
    chrome_binary = os.getenv("CHROME_BINARY")
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chrome_binary:
        options.binary_location = chrome_binary
    if headless:
        options.add_argument("--headless=new")
    if profile_dir:
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")
    options.add_argument("--start-maximized")
    options.add_argument(f"--lang={language}")
    options.add_argument(f"user-agent={DEFAULT_USER_AGENT}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    service = Service(executable_path=chromedriver_path) if chromedriver_path else None
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        },
    )
    return driver


def load_existing_links(output: Path, canonicalize: Canonicalizer) -> set[str]:
    if not output.exists():
        return set()
    return {
        canonical
        for line in output.read_text(encoding="utf-8").splitlines()
        if (canonical := canonicalize(line)) is not None
    }


def store_links(output: Path, known: set[str], found: list[str]) -> int:
    before = len(known)
    known.update(found)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{link}\n" for link in sorted(known)), encoding="utf-8")
    return len(known) - before


def default_row_normalizer(row: Mapping[str, str], canonical: str) -> Row:
    normalized = {field: row.get(field, "") for field in CSV_FIELDS}
    normalized["link"] = canonical
    return normalized


def read_csv_rows(
    csv_output: Path,
    canonicalize: Canonicalizer,
    normalize_row: RowNormalizer = default_row_normalizer,
) -> dict[str, Row]:
    if not csv_output.exists() or csv_output.stat().st_size == 0:
        return {}

    first_line = csv_output.read_text(encoding="utf-8-sig").splitlines()[0]
    delimiter = "|" if "|" in first_line else ","
    rows_by_link: dict[str, Row] = {}
    with csv_output.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=delimiter):
            canonical = canonicalize(row.get("link", ""))
            if canonical:
                rows_by_link[canonical] = normalize_row(row, canonical)
    return rows_by_link


def write_csv_rows(csv_output: Path, rows_by_link: Mapping[str, Row]) -> None:
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = csv_output.with_suffix(csv_output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, delimiter="|")
        writer.writeheader()
        writer.writerows(rows_by_link.values())
    temporary.replace(csv_output)


def load_csv_links(
    csv_output: Path,
    canonicalize: Canonicalizer,
    normalize_row: RowNormalizer = default_row_normalizer,
) -> set[str]:
    """Load saved ad URLs and normalize existing output to pipe-delimited CSV."""
    rows_by_link = read_csv_rows(csv_output, canonicalize, normalize_row)
    if csv_output.exists() and csv_output.stat().st_size:
        write_csv_rows(csv_output, rows_by_link)
    return set(rows_by_link)


def upsert_csv_row(
    csv_output: Path,
    row: Mapping[str, str],
    canonicalize: Canonicalizer,
    normalize_row: RowNormalizer = default_row_normalizer,
) -> None:
    rows_by_link = read_csv_rows(csv_output, canonicalize, normalize_row)
    canonical = canonicalize(row.get("link", ""))
    if canonical is None:
        raise ValueError(f"Invalid marketplace item link: {row.get('link', '')}")
    rows_by_link[canonical] = normalize_row(row, canonical)
    write_csv_rows(csv_output, rows_by_link)


def scrape_ad_chunk(
    links: list[str],
    headless: bool,
    driver_factory: DriverFactory,
    detail_scraper: DetailScraper,
) -> tuple[list[Row], list[tuple[str, str]]]:
    """Scrape one link chunk in a dedicated Chrome process."""
    rows: list[Row] = []
    errors: list[tuple[str, str]] = []
    driver = driver_factory(headless)
    try:
        for link in links:
            try:
                rows.append(detail_scraper(driver, link))
            except Exception as exc:
                errors.append((link, str(exc)))
    finally:
        driver.quit()
    return rows, errors


def scrape_details_parallel(
    links: list[str],
    workers: int,
    headless: bool,
    driver_factory: DriverFactory,
    detail_scraper: DetailScraper,
) -> tuple[list[Row], list[tuple[str, str]]]:
    if not links:
        return [], []
    worker_count = min(workers, len(links))
    chunks = [links[index::worker_count] for index in range(worker_count)]
    rows: list[Row] = []
    errors: list[tuple[str, str]] = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                scrape_ad_chunk,
                chunk,
                headless,
                driver_factory,
                detail_scraper,
            )
            for chunk in chunks
        ]
        for future in as_completed(futures):
            chunk_rows, chunk_errors = future.result()
            rows.extend(chunk_rows)
            errors.extend(chunk_errors)
    return rows, errors
