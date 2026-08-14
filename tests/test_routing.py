"""
Tests for the deterministic routing layer.

Leads are built by hand rather than pulled from the corpus so each test states
exactly the fields the rule under test depends on — the routing contract is
independent of extraction.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.catalog import by_sku
from src.routing import (
    ENTERPRISE_FLOOR,
    MID_MARKET_FLOOR,
    _REP_BY_REGION,
    route,
)
from src.schema import (
    CanonicalLead,
    Channel,
    Contact,
    E,
    LineItem,
)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def _lead(is_lead: bool | None = True) -> CanonicalLead:
    """A minimal lead with is_lead set. Everything else stays at defaults."""
    return CanonicalLead(
        lead_id="L-TEST",
        received_at=datetime(2026, 1, 1, 9, 0, 0),
        channel=E(Channel.EMAIL, 0.99),
        is_lead=E(is_lead, 0.99) if is_lead is not None else E(),
    )


def _line_item(sku: str | None, qty: int | None, desc: str = "") -> LineItem:
    item = LineItem(raw_description=desc)
    if sku is not None:
        item.matched_sku = E(sku, 0.95)
    if qty is not None:
        item.quantity = E(qty, 0.95)
    return item


# --------------------------------------------------------------------------
# Acceptance cases from the task
# --------------------------------------------------------------------------

def test_enterprise_case():
    """Big budget + install + named DM + TX + large line items -> enterprise."""
    lead = _lead()
    lead.project.budget_low = E(6_500_000.0, 0.9)
    lead.project.install_required = E(True, 0.9)
    lead.project.site_state = E("TX", 0.95)
    lead.customer.primary_contact = Contact(
        full_name=E("Regina Vasquez", 0.9),
        title=E("VP Facilities", 0.9),
        is_decision_maker=E(True, 0.9),
    )
    lead.line_items = [
        _line_item("VER-POD-4", 12, "12 meeting pods"),
        _line_item("MER-CT-144", 20, "20 conference tables"),
        _line_item("ASH-TSK-40", 300, "300 exec chairs"),
    ]

    route(lead)

    assert lead.routing.segment == "enterprise"
    assert len(lead.routing.rules_fired) >= 3
    assert lead.routing.priority_score >= 70
    # Territory reflects TX both as the field value and as a logged rule.
    assert lead.routing.territory == "south"
    assert "territory_TX" in lead.routing.rules_fired
    assert "value_from_budget" in lead.routing.rules_fired
    assert "segment_enterprise" in lead.routing.rules_fired
    assert lead.routing.assigned_rep == _REP_BY_REGION["south"]


def test_smb_case():
    """One small line item (8 chairs ~$5k, ASH-TSK-40 @ $1180 would be too big;
    use stacking chairs $310) -> smb, low priority."""
    lead = _lead()
    # TRV-STK list price 310 * 16 = 4960 ~ $5k, below mid-market floor.
    lead.line_items = [_line_item("TRV-STK", 16, "16 stacking chairs")]

    route(lead)

    assert lead.routing.segment == "smb"
    assert lead.routing.priority_score < 20
    assert "value_from_line_items" in lead.routing.rules_fired
    assert "segment_smb" in lead.routing.rules_fired


def test_not_a_lead_is_noop():
    """is_lead False -> routing untouched at defaults."""
    lead = _lead(is_lead=False)
    lead.project.budget_low = E(1_000_000.0, 0.9)  # would be enterprise if routed
    lead.project.site_state = E("TX", 0.95)

    returned = route(lead)

    assert returned is lead
    assert lead.routing.segment == "unclassified"
    assert lead.routing.rules_fired == []
    assert lead.routing.priority_score == 0
    assert lead.routing.territory is None
    assert lead.routing.assigned_rep is None
    assert lead.routing.routed_at is None


def test_not_a_lead_with_now_still_leaves_routed_at_none():
    """The gate must short-circuit before routed_at is stamped, even with a
    clock supplied — locks the no-op semantics against a future refactor."""
    lead = _lead(is_lead=False)
    route(lead, now=datetime(2026, 8, 14, 12, 0, 0))
    assert lead.routing.routed_at is None
    assert lead.routing.rules_fired == []


def test_is_lead_none_is_noop():
    """A never-classified lead (is_lead value None) is also a no-op."""
    lead = _lead(is_lead=None)
    lead.project.budget_low = E(1_000_000.0, 0.9)

    route(lead)

    assert lead.routing.segment == "unclassified"
    assert lead.routing.rules_fired == []


# --------------------------------------------------------------------------
# Value estimation
# --------------------------------------------------------------------------

def test_budget_high_preferred_over_low():
    lead = _lead()
    lead.project.budget_low = E(40_000.0, 0.9)
    lead.project.budget_high = E(90_000.0, 0.9)
    route(lead)
    # 90k lands in mid-market; if low (40k) had been used it would be smb.
    assert lead.routing.segment == "mid_market"
    assert "value_from_budget" in lead.routing.rules_fired


def test_budget_low_used_when_no_high():
    lead = _lead()
    lead.project.budget_low = E(60_000.0, 0.9)
    route(lead)
    assert lead.routing.segment == "mid_market"


def test_value_summed_from_line_items_matches_catalog():
    lead = _lead()
    lead.line_items = [
        _line_item("KRN-DSK-72", 10),   # 1290 * 10 = 12900
        _line_item("STO-PED-3", 10),    # 410 * 10  = 4100
    ]
    route(lead)
    expected = by_sku("KRN-DSK-72")["list_price"] * 10 + by_sku("STO-PED-3")["list_price"] * 10
    assert expected == 17_000.0
    # 17k < 50k floor -> smb, and the line-item rule fired.
    assert lead.routing.segment == "smb"
    assert "value_from_line_items" in lead.routing.rules_fired


def test_line_items_without_sku_or_qty_are_skipped():
    lead = _lead()
    lead.line_items = [
        _line_item(None, 5, "no sku"),
        _line_item("MER-CT-96", None, "no qty"),
        _line_item("NOT-A-REAL-SKU", 100, "unmatched sku"),
    ]
    route(lead)
    # Nothing contributes -> no value signal -> smb, no value rule.
    assert lead.routing.segment == "smb"
    assert not any(r.startswith("value_from") for r in lead.routing.rules_fired)


def test_no_value_signal_defaults_to_smb():
    lead = _lead()
    route(lead)
    assert lead.routing.segment == "smb"
    assert lead.routing.priority_score < 20


# --------------------------------------------------------------------------
# Segment boundaries
# --------------------------------------------------------------------------

def test_mid_market_floor_inclusive():
    lead = _lead()
    lead.project.budget_high = E(MID_MARKET_FLOOR, 0.9)
    route(lead)
    assert lead.routing.segment == "mid_market"


def test_just_below_mid_market_is_smb():
    lead = _lead()
    lead.project.budget_high = E(MID_MARKET_FLOOR - 1, 0.9)
    route(lead)
    assert lead.routing.segment == "smb"


def test_enterprise_floor_inclusive():
    lead = _lead()
    lead.project.budget_high = E(ENTERPRISE_FLOOR, 0.9)
    route(lead)
    assert lead.routing.segment == "enterprise"


def test_just_below_enterprise_is_mid_market():
    lead = _lead()
    lead.project.budget_high = E(ENTERPRISE_FLOOR - 1, 0.9)
    route(lead)
    assert lead.routing.segment == "mid_market"


def test_named_account_forces_enterprise_regardless_of_value():
    lead = _lead()
    lead.line_items = [_line_item("TRV-STK", 4)]  # tiny value
    lead.customer.existing_account_id = E("ACME-0042", 0.99)
    route(lead)
    assert lead.routing.segment == "enterprise"
    assert "signal_named_account" in lead.routing.rules_fired
    assert "segment_enterprise" in lead.routing.rules_fired


# --------------------------------------------------------------------------
# Territory
# --------------------------------------------------------------------------

def test_site_state_wins_over_billing_state():
    lead = _lead()
    lead.project.site_state = E("CA", 0.95)
    lead.customer.billing_state = E("NY", 0.95)
    route(lead)
    assert lead.routing.territory == "west"
    assert "territory_CA" in lead.routing.rules_fired


def test_billing_state_used_when_no_site_state():
    lead = _lead()
    lead.customer.billing_state = E("il", 0.95)  # lower-case tolerated
    route(lead)
    assert lead.routing.territory == "midwest"
    assert "territory_IL" in lead.routing.rules_fired


def test_unmapped_state_recorded_verbatim():
    lead = _lead()
    lead.project.site_state = E("ZZ", 0.5)
    route(lead)
    assert lead.routing.territory == "ZZ"
    assert "territory_unmapped_ZZ" in lead.routing.rules_fired
    assert lead.routing.assigned_rep  # falls back rather than crashing


def test_no_state_leaves_territory_none_and_rep_fallback():
    lead = _lead()
    lead.project.budget_high = E(60_000.0, 0.9)
    route(lead)
    assert lead.routing.territory is None
    assert lead.routing.assigned_rep == "Unassigned (queue)"
    assert not any(r.startswith("territory") for r in lead.routing.rules_fired)


def test_rep_assigned_by_region():
    lead = _lead()
    lead.project.site_state = E("MA", 0.95)
    route(lead)
    assert lead.routing.territory == "northeast"
    assert lead.routing.assigned_rep == _REP_BY_REGION["northeast"]
    assert "rep_assigned" in lead.routing.rules_fired


# --------------------------------------------------------------------------
# Priority score / urgency
# --------------------------------------------------------------------------

def test_priority_is_bounded():
    lead = _lead()
    lead.project.budget_high = E(50_000_000.0, 0.9)  # way over the cap
    lead.project.site_state = E("TX", 0.95)
    lead.project.quote_deadline = E(date(2026, 1, 15), 0.9)
    route(lead, now=datetime(2026, 1, 1))
    assert 0 <= lead.routing.priority_score <= 100


def test_higher_value_scores_higher():
    small = _lead()
    small.project.budget_high = E(60_000.0, 0.9)
    route(small)

    big = _lead()
    big.project.budget_high = E(600_000.0, 0.9)
    route(big)

    assert big.routing.priority_score > small.routing.priority_score


def test_near_deadline_raises_priority():
    base = _lead()
    base.project.budget_high = E(200_000.0, 0.9)
    route(base, now=datetime(2026, 1, 1))

    urgent = _lead()
    urgent.project.budget_high = E(200_000.0, 0.9)
    urgent.project.quote_deadline = E(date(2026, 1, 10), 0.9)  # 9 days out
    route(urgent, now=datetime(2026, 1, 1))

    assert urgent.routing.priority_score > base.routing.priority_score
    assert "urgency_hot" in urgent.routing.rules_fired


def test_urgency_tiers_hot_warm_presence():
    def score_for(deadline: date | None, now: datetime | None):
        lead = _lead()
        lead.project.budget_high = E(200_000.0, 0.9)
        if deadline is not None:
            lead.project.quote_deadline = E(deadline, 0.9)
        route(lead, now=now)
        return lead.routing

    now = datetime(2026, 1, 1)
    hot = score_for(date(2026, 1, 20), now)       # ~19 days
    warm = score_for(date(2026, 2, 20), now)      # ~50 days
    cool = score_for(date(2026, 6, 1), now)       # ~150 days
    presence = score_for(date(2026, 6, 1), None)  # no clock

    assert "urgency_hot" in hot.rules_fired
    assert "urgency_warm" in warm.rules_fired
    assert "urgency_has_deadline" in cool.rules_fired
    assert "urgency_has_deadline" in presence.rules_fired
    assert hot.priority_score > warm.priority_score > cool.priority_score


def test_past_deadline_treated_as_hot():
    lead = _lead()
    lead.project.budget_high = E(200_000.0, 0.9)
    lead.project.requested_delivery = E(date(2025, 12, 1), 0.9)  # already past
    route(lead, now=datetime(2026, 1, 1))
    assert "urgency_hot" in lead.routing.rules_fired


def test_requested_delivery_used_when_no_quote_deadline():
    lead = _lead()
    lead.project.budget_high = E(200_000.0, 0.9)
    lead.project.requested_delivery = E(date(2026, 1, 10), 0.9)
    route(lead, now=datetime(2026, 1, 1))
    assert "urgency_hot" in lead.routing.rules_fired


def test_earliest_of_two_dates_drives_urgency():
    lead = _lead()
    lead.project.budget_high = E(200_000.0, 0.9)
    lead.project.quote_deadline = E(date(2026, 5, 1), 0.9)       # far
    lead.project.requested_delivery = E(date(2026, 1, 10), 0.9)  # near
    route(lead, now=datetime(2026, 1, 1))
    assert "urgency_hot" in lead.routing.rules_fired


# --------------------------------------------------------------------------
# routed_at / determinism
# --------------------------------------------------------------------------

def test_routed_at_set_from_now():
    lead = _lead()
    stamp = datetime(2026, 8, 14, 12, 0, 0)
    route(lead, now=stamp)
    assert lead.routing.routed_at == stamp


def test_routed_at_none_when_now_omitted():
    lead = _lead()
    route(lead)
    assert lead.routing.routed_at is None


def test_routing_is_deterministic():
    def build():
        lead = _lead()
        lead.project.budget_high = E(750_000.0, 0.9)
        lead.project.site_state = E("TX", 0.95)
        lead.project.quote_deadline = E(date(2026, 2, 1), 0.9)
        return lead

    a = route(build(), now=datetime(2026, 1, 1))
    b = route(build(), now=datetime(2026, 1, 1))
    assert a.routing.model_dump() == b.routing.model_dump()


def test_returns_same_object():
    lead = _lead()
    assert route(lead) is lead


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
