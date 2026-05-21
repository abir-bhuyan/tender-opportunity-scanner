"""
scanner.scoring
===============

Relevance scoring engine.

The scoring algorithm assigns each tender a numeric score reflecting how
well it matches a configured service profile. The design prioritises:

    1. **Tier-weighted keyword matching** so that a strong direct
       signal ("subsea inspection") outweighs many weak signals.
    2. **Geographic multipliers** because for a Perth-based vendor a
       WA opportunity is worth materially more than an east-coast one.
    3. **Negative keywords** that actively reject wrong-industry
       tenders sharing surface vocabulary (e.g. "cleaning services").
    4. **Time and value bonuses** that reward urgency and scale.

The output is a Score object containing the numeric score, a list of
matched signals, and a short human-readable rationale that explains
*why* a tender ranked where it did — important for a sales team
deciding whether to invest tender-response effort.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

# YAML is the only non-stdlib dependency. PyYAML is in pip-standard
# distributions on Python 3.x and the conftest pins it in requirements.
try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyYAML is required. Install with: pip install pyyaml"
    ) from exc


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """A single match that contributed to a tender's score."""
    kind: str          # e.g. "tier_1", "negative", "geographic"
    term: str          # the matched phrase
    points: float      # signed contribution to the score


@dataclass
class Score:
    """Result of scoring a single tender."""
    tender_id: str
    raw_score: float
    display_score: int       # capped 0..100 for the dashboard
    qualified: bool          # above the configured threshold
    signals: list[Signal] = field(default_factory=list)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> dict[str, Any]:
    """Load the YAML keyword configuration."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    # Light validation — fail fast on missing top-level keys
    for required in ("tier_1", "tier_2", "tier_3", "negative",
                     "geographic_boost", "qualified_threshold"):
        if required not in cfg:
            raise ValueError(
                f"Config {path} missing required key: {required!r}"
            )
    return cfg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haystack(tender: dict[str, Any]) -> str:
    """Concatenate the searchable fields of a tender, lowercased."""
    parts = (
        tender.get("title", ""),
        tender.get("description", ""),
        tender.get("category", ""),
        tender.get("location", ""),
    )
    return " ".join(str(p).lower() for p in parts)


def _days_until(closing: str) -> int:
    """Days from today to the tender's closing date (negative if past)."""
    try:
        close = date.fromisoformat(closing)
    except (TypeError, ValueError):
        return 9999
    return (close - date.today()).days


def _value_for_bonus(tender: dict[str, Any]) -> float:
    """Take the midpoint of the min/max value range, or 0 if not given."""
    lo = tender.get("value_aud_min") or 0
    hi = tender.get("value_aud_max") or 0
    if lo and hi:
        return (float(lo) + float(hi)) / 2
    return float(lo or hi)


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score_tender(tender: dict[str, Any], cfg: dict[str, Any]) -> Score:
    """Compute a relevance score for a single tender against the config."""
    text = _haystack(tender)
    signals: list[Signal] = []
    score = 0.0

    # --- tiered keyword matches ---------------------------------------
    for tier_name, tier_kind in (
        ("tier_1", "tier_1"),
        ("tier_2", "tier_2"),
        ("tier_3", "tier_3"),
    ):
        tier = cfg[tier_name]
        weight = float(tier["weight"])
        for term in tier["terms"]:
            if term.lower() in text:
                signals.append(Signal(tier_kind, term, weight))
                score += weight

    # --- sector boost --------------------------------------------------
    sector = cfg.get("sector_boost", {})
    sector_weight = float(sector.get("weight", 0))
    for term in sector.get("terms", []):
        if term.lower() in text:
            signals.append(Signal("sector", term, sector_weight))
            score += sector_weight
            break  # one match is enough; avoid double-counting

    # --- negative keywords ---------------------------------------------
    neg = cfg.get("negative", {})
    neg_weight = float(neg.get("weight", 0))   # already negative
    for term in neg.get("terms", []):
        if term.lower() in text:
            signals.append(Signal("negative", term, neg_weight))
            score += neg_weight

    # --- value bonus ---------------------------------------------------
    vb = cfg.get("value_bonus", {})
    value = _value_for_bonus(tender)
    if value >= 10_000_000:
        bonus = float(vb.get("above_10m", 0))
        signals.append(Signal("value", ">$10M", bonus))
        score += bonus
    elif value >= 2_000_000:
        bonus = float(vb.get("above_2m", 0))
        signals.append(Signal("value", ">$2M", bonus))
        score += bonus
    elif value >= 500_000:
        bonus = float(vb.get("above_500k", 0))
        signals.append(Signal("value", ">$500k", bonus))
        score += bonus

    # --- time bonus ----------------------------------------------------
    tb = cfg.get("time_bonus", {})
    days = _days_until(tender.get("closing_date", ""))
    if 0 <= days <= 30:
        bonus = float(tb.get("closing_within_30_days", 0))
        signals.append(Signal("time", "<30 days", bonus))
        score += bonus
    elif 0 <= days <= 60:
        bonus = float(tb.get("closing_within_60_days", 0))
        signals.append(Signal("time", "<60 days", bonus))
        score += bonus

    # --- geographic multiplier -----------------------------------------
    # Applied last so it operates on the already-accumulated positive
    # base. We only apply the boost if there's a positive base to amplify
    # — multiplying a negative score makes the geographic match look
    # like it's hurting the tender, which would mislead the operator.
    geo = cfg.get("geographic_boost", {})
    geo_mult = float(geo.get("multiplier", 1.0))
    if score > 0:
        for term in geo.get("terms", []):
            if term.lower() in text:
                pre = score
                score = score * geo_mult
                gained = score - pre
                signals.append(Signal("geographic", term, gained))
                break

    # --- assemble result ----------------------------------------------
    threshold = float(cfg.get("qualified_threshold", 40))
    display = max(0, min(100, int(round(score))))
    rationale = _explain(signals, score, threshold)

    return Score(
        tender_id=tender["tender_id"],
        raw_score=score,
        display_score=display,
        qualified=score >= threshold,
        signals=signals,
        rationale=rationale,
    )


def _explain(signals: list[Signal], score: float, threshold: float) -> str:
    """Build a one-sentence rationale string for the dashboard."""
    if not signals:
        return "No relevant signals detected."

    # Group positive / negative signals for a tidy summary
    positives = [s for s in signals if s.points > 0]
    negatives = [s for s in signals if s.points < 0]
    geo_hits = [s for s in signals if s.kind == "geographic"]

    parts: list[str] = []
    if positives:
        top_terms = sorted(positives, key=lambda s: -s.points)[:3]
        parts.append(
            "Matches: " + ", ".join(f"'{s.term}'" for s in top_terms)
        )
    if geo_hits:
        parts.append("WA-relevant location")
    if negatives:
        parts.append(
            "but penalised by " + ", ".join(f"'{s.term}'" for s in negatives)
        )

    verdict = (
        "Qualified for tender review." if score >= threshold
        else "Below qualification threshold."
    )
    return ". ".join(parts) + ". " + verdict


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def score_all(
    tenders: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[tuple[dict[str, Any], Score]]:
    """Score a batch and return tenders paired with their Score, sorted desc."""
    results = [(t, score_tender(t, cfg)) for t in tenders]
    results.sort(key=lambda pair: pair[1].raw_score, reverse=True)
    return results
