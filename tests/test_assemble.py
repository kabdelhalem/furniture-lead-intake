"""
Tests for the deterministic assembler.

We feed `assemble` a hand-built ExtractionResult standing in for a *perfect
model read* and check two things: the typed CanonicalLead matches ground truth
(so a perfect read scores 100% through the eval harness), and the confidence
layer flags exactly the fields the corpus says should be uncertain — a clean
lead auto-commits, while the ambiguity/hedge/conflict/null cases land in review.
"""

from __future__ import annotations

from datetime import datetime

from src.assemble import assemble
from src.eval import score_lead
from src.extract_types import EContact, EDimensions, EField, ELineItem, ExtractionResult
from src.ingest import IngestedArtifact
from src.schema import flatten_values

RECEIVED = datetime(2026, 8, 14, 9, 0, 0)


def _artifact(kind="email", aid="A::x"):
    return IngestedArtifact(artifact_id=aid, kind=kind, filename="x", sha256="0", bytes=1)


def _assemble(extraction, kind="email", lead_id="LTEST"):
    return assemble(extraction, [_artifact(kind)], lead_id=lead_id, received_at=RECEIVED)


# --------------------------------------------------------------------------
# L001 — a clean lead should type correctly and auto-commit
# --------------------------------------------------------------------------

def _l001_extraction() -> ExtractionResult:
    return ExtractionResult(
        is_lead=EField(value="true", certainty=0.98),
        channel=EField(value="email", certainty=0.99),
        company_name=EField(value="Northgate Labs", certainty=0.95, locator="body line 4"),
        customer_type=EField(value="end_customer", certainty=0.85),
        primary_contact=EContact(
            full_name=EField(value="Dana Whitfield", certainty=0.95),
            email=EField(value="dwhitfield@northgatelabs.com", certainty=0.92),
            phone=EField(value="617-555-0182", certainty=0.92),
            title=EField(value="Facilities Manager", certainty=0.85),
        ),
        site_city=EField(value="Cambridge", certainty=0.9),
        site_state=EField(value="MA", certainty=0.9),
        requested_delivery=EField(value="October 15", certainty=0.85,
                                  snippet="need them by October 15"),
        line_items=[ELineItem(
            raw_description="Ashfield task chairs, high-back, graphite",
            quantity=EField(value="8", certainty=0.95, snippet="8 of the Ashfield task chairs"),
            finish=EField(value="graphite", certainty=0.9),
        )],
    )


def test_l001_types_and_matches_truth():
    lead = _assemble(_l001_extraction(), lead_id="L001")
    v = flatten_values(lead)
    assert v["is_lead"] is True
    assert v["channel"] == "email"
    assert v["customer.company_name"] == "Northgate Labs"
    assert v["customer.customer_type"] == "end_customer"
    assert v["customer.primary_contact.email"] == "dwhitfield@northgatelabs.com"
    assert v["customer.primary_contact.phone"] == "617-555-0182"
    assert str(v["project.requested_delivery"]) == "2026-10-15"
    assert v["line_items[0].matched_sku"] == "ASH-TSK-30H"
    assert v["line_items[0].quantity"] == 8
    assert v["line_items[0].finish"] == "graphite"


def test_l001_scores_100_through_eval():
    lead = _assemble(_l001_extraction(), lead_id="L001")
    truth = {"fields": {
        "is_lead": True, "channel": "email",
        "customer.company_name": "Northgate Labs",
        "customer.customer_type": "end_customer",
        "customer.primary_contact.full_name": "Dana Whitfield",
        "customer.primary_contact.email": "dwhitfield@northgatelabs.com",
        "customer.primary_contact.phone": "617-555-0182",
        "customer.primary_contact.title": "Facilities Manager",
        "project.site_city": "Cambridge", "project.site_state": "MA",
        "project.requested_delivery": "2026-10-15",
        "line_items[0].matched_sku": "ASH-TSK-30H",
        "line_items[0].quantity": 8, "line_items[0].finish": "graphite",
    }}
    score = score_lead(lead, truth)
    assert score.field_accuracy == 1.0, [r for r in score.field_results if not r.ok]


def test_l001_clean_fields_auto_commit():
    lead = _assemble(_l001_extraction(), lead_id="L001")
    flagged = set(lead.review.flagged_paths)
    for path in ("customer.primary_contact.email", "customer.primary_contact.phone",
                 "line_items[0].quantity", "line_items[0].matched_sku"):
        assert path not in flagged, f"{path} should have auto-committed"


# --------------------------------------------------------------------------
# L007 — ambiguous SKU declines to a value with alternatives
# --------------------------------------------------------------------------

def test_l007_ambiguous_sku_declines_with_alternatives():
    extraction = ExtractionResult(
        is_lead=EField(value="true", certainty=0.9),
        line_items=[ELineItem(
            raw_description="the big walnut conference table",
            quantity=EField(value="3", certainty=0.9),
        )],
    )
    lead = _assemble(extraction, lead_id="L007")
    sku = lead.line_items[0].matched_sku
    assert sku.value is None                                   # declined, not guessed
    assert any(a.startswith("MER-CT-") for a in sku.alternatives)
    assert "line_items[0].matched_sku" in lead.review.flagged_paths
    # ...but the quantity, which the source does state, is fine.
    assert flatten_values(lead)["line_items[0].quantity"] == 3


# --------------------------------------------------------------------------
# L008 — off-nominal metric names the SKU but stays below the bar
# --------------------------------------------------------------------------

def test_l008_off_nominal_sku_named_but_flagged():
    extraction = ExtractionResult(
        is_lead=EField(value="true", certainty=0.9),
        line_items=[ELineItem(
            raw_description="Height-adjustable desk, laminate, white",
            quantity=EField(value="32", certainty=0.95),
            dimensions=EDimensions(width=EField(value="1800mm", certainty=0.9)),
        )],
    )
    lead = _assemble(extraction, lead_id="L008")
    li = lead.line_items[0]
    assert li.matched_sku.value == "KRN-DSK-72"                # named, not declined
    assert abs(li.dimensions.width_in.value - 70.87) < 0.01    # exact metric conversion
    assert "line_items[0].matched_sku" in lead.review.flagged_paths  # off-nominal -> review


# --------------------------------------------------------------------------
# L011 — a quantity stated nowhere is None and flagged
# --------------------------------------------------------------------------

def test_l011_missing_quantity_is_null_and_flagged():
    extraction = ExtractionResult(
        is_lead=EField(value="true", certainty=0.9),
        line_items=[ELineItem(
            raw_description="Verano meeting pod, 4 person, slate",
            finish=EField(value="slate", certainty=0.9),
            # quantity intentionally left empty — the source never states it
        )],
    )
    lead = _assemble(extraction, lead_id="L011")
    assert flatten_values(lead)["line_items[0].quantity"] is None
    assert "line_items[0].quantity" in lead.review.flagged_paths


# --------------------------------------------------------------------------
# L006 — a hedged quantity is flagged even though a number was read
# --------------------------------------------------------------------------

def test_l006_hedged_quantity_is_flagged():
    extraction = ExtractionResult(
        is_lead=EField(value="true", certainty=0.9),
        line_items=[ELineItem(
            raw_description="Meridian conference table, espresso",
            quantity=EField(value="4", certainty=0.7, snippet="four, maybe five"),
        )],
    )
    lead = _assemble(extraction, lead_id="L006")
    assert flatten_values(lead)["line_items[0].quantity"] == 4   # best read is 4
    assert "line_items[0].quantity" in lead.review.flagged_paths  # ...but hedged -> review


# --------------------------------------------------------------------------
# L014 — a cross-artifact finish conflict is flagged
# --------------------------------------------------------------------------

def test_l014_conflicting_finish_is_flagged():
    extraction = ExtractionResult(
        is_lead=EField(value="true", certainty=0.9),
        line_items=[ELineItem(
            raw_description="Verano acoustic panel 48 inch",
            quantity=EField(value="34", certainty=0.95),
            finish=EField(value="oat", certainty=0.95, conflict=True),
        )],
    )
    lead = _assemble(extraction, lead_id="L014")
    assert "line_items[0].finish" in lead.review.flagged_paths


# --------------------------------------------------------------------------
# Not-a-lead gate + evidence
# --------------------------------------------------------------------------

def test_not_a_lead_gate():
    extraction = ExtractionResult(is_lead=EField(value="false", certainty=0.95))
    lead = _assemble(extraction, lead_id="L013")
    assert flatten_values(lead)["is_lead"] is False


def test_every_present_value_carries_evidence():
    lead = _assemble(_l001_extraction(), lead_id="L001")
    # The company name was located; its envelope must carry an evidence locator.
    assert lead.customer.company_name.evidence
    assert lead.customer.company_name.evidence[0].locator == "body line 4"
