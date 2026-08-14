"""
Deterministic lead routing.

This is intentionally NOT a model. Segmentation, territory, priority, and rep
assignment are a lookup-table decision: cheap, auditable, and trivially
explainable to a sales ops lead. Spending model tokens on this class of decision
would erode trust in the cost profile of the parts of the system that genuinely
need a model (extraction and ambiguity resolution).

Every rule that fires appends a stable id to ``routing.rules_fired`` so the
decision is fully reconstructable from the record alone — the same audit
affordance the extraction layer gets from per-field ``evidence``.

The only non-determinism a caller might want is "now" (for urgency scoring and
the ``routed_at`` stamp). We never read the clock here; ``now`` is an explicit
optional parameter so tests stay reproducible and imports stay side-effect free.
"""

from __future__ import annotations

from datetime import date, datetime

from .catalog import by_sku
from .schema import CanonicalLead

# --------------------------------------------------------------------------
# Tunables — plain constants, not config. Documented so the thresholds are
# reviewable rather than magic.
# --------------------------------------------------------------------------

ENTERPRISE_FLOOR = 500_000.0   # est. deal value at/above which a lead is enterprise
MID_MARKET_FLOOR = 50_000.0    # ...and above which it is at least mid-market

# US-region rollup, keyed by two-letter state code. Coarse on purpose: routing
# only needs enough geography to pick a rep pod, not a full ZIP-level territory.
_REGION_BY_STATE: dict[str, str] = {
    # Northeast
    "CT": "northeast", "ME": "northeast", "MA": "northeast", "NH": "northeast",
    "NJ": "northeast", "NY": "northeast", "PA": "northeast", "RI": "northeast",
    "VT": "northeast",
    # Midwest
    "IL": "midwest", "IN": "midwest", "IA": "midwest", "KS": "midwest",
    "MI": "midwest", "MN": "midwest", "MO": "midwest", "NE": "midwest",
    "ND": "midwest", "OH": "midwest", "SD": "midwest", "WI": "midwest",
    # South
    "AL": "south", "AR": "south", "DE": "south", "DC": "south", "FL": "south",
    "GA": "south", "KY": "south", "LA": "south", "MD": "south", "MS": "south",
    "NC": "south", "OK": "south", "SC": "south", "TN": "south", "TX": "south",
    "VA": "south", "WV": "south",
    # West
    "AK": "west", "AZ": "west", "CA": "west", "CO": "west", "HI": "west",
    "ID": "west", "MT": "west", "NV": "west", "NM": "west", "OR": "west",
    "UT": "west", "WA": "west", "WY": "west",
}

# One rep pod per region, plus a fallback when geography is unknown. A hardcoded
# stub — a real system would hit a rep-capacity service here.
_REP_BY_REGION: dict[str, str] = {
    "northeast": "Priya Menon",
    "midwest": "Marcus Hale",
    "south": "Dana Reed",
    "west": "Alex Okafor",
}
_REP_UNASSIGNED = "Unassigned (queue)"

# Urgency windows (days from ``now`` to the earliest hard date on the lead).
_URGENCY_HOT_DAYS = 30
_URGENCY_WARM_DAYS = 60


# --------------------------------------------------------------------------
# Value estimation
# --------------------------------------------------------------------------

def _extracted_value(field):
    """Return ``field.value`` for an Extracted envelope, else None."""
    return getattr(field, "value", None)


def _estimate_value(lead: CanonicalLead) -> tuple[float | None, str | None]:
    """Estimate deal value and return (value, rule_id).

    Prefer a stated budget — it is the customer's own number and beats any
    catalog inference. Budget-high is the ceiling a rep quotes toward, so we
    take the high end when present, else the low end. Falling back, sum
    ``quantity * catalog list price`` over line items whose SKU we matched;
    line items with no SKU or no quantity contribute nothing (we never invent a
    number to fill the gap).

    Returns (None, None) when neither path yields anything.
    """
    budget_high = _extracted_value(lead.project.budget_high)
    budget_low = _extracted_value(lead.project.budget_low)
    if budget_high is not None:
        return float(budget_high), "value_from_budget"
    if budget_low is not None:
        return float(budget_low), "value_from_budget"

    total = 0.0
    matched_any = False
    for item in lead.line_items:
        sku = _extracted_value(item.matched_sku)
        qty = _extracted_value(item.quantity)
        if not sku or qty is None:
            continue
        entry = by_sku(sku)
        if entry is None:
            continue
        total += float(entry["list_price"]) * int(qty)
        matched_any = True

    if not matched_any:
        return None, None
    return total, "value_from_line_items"


# --------------------------------------------------------------------------
# Enterprise "named account / multi-site" signal
# --------------------------------------------------------------------------

def _named_account_signal(lead: CanonicalLead) -> bool:
    """True if the lead carries a structured named-account / multi-site signal.

    The one structured signal the schema gives us is an existing account id:
    a lead tied to an already-provisioned account is, by definition, a named
    account and gets enterprise handling regardless of this order's size.
    (There is no dedicated multi-site field in the schema; if one is added
    later, OR it in here.)
    """
    return bool(_extracted_value(lead.customer.existing_account_id))


# --------------------------------------------------------------------------
# Territory
# --------------------------------------------------------------------------

def _state_code(lead: CanonicalLead) -> str | None:
    """Two-letter state: project site wins over billing (route to the install)."""
    for field in (lead.project.site_state, lead.customer.billing_state):
        raw = _extracted_value(field)
        if raw:
            return str(raw).strip().upper()
    return None


# --------------------------------------------------------------------------
# Urgency (priority component)
# --------------------------------------------------------------------------

def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _earliest_hard_date(lead: CanonicalLead) -> date | None:
    """Soonest of quote_deadline / requested_delivery, whichever exist."""
    candidates = [
        _as_date(_extracted_value(lead.project.quote_deadline)),
        _as_date(_extracted_value(lead.project.requested_delivery)),
    ]
    dates = [d for d in candidates if d is not None]
    return min(dates) if dates else None


def _urgency_points(lead: CanonicalLead, now: datetime | None) -> tuple[int, str | None]:
    """0-20 urgency points plus a rule id, from how near the earliest date is.

    Presence of any hard date is itself mild urgency (+8) even without a clock.
    With ``now``, a nearer date scores higher; a date already in the past is
    treated as maximally urgent, not negative.
    """
    hard = _earliest_hard_date(lead)
    if hard is None:
        return 0, None
    if now is None:
        return 8, "urgency_has_deadline"

    days = (hard - now.date()).days
    if days <= _URGENCY_HOT_DAYS:
        return 20, "urgency_hot"
    if days <= _URGENCY_WARM_DAYS:
        return 12, "urgency_warm"
    return 8, "urgency_has_deadline"


# --------------------------------------------------------------------------
# Priority score
# --------------------------------------------------------------------------

_SEGMENT_POINTS = {"enterprise": 35, "mid_market": 20, "smb": 5}


def _priority_score(
    est_value: float | None, segment: str, urgency_pts: int
) -> int:
    """0-100. Blend of deal value, segment tier, and urgency.

    Value dominates (0-45, saturating at the enterprise floor so a $6.5M and a
    $500K lead both max the value term), segment adds a tier bump (0-35), and
    urgency tops it off (0-20). Clamped to [0, 100].
    """
    value = est_value or 0.0
    value_pts = min(45.0, (value / ENTERPRISE_FLOOR) * 45.0)
    seg_pts = _SEGMENT_POINTS.get(segment, 0)
    score = round(value_pts + seg_pts + urgency_pts)
    return max(0, min(100, score))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def route(lead: CanonicalLead, now: datetime | None = None) -> CanonicalLead:
    """Populate ``lead.routing`` deterministically and return the lead.

    Pure over (lead, now): no clock reads, no I/O, no model calls. Every rule
    that fires is recorded in ``routing.rules_fired`` in the order it ran, so
    the routing decision is fully reconstructable from the record.

    If the lead did not clear the is-a-lead gate, this is a no-op: routing stays
    at its ``unclassified`` / empty defaults. Routing a non-lead would put junk
    in the sales queue, which is exactly what the classifier gate exists to
    prevent.

    ``now``, when supplied, is used both to score urgency (how near the earliest
    hard date is) and as ``routed_at``. Left as None, urgency degrades to a
    presence-only signal and ``routed_at`` stays None.
    """
    routing = lead.routing

    # Gate: only real leads get routed. Anything else stays unclassified.
    if _extracted_value(lead.is_lead) is not True:
        return lead

    rules: list[str] = []

    # 1. Estimate deal value.
    est_value, value_rule = _estimate_value(lead)
    if value_rule:
        rules.append(value_rule)

    # 2. Segment.
    named_account = _named_account_signal(lead)
    if named_account:
        rules.append("signal_named_account")

    if (est_value is not None and est_value >= ENTERPRISE_FLOOR) or named_account:
        segment = "enterprise"
    elif est_value is not None and est_value >= MID_MARKET_FLOOR:
        segment = "mid_market"
    else:
        # Below mid-market, or no value signal at all: smb is the safe default
        # tier for a real lead (it still routes to a rep, just low priority).
        segment = "smb"
    routing.segment = segment
    rules.append(f"segment_{segment}")

    # 3. Territory.
    state = _state_code(lead)
    if state:
        region = _REGION_BY_STATE.get(state)
        if region:
            routing.territory = region
            rules.append(f"territory_{state}")
        else:
            # A state-shaped value we don't recognize: record it verbatim so a
            # reviewer sees what we couldn't map, rather than silently dropping.
            routing.territory = state
            rules.append(f"territory_unmapped_{state}")

    # 4. Priority score (value + segment + urgency).
    urgency_pts, urgency_rule = _urgency_points(lead, now)
    if urgency_rule:
        rules.append(urgency_rule)
    routing.priority_score = _priority_score(est_value, segment, urgency_pts)

    # 5. Assigned rep (by territory; fallback when geography is unknown).
    rep = _REP_BY_REGION.get(routing.territory, _REP_UNASSIGNED)
    routing.assigned_rep = rep
    rules.append("rep_assigned")

    routing.rules_fired = rules
    routing.routed_at = now
    return lead
