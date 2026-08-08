#!/usr/bin/env python3
"""Replace a Google Sheets worksheet with the combined marketplace CSV."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "combined_rated_ads.csv"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SERVICE_ACCOUNT_ENV = "GOOGLE_SERVICE_ACCOUNT_JSON_BASE64"


def read_csv_values(csv_path: Path) -> list[list[str]]:
    """Read every pipe-delimited CSV cell as a Google Sheets string value."""
    if not csv_path.is_file():
        raise RuntimeError(f"Combined CSV not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        values = list(csv.reader(handle, delimiter="|"))
    if not values:
        raise RuntimeError(f"Combined CSV is empty: {csv_path}")
    return values


def load_service_account_info_from_env() -> dict[str, Any] | None:
    """Decode a complete service-account JSON document from one environment value."""
    encoded_credentials = os.getenv(SERVICE_ACCOUNT_ENV, "").strip()
    if not encoded_credentials:
        return None
    try:
        decoded = base64.b64decode(encoded_credentials, validate=True)
        credentials_info = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} must be valid Base64-encoded service-account JSON"
        ) from exc
    required = {"client_email", "private_key", "token_uri"}
    if not isinstance(credentials_info, dict) or required - credentials_info.keys():
        raise RuntimeError(
            f"{SERVICE_ACCOUNT_ENV} does not contain valid service-account credentials"
        )
    return credentials_info


def build_sheets_service() -> Any:
    """Build a Sheets API client from environment credentials or ADC fallback."""
    try:
        import google.auth
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Sheets dependencies are not installed. Run "
            "'pip install -r requirements.txt'."
        ) from exc

    credentials_info = load_service_account_info_from_env()
    if credentials_info:
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=[SHEETS_SCOPE],
        )
    else:
        credentials, _ = google.auth.default(scopes=[SHEETS_SCOPE])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def _a1_sheet_name(worksheet: str) -> str:
    """Quote a worksheet title for safe use in A1 notation."""
    return "'" + worksheet.replace("'", "''") + "'"


def _ensure_worksheet(service: Any, spreadsheet_id: str, worksheet: str) -> None:
    spreadsheet = service.spreadsheets()
    metadata = spreadsheet.get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title",
    ).execute()
    titles = {
        sheet.get("properties", {}).get("title")
        for sheet in metadata.get("sheets", [])
    }
    if worksheet not in titles:
        spreadsheet.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": worksheet}}}]},
        ).execute()


def upload_csv_to_google_sheets(
    csv_path: Path,
    spreadsheet_id: str,
    worksheet: str = "Ads",
    *,
    service: Any | None = None,
) -> dict[str, int]:
    """Replace one worksheet's values with the complete combined CSV."""
    spreadsheet_id = spreadsheet_id.strip()
    worksheet = worksheet.strip()
    if not spreadsheet_id:
        raise ValueError("Google spreadsheet ID must not be empty")
    if not worksheet:
        raise ValueError("Google worksheet name must not be empty")

    values = read_csv_values(csv_path)
    sheets_service = service or build_sheets_service()
    _ensure_worksheet(sheets_service, spreadsheet_id, worksheet)

    spreadsheet = sheets_service.spreadsheets()
    sheet_range = _a1_sheet_name(worksheet)
    spreadsheet.values().clear(
        spreadsheetId=spreadsheet_id,
        range=sheet_range,
        body={},
    ).execute()
    response = spreadsheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_range}!A1",
        valueInputOption="RAW",
        body={"majorDimension": "ROWS", "values": values},
    ).execute()
    return {
        "rows": len(values) - 1,
        "cells": int(response.get("updatedCells", 0)),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
    )
    parser.add_argument(
        "--worksheet",
        default=os.getenv("GOOGLE_SHEETS_WORKSHEET", "Ads"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.spreadsheet_id.strip():
        raise SystemExit(
            "Set GOOGLE_SHEETS_SPREADSHEET_ID or pass --spreadsheet-id."
        )
    try:
        result = upload_csv_to_google_sheets(
            args.csv,
            args.spreadsheet_id,
            args.worksheet,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(
        f"Uploaded {result['rows']} data rows to worksheet {args.worksheet!r} "
        f"({result['cells']} cells updated)."
    )


if __name__ == "__main__":
    main()
