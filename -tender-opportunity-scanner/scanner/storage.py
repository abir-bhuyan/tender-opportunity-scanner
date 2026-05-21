"""
scanner.storage
===============

SQLite persistence for scanned tenders and their scores.

The store deduplicates by tender_id so re-running the scanner is safe;
existing rows are updated with the latest score and last-seen timestamp.
This mimics how a real commercial team would track an opportunity over
its lifecycle (newly seen → scored → reviewed → bid / no-bid).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    tender_id        TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    agency           TEXT,
    description      TEXT,
    location         TEXT,
    category         TEXT,
    value_aud_min    INTEGER,
    value_aud_max    INTEGER,
    published_date   TEXT,
    closing_date     TEXT,
    source           TEXT,
    url              TEXT,
    raw_score        REAL,
    display_score    INTEGER,
    qualified        INTEGER,        -- 0 / 1
    signals_json     TEXT,
    rationale        TEXT,
    first_seen_at    TEXT NOT NULL,
    last_scored_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tenders_score ON tenders(raw_score DESC);
CREATE INDEX IF NOT EXISTS idx_tenders_closing ON tenders(closing_date);
"""


@contextmanager
def open_db(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with sensible defaults."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert(
    conn: sqlite3.Connection,
    tender: dict[str, Any],
    score: "scoring.Score",  # type: ignore[name-defined]
) -> None:
    """Insert or update a tender + score row.

    On re-scan, we preserve `first_seen_at` (so we can spot tenders that
    have been visible for a while) but refresh everything else.
    """
    now = datetime.utcnow().isoformat(timespec="seconds")
    signals_json = json.dumps(
        [{"kind": s.kind, "term": s.term, "points": s.points}
         for s in score.signals]
    )

    conn.execute(
        """
        INSERT INTO tenders (
            tender_id, title, agency, description, location, category,
            value_aud_min, value_aud_max, published_date, closing_date,
            source, url, raw_score, display_score, qualified,
            signals_json, rationale, first_seen_at, last_scored_at
        )
        VALUES (
            :tender_id, :title, :agency, :description, :location, :category,
            :value_aud_min, :value_aud_max, :published_date, :closing_date,
            :source, :url, :raw_score, :display_score, :qualified,
            :signals_json, :rationale, :now, :now
        )
        ON CONFLICT(tender_id) DO UPDATE SET
            title = excluded.title,
            agency = excluded.agency,
            description = excluded.description,
            location = excluded.location,
            category = excluded.category,
            value_aud_min = excluded.value_aud_min,
            value_aud_max = excluded.value_aud_max,
            closing_date = excluded.closing_date,
            raw_score = excluded.raw_score,
            display_score = excluded.display_score,
            qualified = excluded.qualified,
            signals_json = excluded.signals_json,
            rationale = excluded.rationale,
            last_scored_at = excluded.last_scored_at
        """,
        {
            **tender,
            "raw_score": score.raw_score,
            "display_score": score.display_score,
            "qualified": 1 if score.qualified else 0,
            "signals_json": signals_json,
            "rationale": score.rationale,
            "now": now,
        },
    )


def fetch_all_ranked(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all scored tenders, highest-score first."""
    cur = conn.execute(
        "SELECT * FROM tenders ORDER BY raw_score DESC, closing_date ASC"
    )
    return cur.fetchall()
