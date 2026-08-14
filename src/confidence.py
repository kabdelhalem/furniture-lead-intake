"""
Per-field confidence scoring — the layer the whole project is arguing for.

A field's confidence is never the model's self-report alone. Self-reported
certainty is poorly calibrated, so we fold it together with *deterministic*
signals the model can't fake: did the email/phone pass a format regex, how did
the SKU fuzzy-match score, did a normalizer parse the value cleanly, do two
artifacts agree or conflict, did the source hedge the number. Deterministic
signals dominate wherever we have them; the model's certainty only fills gaps
and breaks ties.

`score(path, signals)` returns a calibrated confidence in [0, 1]. It says
nothing about whether that confidence is *good enough* — that decision belongs
to `apply_policy()` in the schema, which compares this number against the
per-field-class threshold. Keeping the two apart is what lets the review queue
be a pure function of confidence and thresholds (move a slider, the queue
resizes) rather than something baked into extraction.

The score bands are tuned against the real matcher and normalizer outputs so the
corpus lands where the ground truth says it should: a clean unique SKU match can
clear its 0.90 bar and auto-commit, while an ambiguous match (L007), a metric
size that falls between two nominal SKUs (L008), a hedged quantity (L006), and a
cross-artifact finish conflict (L014) all land in the review band.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Signals:
    """Everything known about one extracted field, model and deterministic alike.

    The extractor fills what applies to the field's class and leaves the rest at
    its default; `score` reads only the signals relevant to that class.
    """
    present: bool = True                 # a value was extracted at all
    model_certainty: float | None = None # the model's self-reported 0..1 (or None)
    regex_valid: bool | None = None      # email/phone passed format validation
    normalized_ok: bool | None = None    # a normalizer parsed the value cleanly
    match_score: float | None = None     # SKU fuzzy-match score (matching.py)
    ambiguous: bool = False              # matcher flagged near-ties / low separation
    off_nominal: bool = False            # value sits between two nominal SKU sizes (L008)
    hedged: bool = False                 # source hedged the value ("four, maybe five")
    cross_artifact: str | None = None    # "agree" | "conflict" | None


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
_DATES = {
    "project.requested_delivery",
    "project.quote_deadline",
}


def _generic_path(path: str) -> str:
    """line_items[3].quantity -> line_items[].quantity (matches threshold_for)."""
    return re.sub(r"\[\d+\]", "[]", path)


def _clamp(x: float) -> float:
    return round(min(1.0, max(0.0, x)), 3)


# --------------------------------------------------------------------------
# Per-class scorers
# --------------------------------------------------------------------------

def _format_field(mc: float, valid: bool | None) -> float:
    """Email / phone: a format regex is a strong, cheap signal.

    Valid + confident clears the 0.95 identity bar (a wrong contact email is
    unrecoverable, so the bar is high on purpose); malformed is capped low.
    """
    if valid is True:
        return 0.90 + 0.09 * mc
    if valid is False:
        return 0.35
    return 0.60 + 0.30 * mc          # no validation available — moderate


def _sku(mc: float, s: Signals) -> float:
    """Matched SKU: the fuzzy-match score is the dominant signal.

    An ambiguous match (near-ties, L007) or a size that falls between two
    nominal SKUs (L008) is held below the 0.90 auto-commit bar no matter how
    sure the model claims to be. A clean, well-separated match scales with the
    match score so a strong hit can auto-commit and a borderline-clean one still
    gets a human glance.
    """
    if s.ambiguous:
        return min(0.60, s.match_score if s.match_score is not None else 0.40)
    if s.off_nominal:
        return min(0.80, 0.60 + 0.20 * mc)
    ms = s.match_score if s.match_score is not None else 0.85
    return min(0.97, 0.80 + 0.5 * (ms - 0.55) + 0.05 * mc)


def _quantity(mc: float, s: Signals) -> float:
    """Quantity: a hedged source ("four, maybe five") is capped below the strict
    0.92 bar — a qty error scales the whole quote, so uncertainty must surface.
    A clean parse scales with model certainty and can clear the bar."""
    if s.hedged:
        return min(0.60, 0.40 + 0.20 * mc)
    base = 0.75 if s.normalized_ok else 0.60
    return base + 0.20 * mc


def _normalized(mc: float, ok: bool | None) -> float:
    """Dates and dimensions: gated on whether the normalizer parsed cleanly."""
    if ok is True:
        return 0.80 + 0.17 * mc
    if ok is False:
        return 0.45
    return 0.60 + 0.30 * mc


def _generic(mc: float, s: Signals) -> float:
    """Descriptive / identity fields with no special signal: model-led, but a
    failed normalization still drags it down."""
    c = 0.55 + 0.40 * mc
    if s.normalized_ok is False:
        c *= 0.6
    return c


def _apply_cross_artifact(c: float, mode: str | None) -> float:
    """Two artifacts naming the same field: agreement is corroboration, a
    conflict (L014) must not resolve silently — damp it into the review band."""
    if mode == "agree":
        return min(0.99, c + 0.08)
    if mode == "conflict":
        return min(c, 0.50)
    return c


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def score(path: str, signals: Signals) -> float:
    """Calibrated confidence in [0, 1] for the field at `path`.

    A field with no extracted value scores 0.0 — `apply_policy` will read that
    as NOT_FOUND. Everything else routes to its field-class scorer, then picks
    up any cross-artifact adjustment.
    """
    if not signals.present:
        return 0.0

    mc = signals.model_certainty if signals.model_certainty is not None else 0.70
    g = _generic_path(path)

    if g in (_EMAIL, _PHONE):
        c = _format_field(mc, signals.regex_valid)
    elif g == _SKU:
        c = _sku(mc, signals)
    elif g == _QTY:
        c = _quantity(mc, signals)
    elif g in _DATES or g in _DIMENSIONS:
        c = _normalized(mc, signals.normalized_ok)
    else:
        c = _generic(mc, signals)

    c = _apply_cross_artifact(c, signals.cross_artifact)
    return _clamp(c)
