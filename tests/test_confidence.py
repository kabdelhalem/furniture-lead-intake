"""
Tests for the confidence scorer.

The assertions are framed against the schema's real per-field thresholds
(`threshold_for`) rather than magic numbers: what matters is not the exact score
but which side of the review bar the corpus's decisive fields land on. A clean
SKU auto-commits; an ambiguous or off-nominal one is flagged; a hedged quantity
is flagged; a cross-artifact conflict is flagged.
"""

from __future__ import annotations

from src.confidence import Signals, score
from src.schema import threshold_for


def _auto(path: str, s: Signals) -> bool:
    """Would apply_policy auto-commit this field?"""
    return score(path, s) >= threshold_for(path)


# --------------------------------------------------------------------------
# Absent value
# --------------------------------------------------------------------------

def test_absent_value_scores_zero():
    assert score("customer.company_name", Signals(present=False)) == 0.0
    # ...even if the model claimed certainty. No value, no confidence.
    assert score("line_items[0].quantity", Signals(present=False, model_certainty=0.99)) == 0.0


# --------------------------------------------------------------------------
# Email / phone — format-gated identity fields (bar is 0.95)
# --------------------------------------------------------------------------

def test_valid_email_auto_commits():
    s = Signals(model_certainty=0.85, regex_valid=True)
    assert _auto("customer.primary_contact.email", s)

def test_malformed_email_is_flagged():
    s = Signals(model_certainty=0.99, regex_valid=False)
    assert not _auto("customer.primary_contact.email", s)

def test_unvalidated_email_is_flagged():
    # No regex result available -> can't clear the strict 0.95 identity bar.
    s = Signals(model_certainty=0.9, regex_valid=None)
    assert not _auto("customer.primary_contact.email", s)

def test_valid_phone_auto_commits():
    s = Signals(model_certainty=0.85, regex_valid=True)
    assert _auto("customer.primary_contact.phone", s)


# --------------------------------------------------------------------------
# SKU matching (bar is 0.90)
# --------------------------------------------------------------------------

def test_clean_strong_sku_match_auto_commits():
    # A well-separated exact match (matcher ~0.85) with a confident model.
    s = Signals(model_certainty=0.85, match_score=0.85, ambiguous=False)
    assert _auto("line_items[0].matched_sku", s)

def test_ambiguous_sku_is_flagged():
    # L007: "the big walnut one" -> several MER-CT-*; matcher score ~0.40.
    s = Signals(model_certainty=0.9, match_score=0.41, ambiguous=True)
    assert not _auto("line_items[0].matched_sku", s)
    assert score("line_items[0].matched_sku", s) <= 0.60

def test_off_nominal_metric_sku_is_flagged():
    # L008: 1800mm = 70.87in must not snap confidently to the 72" SKU.
    s = Signals(model_certainty=0.95, match_score=0.65, off_nominal=True)
    assert not _auto("line_items[0].matched_sku", s)

def test_borderline_clean_sku_gets_a_glance():
    # A clean but weak match (low matcher score) should not auto-commit.
    s = Signals(model_certainty=0.6, match_score=0.60, ambiguous=False)
    assert not _auto("line_items[0].matched_sku", s)


# --------------------------------------------------------------------------
# Quantity (bar is 0.92 — a qty error scales the whole quote)
# --------------------------------------------------------------------------

def test_clean_confident_quantity_auto_commits():
    s = Signals(model_certainty=0.95, normalized_ok=True, hedged=False)
    assert _auto("line_items[0].quantity", s)

def test_hedged_quantity_is_flagged():
    # L006: "four, maybe five".
    s = Signals(model_certainty=0.9, normalized_ok=True, hedged=True)
    assert not _auto("line_items[0].quantity", s)
    assert score("line_items[0].quantity", s) <= 0.60


# --------------------------------------------------------------------------
# Dates (bar is 0.85)
# --------------------------------------------------------------------------

def test_parsed_date_auto_commits():
    s = Signals(model_certainty=0.9, normalized_ok=True)
    assert _auto("project.requested_delivery", s)

def test_unparsed_date_is_flagged():
    s = Signals(model_certainty=0.9, normalized_ok=False)
    assert not _auto("project.quote_deadline", s)


# --------------------------------------------------------------------------
# Cross-artifact agreement / conflict
# --------------------------------------------------------------------------

def test_conflict_flags_a_finish_that_would_otherwise_pass():
    # L014: spec PDF says oat, qty sheet says slate. Finish bar is only 0.65,
    # so a confident model would normally auto-commit — the conflict must not.
    base = Signals(model_certainty=0.95)
    assert _auto("line_items[0].finish", base)                       # would pass
    conflict = Signals(model_certainty=0.95, cross_artifact="conflict")
    assert not _auto("line_items[0].finish", conflict)               # must not

def test_agreement_corroborates():
    lone = score("customer.company_name", Signals(model_certainty=0.7))
    agree = score("customer.company_name", Signals(model_certainty=0.7, cross_artifact="agree"))
    assert agree > lone


# --------------------------------------------------------------------------
# Bounds and determinism
# --------------------------------------------------------------------------

def test_scores_are_bounded_and_deterministic():
    s = Signals(model_certainty=0.8, regex_valid=True, cross_artifact="agree")
    a = score("customer.primary_contact.email", s)
    b = score("customer.primary_contact.email", s)
    assert a == b
    assert 0.0 <= a <= 1.0

def test_index_insensitive_path():
    s = Signals(model_certainty=0.9, match_score=0.85)
    assert score("line_items[0].matched_sku", s) == score("line_items[3].matched_sku", s)
