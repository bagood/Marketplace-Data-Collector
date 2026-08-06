#!/usr/bin/env python3
"""Run all marketplace scrapers concurrently, then analyze newly collected ads."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true", help="Run scraper browsers headlessly")
    parser.add_argument("--facebook-workers", type=int, default=2)
    parser.add_argument("--olx-workers", type=int, default=2)
    parser.add_argument("--model", default="gpt-5.5", help="Codex model used by the analyzer")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def build_commands(args: argparse.Namespace) -> tuple[dict[str, list[str]], list[str]]:
    python = sys.executable
    headless = ["--headless"] if args.headless else []
    scrapers = {
        "facebook": [
            python,
            str(PROJECT_ROOT / "scrapperScripts" / "facebook_marketplace_scraper.py"),
            *headless,
            "--detail-workers",
            str(args.facebook_workers),
        ],
        "olx": [
            python,
            str(PROJECT_ROOT / "scrapperScripts" / "olx_scraper.py"),
            *headless,
            "--detail-workers",
            str(args.olx_workers),
            "--profile-dir",
            str(PROJECT_ROOT / ".olx-chrome-profile"),
        ],
    }
    analyzer = [
        python,
        str(PROJECT_ROOT / "analyzeData" / "analyze_data.py"),
        "--model",
        args.model,
        "--batch-size",
        str(args.batch_size),
        "--timeout",
        str(args.timeout),
    ]
    return scrapers, analyzer


def run_scrapers(commands: dict[str, list[str]]) -> None:
    """Run scraper commands concurrently and require every one to succeed."""
    processes: dict[str, subprocess.Popen] = {}
    try:
        for name, command in commands.items():
            print(f"Starting {name} scraper", flush=True)
            processes[name] = subprocess.Popen(command, cwd=PROJECT_ROOT)

        remaining = set(processes)
        failures: dict[str, int] = {}
        while remaining:
            for name in tuple(remaining):
                returncode = processes[name].poll()
                if returncode is None:
                    continue
                remaining.remove(name)
                print(f"{name} scraper exited with code {returncode}", flush=True)
                if returncode != 0:
                    failures[name] = returncode
            if failures:
                break
            time.sleep(0.2)

        if failures:
            for name in remaining:
                processes[name].terminate()
            for name in remaining:
                processes[name].wait()
            details = ", ".join(f"{name}={code}" for name, code in failures.items())
            raise RuntimeError(f"Scraping failed ({details}); analysis was not started")
    except (KeyboardInterrupt, SystemExit):
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            process.wait()
        raise


def run_pipeline(args: argparse.Namespace) -> None:
    if args.facebook_workers < 1 or args.olx_workers < 1:
        raise ValueError("scraper worker counts must be greater than zero")
    if args.batch_size < 1 or args.timeout <= 0:
        raise ValueError("batch size and timeout must be greater than zero")

    scraper_commands, analyzer_command = build_commands(args)
    run_scrapers(scraper_commands)
    print("All scrapers completed; starting incremental analysis", flush=True)
    subprocess.run(analyzer_command, cwd=PROJECT_ROOT, check=True)
    print("Collection and analysis completed", flush=True)


def main() -> None:
    try:
        run_pipeline(parse_args())
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
