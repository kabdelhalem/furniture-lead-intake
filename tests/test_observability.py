"""
Tests for calibration observability.

Leads are hand-built with specific (confidence, status) pairs so each review
outcome is unambiguous: an auto-committed field that got corrected is a false
auto-commit (tighten), a flagged field that got confirmed is an over-flag
(loosen).
"""

from __future__ import annotations

from datetime import datetime

from src.observability import summarize
from src.schema import (
    CanonicalLead,
    Confidence,
    Correction,
    Extracted,
    FieldStatus,
    LineItem,
    threshold_for,
)


def _reviewed_lead() -> CanonicalLead:
    lead = CanonicalLead(lead_id="X", received_at=datetime(2026, 8, 14))
    # email bar is CERTAIN. Confidence CERTAIN -> auto-committed; corrected anyway
    # => false auto-commit (we were confidently wrong).
    lead.customer.primary_contact.email = Extracted(
        value="a@b.com", confidence=Confidence.CERTAIN, status=FieldStatus.HUMAN_CORRECTED)
    # company bar is HIGH. Confidence HIGH -> auto-committed; confirmed => normal.
    lead.customer.company_name = Extracted(
        value="Acme", confidence=Confidence.HIGH, status=FieldStatus.HUMAN_CONFIRMED)
    li = LineItem()
    # quantity bar is HIGH. Confidence LOW -> flagged; corrected => normal correction.
    li.quantity = Extracted(value=8, confidence=Confidence.LOW, status=FieldStatus.HUMAN_CORRECTED)
    # finish bar is LOW. Confidence SEVERE -> flagged; confirmed => over-flag.
    li.finish = Extracted(value="oat", confidence=Confidence.SEVERE, status=FieldStatus.HUMAN_CONFIRMED)
    lead.line_items = [li]
    lead.review.corrections = [
        Correction(field_path="customer.primary_contact.email", reason_code="wrong_email"),
        Correction(field_path="line_items[0].quantity", reason_code="unit_error"),
    ]
    return lead


def test_totals():
    s = summarize([_reviewed_lead()])
    assert s["reviewed_fields"] == 4
    assert s["corrections"] == 2 and s["confirmations"] == 2
    assert s["false_auto_commits"] == 1     # the email
    assert s["over_flags"] == 1             # the finish


def test_false_auto_commit_recommends_tighten():
    s = summarize([_reviewed_lead()])
    email = s["by_field_class"]["customer.primary_contact.email"]
    assert email["corrected"] == 1 and email["false_auto_commits"] == 1
    assert email["suggestion"] == "tighten"
    assert email["current_min_level"] == "certain"


def test_over_flag_recommends_loosen():
    s = summarize([_reviewed_lead()])
    finish = s["by_field_class"]["line_items[].finish"]
    assert finish["confirmed"] == 1 and finish["over_flags"] == 1
    assert finish["suggestion"] == "loosen"


def test_normal_outcomes_are_ok():
    s = summarize([_reviewed_lead()])
    # flagged-then-corrected and auto-then-confirmed are the system working.
    assert s["by_field_class"]["line_items[].quantity"]["suggestion"] == "ok"
    assert s["by_field_class"]["line_items[].quantity"]["false_auto_commits"] == 0
    assert s["by_field_class"]["customer.company_name"]["suggestion"] == "ok"
    assert s["by_field_class"]["customer.company_name"]["over_flags"] == 0


def test_reason_codes_counted():
    s = summarize([_reviewed_lead()])
    assert s["reason_codes"] == {"wrong_email": 1, "unit_error": 1}


def test_unreviewed_fields_are_ignored():
    # A fresh lead nobody has reviewed contributes nothing.
    lead = CanonicalLead(lead_id="Y", received_at=datetime(2026, 8, 14))
    lead.customer.company_name = Extracted(value="Acme", confidence=Confidence.HIGH,
                                           status=FieldStatus.AUTO_COMMITTED)
    s = summarize([lead])
    assert s["reviewed_fields"] == 0 and s["by_field_class"] == {}


def test_was_flagged_matches_the_threshold():
    # Sanity: the flag reconstruction uses the same bar apply_policy would.
    assert Confidence.SEVERE < threshold_for("line_items[].finish")   # flagged
    assert Confidence.CERTAIN >= threshold_for("customer.primary_contact.email")  # auto
