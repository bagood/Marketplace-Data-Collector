import base64
import csv
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from uploadToGoogleSheets.upload_to_google_sheets import (
    SERVICE_ACCOUNT_ENV,
    load_service_account_info_from_env,
    read_csv_values,
    upload_csv_to_google_sheets,
)


class GoogleSheetsUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.csv_path = Path(self.temp_dir.name) / "combined_rated_ads.csv"
        with self.csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="|")
            writer.writerow(["link", "title", "description"])
            writer.writerow(["https://example/1", "iPhone 11", "Clean\nFullset"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def service_with_sheets(titles: list[str]) -> tuple[MagicMock, MagicMock]:
        service = MagicMock()
        spreadsheets = service.spreadsheets.return_value
        spreadsheets.get.return_value.execute.return_value = {
            "sheets": [{"properties": {"title": title}} for title in titles]
        }
        spreadsheets.values.return_value.update.return_value.execute.return_value = {
            "updatedCells": 6
        }
        return service, spreadsheets

    def test_reads_pipe_csv_and_preserves_multiline_fields(self) -> None:
        self.assertEqual(
            read_csv_values(self.csv_path),
            [
                ["link", "title", "description"],
                ["https://example/1", "iPhone 11", "Clean\nFullset"],
            ],
        )

    def test_loads_complete_service_account_credentials_from_base64_env(self) -> None:
        credentials = {
            "type": "service_account",
            "client_email": "uploader@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        encoded = base64.b64encode(json.dumps(credentials).encode()).decode()
        with patch.dict("os.environ", {SERVICE_ACCOUNT_ENV: encoded}, clear=True):
            self.assertEqual(load_service_account_info_from_env(), credentials)

    def test_rejects_invalid_base64_credentials(self) -> None:
        with patch.dict("os.environ", {SERVICE_ACCOUNT_ENV: "not base64!"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, SERVICE_ACCOUNT_ENV):
                load_service_account_info_from_env()

    def test_upload_replaces_existing_worksheet_using_raw_values(self) -> None:
        service, spreadsheets = self.service_with_sheets(["Phone Ads"])
        result = upload_csv_to_google_sheets(
            self.csv_path,
            "spreadsheet-123",
            "Phone Ads",
            service=service,
        )

        spreadsheets.batchUpdate.assert_not_called()
        spreadsheets.values.return_value.clear.assert_called_once_with(
            spreadsheetId="spreadsheet-123", range="'Phone Ads'", body={}
        )
        update = spreadsheets.values.return_value.update
        self.assertEqual(update.call_args.kwargs["range"], "'Phone Ads'!A1")
        self.assertEqual(update.call_args.kwargs["valueInputOption"], "RAW")
        self.assertEqual(update.call_args.kwargs["body"]["values"][1][2], "Clean\nFullset")
        self.assertEqual(result, {"rows": 1, "cells": 6})

    def test_upload_creates_missing_worksheet_and_escapes_its_title(self) -> None:
        service, spreadsheets = self.service_with_sheets(["Sheet1"])
        upload_csv_to_google_sheets(
            self.csv_path,
            "spreadsheet-123",
            "Seller's Ads",
            service=service,
        )

        body = spreadsheets.batchUpdate.call_args.kwargs["body"]
        self.assertEqual(
            body,
            {"requests": [{"addSheet": {"properties": {"title": "Seller's Ads"}}}]},
        )
        update = spreadsheets.values.return_value.update
        self.assertEqual(update.call_args.kwargs["range"], "'Seller''s Ads'!A1")

    def test_rejects_empty_or_missing_input(self) -> None:
        service, _ = self.service_with_sheets(["Ads"])
        with self.assertRaisesRegex(ValueError, "spreadsheet ID"):
            upload_csv_to_google_sheets(self.csv_path, "", service=service)
        with self.assertRaisesRegex(RuntimeError, "Combined CSV not found"):
            upload_csv_to_google_sheets(
                Path(self.temp_dir.name) / "missing.csv",
                "spreadsheet-123",
                service=service,
            )
