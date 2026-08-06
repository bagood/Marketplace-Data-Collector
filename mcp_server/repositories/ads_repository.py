import csv
from pathlib import Path

class DatasetNotFoundError(FileNotFoundError):
    """Raised when the configured CSV dataset does not exist."""

class AdsRepository:
    """Read marketplace advertisements from the pipe-delimited CSV file."""
    delimiter = "|"

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path

    def _ensure_exists(self) -> None:
        if not self.csv_path.is_file():
            raise DatasetNotFoundError(f"Dataset not found: {self.csv_path}")

    def get_all(self) -> list[dict[str, str]]:
        self._ensure_exists()
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=self.delimiter))

    def get_columns(self) -> list[str]:
        self._ensure_exists()
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter=self.delimiter).fieldnames or [])
