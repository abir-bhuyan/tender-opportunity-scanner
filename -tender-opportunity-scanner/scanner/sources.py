"""
scanner.sources
===============

Adapters that pull tender records from different sources and normalise
them into a common dictionary shape used by the rest of the pipeline.

Each source returns a list of dicts with these required keys:
    tender_id, title, agency, description, location, category,
    value_aud_min, value_aud_max, published_date, closing_date,
    source, url

Currently implemented:
    - SampleDataSource:   loads canned JSON for offline demos / CI
    - AusTenderSource:    skeleton for live scraping (stubbed; see notes)

Adding a new source means subclassing TenderSource and implementing fetch().
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Common tender record shape — kept as a TypedDict-style hint, but we use
# plain dicts at runtime to avoid extra dependencies.
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = (
    "tender_id", "title", "agency", "description", "location",
    "category", "value_aud_min", "value_aud_max", "published_date",
    "closing_date", "source", "url",
)


def _validate(record: dict[str, Any]) -> dict[str, Any]:
    """Ensure a record has all required fields; coerce dates to ISO strings."""
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        raise ValueError(
            f"Tender {record.get('tender_id', '?')} missing fields: {missing}"
        )
    # Sanity check on dates — accept ISO strings, no coercion needed
    for field in ("published_date", "closing_date"):
        try:
            datetime.fromisoformat(record[field])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Tender {record['tender_id']} has invalid {field}: "
                f"{record[field]!r}"
            ) from exc
    return record


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class TenderSource(ABC):
    """Abstract base class for a tender data source."""

    name: str = "unknown"

    @abstractmethod
    def fetch(self) -> list[dict[str, Any]]:
        """Return a list of validated tender records."""


# ---------------------------------------------------------------------------
# Sample data source — loads canned JSON, used in demo and CI
# ---------------------------------------------------------------------------

class SampleDataSource(TenderSource):
    """Load a static JSON file of sample tenders.

    Used for offline demos, CI testing, and as a fallback when live
    sources are unreachable. Mirrors the shape of records returned by
    the AusTender adapter so downstream code doesn't care which source
    a tender came from.
    """

    name = "sample"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"Sample data file not found: {self.path}")

    def fetch(self) -> list[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, list):
            raise ValueError(
                f"Expected a list of tenders in {self.path}, got {type(raw).__name__}"
            )
        return [_validate(r) for r in raw]


# ---------------------------------------------------------------------------
# AusTender — live scraping skeleton
# ---------------------------------------------------------------------------

class AusTenderSource(TenderSource):
    """Live scrape of AusTender public listings.

    NOT IMPLEMENTED in this proof-of-concept. The structure is here to
    show how an additional adapter would slot into the pipeline without
    touching the scoring or reporting layers. To wire this up:

        1. Use `requests` to fetch listing pages from
           https://www.tenders.gov.au/atm
        2. Parse with BeautifulSoup; extract title, agency, value range,
           closing date, and ATM ID.
        3. Visit each detail page and pull the description block.
        4. Build a dict with the REQUIRED_FIELDS keys.
        5. Pass each dict through _validate().

    Scraping responsibly: respect robots.txt, set a User-Agent header
    identifying the tool, and rate-limit to <= 1 request per 2 seconds.
    For production use, prefer the official AusTender CSV/XML exports
    where available.
    """

    name = "austender"

    def __init__(self, *, dry_run: bool = True):
        self.dry_run = dry_run

    def fetch(self) -> list[dict[str, Any]]:
        if self.dry_run:
            # In dry-run mode the live adapter returns nothing; demos
            # use SampleDataSource instead.
            return []
        raise NotImplementedError(
            "Live AusTender scraping is intentionally stubbed in this "
            "portfolio piece. See class docstring for the implementation "
            "plan."
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def load_default_source(repo_root: Path) -> TenderSource:
    """Return the default source used by the CLI when no flag is passed.

    Defaults to the bundled sample data so the tool runs out of the box.
    """
    return SampleDataSource(repo_root / "data" / "sample_tenders.json")
