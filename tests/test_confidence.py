"""
Tests for the confidence scorer (ordinal levels).

Assertions are framed against the schema's real per-field-class minimum levels
(`threshold_for`): what matters is which side of the auto-commit bar the corpus's
decisive fields land on. A clean SKU auto-commits; an ambiguous or off-nominal
one is flagged; a hedged quantity is flagged; a cross-artifact conflict drops to
SEVERE, the alarm floor.
"""

from __future__ import annotations

from src.confidence import Signals, explain, score
from src.schema import Confidence, threshold_for


def _auto(path: str, s: Signals) -> bool:
    """Would apply_policy auto-commit this field? (level >= the field's minimum)"""
    return score(path, s) >= threshold_for(path)


# --------------------------------------------------------------------------
# Absent value -> the alarm floor
# --------------------------------------------------------------------------

def test_absent_value_is_severe():
    assert score("customer.company_name", Signals(present=False)) is Confidence.SEVERE
    # ...even if the model claimed certainty. No value, no confidence.
    assert score("line_items[0].quantity",
                 Signals(present=False, model_level=Confidence.CERTAIN)) is Confidence.SEVERE


# --------------------------------------------------------------------------
# Email / phone — format-gated identity fields (bar is CERTAIN)
# --------------------------------------------------------------------------

def test_valid_email_auto_commits():
    assert _auto("customer.primary_contact.email",
                 Signals(model_level=Confidence.HIGH, regex_valid=True))

def test_malformed_email_is_severe():
    s = Signals(model_level=Confidence.CERTAIN, regex_valid=False)
    assert score("customer.primary_contact.email", s) is Confidence.SEVERE
    assert not _auto("customer.primary_contact.email", s)

def test_unvalidated_email_is_flagged():
    # No regex result -> capped at MEDIUM, can't clear the CERTAIN identity bar.
    assert not _auto("customer.primary_contact.email",
                     Signals(model_level=Confidence.HIGH, regex_valid=None))

def test_valid_phone_auto_commits():
    assert _auto("customer.primary_contact.phone",
                 Signals(model_level=Confidence.HIGH, regex_valid=True))


# --------------------------------------------------------------------------
# SKU matching (bar is HIGH)
# --------------------------------------------------------------------------

def test_clean_strong_sku_match_auto_commits():
    assert _auto("line_items[0].matched_sku",
                 Signals(match_score=0.85, ambiguous=False))

def test_ambiguous_sku_is_severe():
    # L007: "the big walnut one" -> several MER-CT-*; a decline, not a guess.
    s = Signals(match_score=0.41, ambiguous=True)
    assert score("line_items[0].matched_sku", s) is Confidence.SEVERE
    assert not _auto("line_items[0].matched_sku", s)

def test_off_nominal_metric_sku_is_flagged():
    # L008: 1800mm = 70.87in must not snap confidently to the 72" SKU.
    s = Signals(match_score=0.65, off_nominal=True)
    assert score("line_items[0].matched_sku", s) is Confidence.MEDIUM
    assert not _auto("line_items[0].matched_sku", s)

def test_borderline_clean_sku_gets_a_glance():
    assert not _auto("line_items[0].matched_sku", Signals(match_score=0.58))


# --------------------------------------------------------------------------
# Quantity (bar is HIGH — a qty error scales the whole quote)
# --------------------------------------------------------------------------

def test_clean_confident_quantity_auto_commits():
    assert _auto("line_items[0].quantity",
                 Signals(model_level=Confidence.HIGH, normalized_ok=True, hedged=False))

def test_hedged_quantity_is_flagged():
    # L006: "four, maybe five".
    s = Signals(model_level=Confidence.HIGH, normalized_ok=True, hedged=True)
    assert score("line_items[0].quantity", s) is Confidence.LOW
    assert not _auto("line_items[0].quantity", s)


# --------------------------------------------------------------------------
# Dates (bar is HIGH)
# --------------------------------------------------------------------------

def test_parsed_date_auto_commits():
    assert _auto("project.requested_delivery",
                 Signals(model_level=Confidence.HIGH, normalized_ok=True))

def test_unparsed_date_is_severe():
    assert score("project.quote_deadline",
                 Signals(model_level=Confidence.HIGH, normalized_ok=False)) is Confidence.SEVERE


# --------------------------------------------------------------------------
# Cross-artifact agreement / conflict
# --------------------------------------------------------------------------

def test_conflict_drops_to_severe_and_flags_a_finish():
    # L014: a finish that would auto-commit (bar is only LOW) must not, on conflict.
    base = Signals(model_level=Confidence.HIGH)
    assert _auto("line_items[0].finish", base)                       # would pass
    conflict = Signals(model_level=Confidence.HIGH, cross_artifact="conflict")
    assert score("line_items[0].finish", conflict) is Confidence.SEVERE
    assert not _auto("line_items[0].finish", conflict)

def test_agreement_corroborates_one_rung():
    lone = score("customer.company_name", Signals(model_level=Confidence.MEDIUM))
    agree = score("customer.company_name",
                  Signals(model_level=Confidence.MEDIUM, cross_artifact="agree"))
    assert agree > lone
    assert agree is Confidence.HIGH


# --------------------------------------------------------------------------
# Determinism / index-insensitivity
# --------------------------------------------------------------------------

def test_scores_are_levels_and_deterministic():
    s = Signals(model_level=Confidence.HIGH, regex_valid=True, cross_artifact="agree")
    a = score("customer.primary_contact.email", s)
    assert a is score("customer.primary_contact.email", s)
    assert isinstance(a, Confidence)

def test_index_insensitive_path():
    s = Signals(match_score=0.85)
    assert score("line_items[0].matched_sku", s) == score("line_items[3].matched_sku", s)


# --------------------------------------------------------------------------
# explain() — plain-English "why flagged"
# --------------------------------------------------------------------------

def test_explain_names_the_deterministic_reason():
    assert "not stated" in explain("customer.company_name", Signals(present=False))
    assert "ambiguous" in explain("line_items[0].matched_sku", Signals(ambiguous=True))
    assert "between two nominal" in explain("line_items[0].matched_sku",
                                            Signals(off_nominal=True, match_score=0.65))
    assert "hedged" in explain("line_items[0].quantity", Signals(hedged=True))
    assert "disagree" in explain("line_items[0].finish", Signals(cross_artifact="conflict"))
    assert "valid email" in explain("customer.primary_contact.email", Signals(regex_valid=False))
    assert "parse" in explain("project.requested_delivery", Signals(normalized_ok=False))

def test_explain_returns_none_for_clean_fields():
    assert explain("customer.company_name", Signals(model_level=Confidence.HIGH)) is None
    assert explain("line_items[0].matched_sku", Signals(match_score=0.9)) is None
