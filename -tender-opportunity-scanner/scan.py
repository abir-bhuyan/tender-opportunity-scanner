#!/usr/bin/env python3
"""
scan.py — Tender Opportunity Scanner CLI
=========================================

Usage
-----

    # Default: scan bundled sample data, write dashboard.html
    python scan.py

    # Use a custom keyword config
    python scan.py --config config/keywords.yaml

    # Use a custom data file (must match sample_tenders.json shape)
    python scan.py --data my_tenders.json

    # Specify the output path
    python scan.py --output reports/2026-05-week-3.html

Exit codes
----------
    0   success
    1   bad arguments
    2   data validation failed
    3   I/O error (file or DB)
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# Make the scanner package importable when running scan.py directly
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scanner import scoring, sources, storage, report   # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tender-scanner",
        description=(
            "Scan public tender feeds for opportunities matching a "
            "configured service profile, score them by relevance, and "
            "render a dashboard."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--config",
        default=str(ROOT / "config" / "keywords.yaml"),
        help="Path to the keyword configuration YAML.",
    )
    p.add_argument(
        "--data",
        default=str(ROOT / "data" / "sample_tenders.json"),
        help="Path to the JSON tender data file (sample data by default).",
    )
    p.add_argument(
        "--db",
        default=str(ROOT / "data" / "tenders.db"),
        help="Path to the SQLite database used for persistence.",
    )
    p.add_argument(
        "--output",
        default=str(ROOT / "output" / "dashboard.html"),
        help="Path to write the HTML dashboard.",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-tender log output.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # 1) Load config
    try:
        cfg = scoring.load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: cannot load config: {exc}", file=sys.stderr)
        return 2

    company = cfg.get("target_company", {}).get("name", "Configured Company")

    # 2) Load tenders from chosen source
    try:
        source = sources.SampleDataSource(args.data)
        tenders = source.fetch()
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: cannot load tender data: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(f"Loaded {len(tenders)} tenders for {company}")

    # 3) Score each tender
    scored = scoring.score_all(tenders, cfg)

    # 4) Persist to SQLite + collect rows in score order
    try:
        with storage.open_db(args.db) as conn:
            for tender, score in scored:
                storage.upsert(conn, tender, score)
                if not args.quiet:
                    flag = "✓" if score.qualified else "·"
                    print(
                        f"  {flag} [{score.display_score:>3}]  "
                        f"{tender['tender_id']}  {tender['title'][:64]}"
                    )
            rows = storage.fetch_all_ranked(conn)
    except Exception:  # pragma: no cover  — fail loudly with traceback
        traceback.print_exc()
        return 3

    # 5) Render the dashboard
    try:
        dash_path = report.render(rows, args.output, company_name=company)
    except OSError as exc:
        print(f"error: cannot write dashboard: {exc}", file=sys.stderr)
        return 3

    qualified_count = sum(1 for r in rows if r["qualified"])
    if not args.quiet:
        print()
        print(f"Qualified: {qualified_count} / {len(rows)}")
        print(f"Dashboard: {dash_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
