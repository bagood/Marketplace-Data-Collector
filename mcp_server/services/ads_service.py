from __future__ import annotations

from pathlib import Path
from mcp_server.repositories import AdsRepository

class AdsService:
    MAX_PAGE_SIZE = 500

    def __init__(self, repository: AdsRepository) -> None:
        self.repository = repository

    def fetch_ads(self, *, limit: int = 100, offset: int = 0, source: str | None = None,
                  condition_rating: str | None = None, query: str | None = None) -> dict:
        if not 1 <= limit <= self.MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {self.MAX_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        rows = self.repository.get_all()
        filtered = [row for row in rows if self._matches(row, source, condition_rating, query)]
        items = filtered[offset:offset + limit]
        return {"items": items, "total": len(filtered), "limit": limit, "offset": offset,
                "has_more": offset + len(items) < len(filtered)}

    def get_ad(self, link: str) -> dict | None:
        return next((row for row in self.repository.get_all() if row.get("link") == link), None)

    def metadata(self) -> dict:
        rows = self.repository.get_all()
        return {"file": str(Path(self.repository.csv_path)), "delimiter": self.repository.delimiter,
                "columns": self.repository.get_columns(), "row_count": len(rows),
                "sources": self._unique_values(rows, "source"),
                "condition_ratings": self._unique_values(rows, "condition_rating")}

    @staticmethod
    def _unique_values(rows: list[dict[str, str]], key: str) -> list[str]:
        return sorted({row[key] for row in rows if row.get(key)})

    @staticmethod
    def _matches(row: dict[str, str], source: str | None,
                 condition_rating: str | None, query: str | None) -> bool:
        if source and row.get("source", "").casefold() != source.casefold():
            return False
        if condition_rating and row.get("condition_rating", "").casefold() != condition_rating.casefold():
            return False
        if query:
            searchable = " ".join(row.get(field, "") for field in
                                  ("title", "description", "condition_reason")).casefold()
            if query.casefold() not in searchable:
                return False
        return True
