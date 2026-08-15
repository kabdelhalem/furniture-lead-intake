"""
Per-field confidence scoring — the layer the whole project is arguing for.

Confidence is an ordinal LEVEL, not a float (see `schema.Confidence`). The model
reports a level ("high", "low"), which is more reliable than a made-up
probability — but we never trust it alone. `score(path, signals)` blends the
model's level with the *deterministic* signals it can't fake (format-regex
validity, SKU fuzzy-match strength, clean normalization, source hedging,
cross-artifact conflict), promoting or demoting on the ladder to a final level.

The result says nothing about whether that level is *good enough* — that's
`apply_policy`, which compares it against the per-field-class minimum level. The
bands are tuned so the corpus lands where ground truth says: a clean unique SKU
reaches its bar, while an ambiguous match (L007), an off-nominal metric size
(L008), a hedged quantity (L006), and a cross-artifact conflict (L014) all fall
into the review band — the last straight to SEVERE, the alarm floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Confidence

# The ladder, indexed by rank (SEVERE=0 .. CERTAIN=4).
_LEVELS = [Confidence.SEVERE, Confidence.LOW, Confidence.MEDIUM,
           Confidence.HIGH, Confidence.CERTAIN]


def _at(rank: int) -> Confidence:
    """A level from a (clamped) rank."""
    return _LEVELS[max(0, min(len(_LEVELS) - 1, rank))]


@dataclass
class Signals:
    """Everything known about one extracted field, model and deterministic alike.

    The extractor fills what applies to the field's class and leaves the rest at
    its default; `score` reads only the signals relevant to that class.
    """
    present: bool = True                    # a value was extracted at all
    model_level: Confidence | None = None   # the model's self-reported level (or None)
    regex_valid: bool | None = None         # email/phone passed format validation
    normalized_ok: bool | None = None       # a normalizer parsed the value cleanly
    match_score: float | None = None        # SKU fuzzy-match score (matching.py)
    ambiguous: bool = False                 # matcher flagged near-ties / low separation
    off_nominal: bool = False               # value between two nominal SKU sizes (L008)
    hedged: bool = False                    # source hedged the value ("four, maybe five")
    cross_artifact: str | None = None       # "agree" | "conflict" | None


# Field classes, keyed by the index-insensitive generic path.
_EMAIL = "customer.primary_contact.email"
_PHONE = "customer.primary_contact.phone"
_SKU = "line_items[].matched_sku"
_QTY = "line_items[].quantity"
_DIMENSIONS = {
    "line_items[].dimensions.width_in",
    "line_items[].dimensions.depth_in",
    "line_items[].dimensions.height_in",
}
_DATES = {"project.requested_delivery", "project.quote_deadline"}


def _generic_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


# --------------------------------------------------------------------------
# Per-class scorers
# --------------------------------------------------------------------------

def _format_field(ml: Confidence, valid: bool | None) -> Confidence:
    """Email / phone: a format regex is a strong, cheap signal. Valid clears the
    identity bar; malformed drops to the alarm floor; unverifiable stays capped."""
    if valid is True:
        return Confidence.CERTAIN if ml >= Confidence.MEDIUM else Confidence.HIGH
    if valid is False:
        return Confidence.SEVERE
    return min(ml, Confidence.MEDIUM)


def _sku(ml: Confidence, s: Signals) -> Confidence:
    """Matched SKU: the fuzzy-match score dominates. An ambiguous match (L007) is
    SEVERE — a decline, not a guess; an off-nominal size (L008) is held to MEDIUM,
    below the HIGH bar; a clean match scales with the match strength."""
    if s.ambiguous:
        return Confidence.SEVERE
    if s.off_nominal:
        return Confidence.MEDIUM
    ms = s.match_score if s.match_score is not None else 0.70
    if ms >= 0.80:
        return Confidence.CERTAIN
    if ms >= 0.62:
        return Confidence.HIGH
    return Confidence.MEDIUM


def _quantity(ml: Confidence, s: Signals) -> Confidence:
    """Quantity: a hedged source ("four, maybe five") is held to LOW, below the
    strict bar. A clean parse the model is at least moderately sure of clears it."""
    if s.hedged:
        return Confidence.LOW
    if s.normalized_ok and ml >= Confidence.MEDIUM:
        return Confidence.HIGH
    return ml


def _normalized(ml: Confidence, ok: bool | None) -> Confidence:
    """Dates and dimensions: gated on whether the normalizer parsed cleanly."""
    if ok is True:
        return max(ml, Confidence.HIGH)
    if ok is False:
        return Confidence.SEVERE
    return ml


def _generic(ml: Confidence, s: Signals) -> Confidence:
    """Descriptive / identity fields: model-led, but a failed normalization drags
    it down two rungs."""
    if s.normalized_ok is False:
        return _at(ml.rank - 2)
    return ml


def _apply_cross_artifact(c: Confidence, mode: str | None) -> Confidence:
    """Agreement corroborates (one rung up); a conflict (L014) is an alarm — it
    must not resolve silently, so it drops straight to SEVERE."""
    if mode == "agree":
        return _at(c.rank + 1)
    if mode == "conflict":
        return Confidence.SEVERE
    return c


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def score(path: str, signals: Signals) -> Confidence:
    """Calibrated confidence LEVEL for the field at `path`.

    A field with no extracted value is SEVERE — `apply_policy` reads the missing
    value as NOT_FOUND. Everything else routes to its field-class scorer, then
    picks up any cross-artifact adjustment.
    """
    if not signals.present:
        return Confidence.SEVERE

    ml = signals.model_level if signals.model_level is not None else Confidence.MEDIUM
    g = _generic_path(path)

    if g in (_EMAIL, _PHONE):
        c = _format_field(ml, signals.regex_valid)
    elif g == _SKU:
        c = _sku(ml, signals)
    elif g == _QTY:
        c = _quantity(ml, signals)
    elif g in _DATES or g in _DIMENSIONS:
        c = _normalized(ml, signals.normalized_ok)
    else:
        c = _generic(ml, signals)

    return _apply_cross_artifact(c, signals.cross_artifact)
