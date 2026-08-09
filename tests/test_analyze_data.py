import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzeData.analyze_data import (
    OUTPUT_FIELDS,
    PhoneTypeLabels,
    ad_identity,
    append_output,
    assign_phone_types,
    backfill_output_phone_types,
    extract_phone_type,
    load_existing_identities,
    normalize_output_schema,
    refresh_missing_output_prices,
    select_new_rows,
    validate_codex_auth,
)


class AnalyzeDataIncrementalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output = Path(self.temp_dir.name) / "combined_rated_ads.csv"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def row(link: str, description: str = "Clean") -> dict[str, str]:
        return {
            "link": link,
            "title": "Phone",
            "price": "100",
            "description": description,
            "timestamp": "2026-01-01T00:00:00+07:00",
            "source": "olx_ads.csv",
            "phone_type": "iPhone 11",
            "condition_rating": "Good",
            "condition_reason": "Clean condition",
        }

    def test_append_creates_header_and_preserves_existing_rows(self) -> None:
        first = self.row("https://example/1")
        second = self.row("https://example/2")
        append_output(self.output, [first])
        append_output(self.output, [second])

        with self.output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="|"))
        self.assertEqual(list(rows[0]), list(OUTPUT_FIELDS))
        self.assertEqual([row["link"] for row in rows], [first["link"], second["link"]])

    def test_existing_identity_does_not_depend_on_description(self) -> None:
        append_output(self.output, [self.row("https://example/1", "Old description")])
        identities = load_existing_identities(self.output)
        changed = self.row("https://example/1", "Updated description")
        self.assertIn(ad_identity(changed), identities)

    def test_only_unique_ads_absent_from_output_are_selected(self) -> None:
        existing_row = self.row("https://example/1")
        new_row = self.row("https://example/2")
        duplicate_from_other_source = existing_row.copy()
        duplicate_from_other_source["source"] = "facebook_ads.csv"
        selected = select_new_rows(
            [duplicate_from_other_source, new_row, new_row.copy()],
            {ad_identity(existing_row)},
        )
        self.assertEqual(selected, [new_row])

    def test_empty_append_does_not_create_file(self) -> None:
        append_output(self.output, [])
        self.assertFalse(self.output.exists())

    def test_legacy_header_is_normalized_before_append(self) -> None:
        legacy_fields = tuple(field for field in OUTPUT_FIELDS if field != "timestamp")
        with self.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=legacy_fields, delimiter="|")
            writer.writeheader()
            writer.writerow({key: value for key, value in self.row("https://example/1").items() if key in legacy_fields})

        normalize_output_schema(self.output)
        append_output(self.output, [self.row("https://example/2")])

        with self.output.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="|")
            rows = list(reader)
        self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_FIELDS)
        self.assertEqual(rows[0]["timestamp"], "")
        self.assertEqual(rows[1]["timestamp"], "2026-01-01T00:00:00+07:00")

    def test_phone_type_is_extracted_from_title_with_canonical_casing(self) -> None:
        cases = {
            "IPhone 11 64 GB": "iPhone 11",
            "IPHONE 12 promax 256GB": "iPhone 12 Pro Max",
            "Apple iPhone 13 MINI": "iPhone 13 mini",
            "ip 14+ ex iBox": "iPhone 14 Plus",
            "Unrelated phone listing": "Unknown",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(extract_phone_type(title), expected)

    def test_phone_labels_are_documented_and_reused_case_insensitively(self) -> None:
        labels_path = Path(self.temp_dir.name) / "phone_type_labels.json"
        labels = PhoneTypeLabels(labels_path)
        self.assertEqual(labels.register("iPhone 11"), "iPhone 11")
        self.assertEqual(labels.register("IPhone 11"), "iPhone 11")
        rows = [self.row("https://example/1")]
        rows[0]["title"] = "IPHONE 12 PRO"
        assign_phone_types(rows, labels)
        labels.save()

        reloaded = PhoneTypeLabels(labels_path)
        self.assertEqual(reloaded.labels, ["iPhone 11", "iPhone 12 Pro"])
        self.assertEqual(rows[0]["phone_type"], "iPhone 12 Pro")

    def test_existing_output_phone_types_are_backfilled_without_rerating(self) -> None:
        legacy_fields = tuple(field for field in OUTPUT_FIELDS if field != "phone_type")
        row = self.row("https://example/1")
        row["title"] = "IPhone 13 128GB"
        with self.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=legacy_fields, delimiter="|")
            writer.writeheader()
            writer.writerow({key: value for key, value in row.items() if key in legacy_fields})

        labels = PhoneTypeLabels(Path(self.temp_dir.name) / "labels.json")
        self.assertEqual(backfill_output_phone_types(self.output, labels), 1)

        with self.output.open(encoding="utf-8", newline="") as handle:
            output_row = next(csv.DictReader(handle, delimiter="|"))
        self.assertEqual(output_row["phone_type"], "iPhone 13")
        self.assertEqual(output_row["condition_rating"], "Good")

    def test_recovered_source_price_refreshes_existing_combined_row(self) -> None:
        combined_row = self.row("https://example/1")
        combined_row["price"] = ""
        append_output(self.output, [combined_row])
        source_row = self.row("https://example/1")
        source_row["price"] = "Rp 5.000.000"

        self.assertEqual(
            refresh_missing_output_prices(self.output, [source_row]),
            1,
        )
        with self.output.open(encoding="utf-8", newline="") as handle:
            refreshed = next(csv.DictReader(handle, delimiter="|"))
        self.assertEqual(refreshed["price"], "Rp 5.000.000")
        self.assertEqual(refreshed["condition_rating"], "Good")

    def test_main_rates_new_ad_once_then_skips_it(self) -> None:
        from analyzeData.analyze_data import main

        data_dir = Path(self.temp_dir.name) / "data"
        data_dir.mkdir()
        source = data_dir / "olx_ads.csv"
        fields = ("link", "title", "price", "description", "timestamp")
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="|")
            writer.writeheader()
            writer.writerow({key: value for key, value in self.row("https://example/1").items() if key in fields})

        output = data_dir / "combined_rated_ads.csv"
        guidelines = Path(self.temp_dir.name) / "guidelines.md"
        guidelines.write_text("guidelines", encoding="utf-8")
        phone_labels = Path(self.temp_dir.name) / "phone_type_labels.json"
        argv = ["analyze_data.py", "--data-dir", str(data_dir), "--output", str(output),
                "--guidelines", str(guidelines), "--phone-labels", str(phone_labels)]

        with patch("sys.argv", argv), patch(
            "analyzeData.analyze_data.rate_batch_with_codex",
            return_value={0: ("Good", "Clean condition")},
        ) as rate:
            main()
            main()
        rate.assert_called_once()

        with output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="|"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["link"], "https://example/1")
        self.assertEqual(rows[0]["phone_type"], "Unknown")

    def test_main_uploads_completed_output_when_google_sheet_is_configured(self) -> None:
        from analyzeData.analyze_data import main

        data_dir = Path(self.temp_dir.name) / "data"
        data_dir.mkdir()
        output = data_dir / "combined_rated_ads.csv"
        existing_row = self.row("https://example/1")
        append_output(output, [existing_row])
        source_fields = ("link", "title", "price", "description", "timestamp")
        with (data_dir / "olx_ads.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=source_fields, delimiter="|")
            writer.writeheader()
            writer.writerow(
                {key: value for key, value in existing_row.items() if key in source_fields}
            )
        guidelines = Path(self.temp_dir.name) / "guidelines.md"
        guidelines.write_text("guidelines", encoding="utf-8")
        labels = Path(self.temp_dir.name) / "labels.json"
        argv = [
            "analyze_data.py",
            "--data-dir",
            str(data_dir),
            "--output",
            str(output),
            "--guidelines",
            str(guidelines),
            "--phone-labels",
            str(labels),
            "--google-spreadsheet-id",
            "spreadsheet-123",
            "--google-worksheet",
            "Phone Ads",
        ]

        with patch("sys.argv", argv), patch(
            "analyzeData.analyze_data.upload_csv_to_google_sheets",
            return_value={"rows": 1, "cells": 9},
        ) as upload:
            main()

        upload.assert_called_once_with(
            output,
            "spreadsheet-123",
            "Phone Ads",
        )

    def test_docker_auth_preflight_rejects_missing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home, patch.dict(
            "analyzeData.analyze_data.os.environ",
            {"RUNNING_IN_DOCKER": "1", "OPENAI_API_KEY": "", "CODEX_HOME": codex_home},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Codex is not authenticated"):
                validate_codex_auth()

    def test_docker_auth_preflight_accepts_key(self) -> None:
        with patch.dict(
            "analyzeData.analyze_data.os.environ",
            {"RUNNING_IN_DOCKER": "1", "OPENAI_API_KEY": "sk-test"},
            clear=True,
        ):
            validate_codex_auth()

    def test_docker_auth_preflight_accepts_cached_chatgpt_login(self) -> None:
        with tempfile.TemporaryDirectory() as codex_home:
            (Path(codex_home) / "auth.json").write_text("{}", encoding="utf-8")
            with patch.dict(
                "analyzeData.analyze_data.os.environ",
                {"RUNNING_IN_DOCKER": "1", "OPENAI_API_KEY": "", "CODEX_HOME": codex_home},
                clear=True,
            ):
                validate_codex_auth()
