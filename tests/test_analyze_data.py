import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analyzeData.analyze_data import (
    OUTPUT_FIELDS,
    ad_identity,
    append_output,
    load_existing_identities,
    normalize_output_schema,
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
        argv = ["analyze_data.py", "--data-dir", str(data_dir), "--output", str(output),
                "--guidelines", str(guidelines)]

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
