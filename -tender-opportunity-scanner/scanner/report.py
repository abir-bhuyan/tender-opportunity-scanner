"""
scanner.report
==============

Render scored tenders to a polished single-file HTML dashboard.

The dashboard has three sections:

    1. **Summary header** — count of qualified vs. total, total value
       in the qualified pipeline, generated timestamp.
    2. **Top opportunities** — qualified tenders, displayed as cards
       with score, rationale, and key facts.
    3. **Other (filtered out)** — sub-threshold tenders in a compact
       table so the user can sanity-check the scoring.

All styling is inline so the file can be opened with a double-click
or emailed as a single attachment, no assets needed.
"""

from __future__ import annotations

import html
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Number / date formatting
# ---------------------------------------------------------------------------

def _fmt_value_range(row: sqlite3.Row) -> str:
    lo = row["value_aud_min"] or 0
    hi = row["value_aud_max"] or 0
    if not lo and not hi:
        return "Value not disclosed"
    if lo and hi and lo != hi:
        return f"${lo/1_000_000:.1f}M – ${hi/1_000_000:.1f}M AUD"
    v = lo or hi
    if v >= 1_000_000:
        return f"~${v/1_000_000:.1f}M AUD"
    return f"~${v/1_000:.0f}k AUD"


def _days_until(closing: str) -> int:
    try:
        return (date.fromisoformat(closing) - date.today()).days
    except (TypeError, ValueError):
        return 9999


def _closing_label(closing: str) -> tuple[str, str]:
    """Return (text, css-class) describing closing urgency."""
    days = _days_until(closing)
    if days < 0:
        return (f"Closed ({-days} d ago)", "closed")
    if days <= 14:
        return (f"Closes in {days} d", "urgent")
    if days <= 30:
        return (f"Closes in {days} d", "soon")
    return (f"Closes {closing}", "later")


def _score_class(score: int) -> str:
    if score >= 80:
        return "score-excellent"
    if score >= 60:
        return "score-strong"
    if score >= 40:
        return "score-ok"
    return "score-weak"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _summary_stats(rows: list[sqlite3.Row]) -> dict[str, Any]:
    qualified = [r for r in rows if r["qualified"]]
    total_value = sum(
        ((r["value_aud_min"] or 0) + (r["value_aud_max"] or 0)) / 2
        for r in qualified
    )
    closing_soon = sum(
        1 for r in qualified if 0 <= _days_until(r["closing_date"]) <= 30
    )
    return {
        "total": len(rows),
        "qualified": len(qualified),
        "pipeline_value_aud": total_value,
        "closing_soon": closing_soon,
    }


def _card_html(row: sqlite3.Row) -> str:
    """Render one qualified-tender card."""
    closing_text, closing_cls = _closing_label(row["closing_date"])
    score = int(row["display_score"])
    score_cls = _score_class(score)

    return f"""
    <article class="card">
      <div class="card-head">
        <div class="score {score_cls}">
          <div class="score-num">{score}</div>
          <div class="score-lbl">SCORE</div>
        </div>
        <div class="card-title">
          <h3>{html.escape(row['title'])}</h3>
          <div class="agency">{html.escape(row['agency'])}</div>
        </div>
      </div>

      <div class="rationale">{html.escape(row['rationale'])}</div>

      <div class="card-meta">
        <div class="meta-item">
          <div class="meta-lbl">Value</div>
          <div class="meta-val">{_fmt_value_range(row)}</div>
        </div>
        <div class="meta-item">
          <div class="meta-lbl">Location</div>
          <div class="meta-val">{html.escape(row['location'])}</div>
        </div>
        <div class="meta-item">
          <div class="meta-lbl">Closing</div>
          <div class="meta-val urgency-{closing_cls}">{closing_text}</div>
        </div>
        <div class="meta-item">
          <div class="meta-lbl">Source</div>
          <div class="meta-val">{html.escape(row['source'])}</div>
        </div>
      </div>

      <div class="card-foot">
        <span class="tender-id">{html.escape(row['tender_id'])}</span>
        <a href="{html.escape(row['url'])}" class="open-link">View tender &rarr;</a>
      </div>
    </article>
    """


def _table_row_html(row: sqlite3.Row) -> str:
    """Render one sub-threshold tender as a compact table row."""
    closing_text, closing_cls = _closing_label(row["closing_date"])
    return f"""
    <tr>
      <td class="tr-score">{int(row['display_score'])}</td>
      <td>
        <div class="tr-title">{html.escape(row['title'])}</div>
        <div class="tr-rationale">{html.escape(row['rationale'])}</div>
      </td>
      <td>{html.escape(row['agency'])}</td>
      <td>{_fmt_value_range(row)}</td>
      <td class="urgency-{closing_cls}">{closing_text}</td>
    </tr>
    """


def render(rows: list[sqlite3.Row], output_path: str | Path,
           company_name: str = "Subsea Solutions Pty Ltd") -> Path:
    """Render the dashboard HTML to disk and return the path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    stats = _summary_stats(rows)
    qualified = [r for r in rows if r["qualified"]]
    others    = [r for r in rows if not r["qualified"]]
    generated = datetime.now().strftime("%d %b %Y, %H:%M")

    cards_html = "\n".join(_card_html(r) for r in qualified) or (
        '<div class="empty">No qualified opportunities in this run.</div>'
    )
    table_rows_html = "\n".join(_table_row_html(r) for r in others)

    pipeline_m = stats["pipeline_value_aud"] / 1_000_000

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Tender Opportunity Scanner — Dashboard</title>
<style>
  :root {{
    --navy: #0B3D5C;
    --teal: #2A8E9A;
    --coral: #FF7A1A;
    --sand: #F3EFE6;
    --ink: #1A1A1A;
    --muted: #6B7785;
    --line: #DDE3EA;
    --green: #2F8F4F;
    --amber: #C77700;
    --red: #C3392C;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Helvetica, Arial, sans-serif;
    background: #F7F8FA;
    color: var(--ink);
    line-height: 1.5;
  }}

  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 24px 64px; }}

  /* ---- HEADER ---- */
  header.dash-header {{
    background: var(--navy);
    color: white;
    padding: 28px 32px;
    border-radius: 8px;
    margin-bottom: 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 16px;
  }}
  .brand h1 {{
    font-size: 22px;
    letter-spacing: -0.3px;
    margin-bottom: 4px;
  }}
  .brand .sub {{
    font-size: 12px;
    color: #B5C2D1;
    letter-spacing: 1.5px;
    text-transform: uppercase;
  }}
  .gen {{
    font-size: 12px;
    color: #B5C2D1;
    text-align: right;
  }}
  .gen strong {{ color: white; display: block; font-size: 14px; }}

  /* ---- KPI ROW ---- */
  .kpis {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 32px;
  }}
  .kpi {{
    background: white;
    padding: 18px 20px;
    border-radius: 8px;
    border-left: 4px solid var(--coral);
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }}
  .kpi .v {{
    font-size: 28px;
    font-weight: 800;
    color: var(--navy);
    letter-spacing: -0.5px;
  }}
  .kpi .v small {{ font-size: 14px; color: var(--muted); font-weight: 500; }}
  .kpi .l {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 4px;
  }}

  /* ---- SECTION HEADINGS ---- */
  h2.section {{
    font-size: 14px;
    color: var(--navy);
    text-transform: uppercase;
    letter-spacing: 2px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--coral);
    margin: 0 0 18px;
    display: inline-block;
  }}

  /* ---- CARDS ---- */
  .cards {{
    display: grid;
    grid-template-columns: 1fr;
    gap: 14px;
    margin-bottom: 40px;
  }}
  .card {{
    background: white;
    border-radius: 8px;
    padding: 20px 22px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    border: 1px solid var(--line);
  }}
  .card-head {{
    display: flex;
    gap: 18px;
    align-items: flex-start;
    margin-bottom: 12px;
  }}
  .score {{
    flex: 0 0 64px;
    border-radius: 8px;
    padding: 10px 0;
    text-align: center;
    color: white;
  }}
  .score-num {{ font-size: 22px; font-weight: 800; line-height: 1; }}
  .score-lbl {{
    font-size: 8.5px;
    letter-spacing: 1.5px;
    margin-top: 4px;
    opacity: 0.85;
  }}
  .score-excellent {{ background: var(--green); }}
  .score-strong    {{ background: var(--teal); }}
  .score-ok        {{ background: var(--amber); }}
  .score-weak      {{ background: var(--muted); }}

  .card-title {{ flex: 1; min-width: 0; }}
  .card-title h3 {{
    font-size: 15px;
    color: var(--navy);
    font-weight: 700;
    line-height: 1.35;
    margin-bottom: 3px;
  }}
  .agency {{ font-size: 12px; color: var(--muted); }}

  .rationale {{
    font-size: 12.5px;
    color: var(--ink);
    background: var(--sand);
    padding: 10px 14px;
    border-radius: 6px;
    border-left: 3px solid var(--coral);
    margin-bottom: 14px;
  }}

  .card-meta {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--line);
  }}
  .meta-lbl {{
    font-size: 9.5px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 2px;
  }}
  .meta-val {{
    font-size: 12.5px;
    color: var(--ink);
    font-weight: 600;
  }}

  .urgency-urgent {{ color: var(--red); }}
  .urgency-soon   {{ color: var(--amber); }}
  .urgency-later  {{ color: var(--ink); }}
  .urgency-closed {{ color: var(--muted); text-decoration: line-through; }}

  .card-foot {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 14px;
    padding-top: 10px;
    border-top: 1px solid var(--line);
    font-size: 11.5px;
    color: var(--muted);
  }}
  .tender-id {{ font-family: "SF Mono", Menlo, Consolas, monospace; }}
  .open-link {{
    color: var(--teal);
    text-decoration: none;
    font-weight: 600;
  }}
  .open-link:hover {{ text-decoration: underline; }}

  /* ---- TABLE (others) ---- */
  table.others {{
    width: 100%;
    border-collapse: collapse;
    background: white;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    font-size: 12.5px;
  }}
  table.others th {{
    background: var(--navy);
    color: white;
    text-align: left;
    padding: 10px 14px;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  table.others td {{
    padding: 10px 14px;
    border-top: 1px solid var(--line);
    vertical-align: top;
  }}
  .tr-score {{
    font-weight: 700;
    color: var(--muted);
    width: 50px;
  }}
  .tr-title {{ font-weight: 600; color: var(--ink); margin-bottom: 3px; }}
  .tr-rationale {{ color: var(--muted); font-size: 11.5px; }}

  /* ---- FOOTER ---- */
  footer.dash-footer {{
    margin-top: 40px;
    padding-top: 18px;
    border-top: 1px solid var(--line);
    font-size: 11px;
    color: var(--muted);
    text-align: center;
    font-style: italic;
  }}

  .empty {{
    background: white;
    padding: 32px;
    border-radius: 8px;
    text-align: center;
    color: var(--muted);
  }}

  @media (max-width: 720px) {{
    .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    .card-meta {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="dash-header">
    <div class="brand">
      <h1>Tender Opportunity Scanner</h1>
      <div class="sub">For: {html.escape(company_name)}</div>
    </div>
    <div class="gen">
      <strong>{generated}</strong>
      Dashboard last refreshed
    </div>
  </header>

  <section class="kpis">
    <div class="kpi">
      <div class="v">{stats['qualified']}<small> / {stats['total']}</small></div>
      <div class="l">Qualified tenders</div>
    </div>
    <div class="kpi">
      <div class="v">${pipeline_m:.1f}<small>M AUD</small></div>
      <div class="l">Qualified pipeline value</div>
    </div>
    <div class="kpi">
      <div class="v">{stats['closing_soon']}</div>
      <div class="l">Closing within 30 days</div>
    </div>
    <div class="kpi">
      <div class="v">{stats['total']}</div>
      <div class="l">Total scanned</div>
    </div>
  </section>

  <h2 class="section">Qualified opportunities</h2>
  <div class="cards">
    {cards_html}
  </div>

  <h2 class="section">Filtered out (below threshold)</h2>
  <table class="others">
    <thead>
      <tr>
        <th>Score</th>
        <th>Tender</th>
        <th>Agency</th>
        <th>Value</th>
        <th>Closing</th>
      </tr>
    </thead>
    <tbody>
      {table_rows_html}
    </tbody>
  </table>

  <footer class="dash-footer">
    Generated by the Tender Opportunity Scanner (portfolio piece).
    Sample data shown for demo purposes — see README for live-source notes.
  </footer>

</div>
</body>
</html>
"""
    output_path.write_text(doc, encoding="utf-8")
    return output_path
