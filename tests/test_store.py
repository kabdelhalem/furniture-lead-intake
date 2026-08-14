"""
Tests for the persistence layer.

Every fixture lead is built with ``CanonicalLead.model_validate`` on a nested
dict rather than by poking ``.value`` attributes — the same idiom as
``tests/test_eval.py``, so the fixture carries the same string->enum / str->date
coercions the real pipeline's output would. That matters here because the
central guarantee under test is a JSON round-trip: ``get_lead`` must reproduce
``model_dump()`` exactly, which only holds if every value survives
``model_dump_json`` -> ``model_validate_json``. The fixture therefore uses fixed
tz-naive datetimes and JSON-native scalars in the ``Any``-typed fields.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import SQLModel, create_engine

from src.schema import CanonicalLead, Correction, ReviewStatus
from src.store import (
    get_corrections,
    get_lead,
    init_db,
    list_leads,
    record_correction,
    save_lead,
    set_review_status,
)


def _engine():
    """An in-memory engine with the tables created.

    Uses ``create_engine("sqlite://")`` directly; its default per-thread
    singleton connection keeps the data alive across sessions within a
    single-threaded test run. ``init_db``'s own in-memory handling is exercised
    separately in ``test_init_db_accepts_in_memory_url``.
    """
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def make_lead(
    lead_id: str = "L001",
    *,
    priority: int = 50,
    status: str = "pending",
    segment: str = "mid_market",
    received: datetime | None = None,
) -> CanonicalLead:
    received = received or datetime(2026, 3, 14, 9, 30)
    return CanonicalLead.model_validate(
        {
            "lead_id": lead_id,
            "received_at": received,
            "channel": {"value": "email", "confidence": 0.99, "status": "auto_committed"},
            "is_lead": {"value": True, "confidence": 0.97, "status": "auto_committed"},
            "customer": {
                "company_name": {
                    "value": "Aalto Contract Interiors",
                    "confidence": 0.93,
                    "status": "auto_committed",
                    "evidence": [{"artifact_id": "A1", "locator": "line 1", "snippet": "Aalto Contract Interiors"}],
                },
                "primary_contact": {
                    "email": {"value": "buyer@aalto.example", "confidence": 0.96, "status": "auto_committed"},
                },
            },
            "line_items": [
                {
                    "raw_description": "6x walnut task chair",
                    "matched_sku": {"value": "ASH-TSK-01", "confidence": 0.91, "status": "auto_committed"},
                    "quantity": {"value": 6, "confidence": 0.94, "status": "auto_committed"},
                }
            ],
            "routing": {
                "assigned_rep": "rep-7",
                "segment": segment,
                "priority_score": priority,
                "rules_fired": ["segment_" + segment],
                "routed_at": datetime(2026, 3, 14, 9, 31),
            },
            "review": {
                "status": status,
                "flagged_paths": ["line_items[0].finish", "project.budget_low"],
                "reviewer": "reviewer-1",
            },
            "metrics": {
                "extraction_ms": 1200,
                "total_tokens": 3400,
                "cost_usd": 0.021,
                "model_calls": 3,
                "fields_total": 20,
                "fields_auto_committed": 16,
            },
        }
    )


# --------------------------------------------------------------------------
# Round-trip
# --------------------------------------------------------------------------


def test_roundtrip_reproduces_model_dump():
    engine = _engine()
    lead = make_lead()
    save_lead(engine, lead)

    got = get_lead(engine, "L001")
    assert got is not None
    assert got.model_dump() == lead.model_dump()


def test_get_missing_lead_returns_none():
    engine = _engine()
    assert get_lead(engine, "nope") is None


def test_save_is_an_upsert():
    engine = _engine()
    save_lead(engine, make_lead(priority=10))
    save_lead(engine, make_lead(priority=88))  # same lead_id, new projection

    summaries = list_leads(engine)
    assert len(summaries) == 1
    assert summaries[0].priority_score == 88


def test_init_db_accepts_in_memory_url():
    # A bare in-memory URL must share one database across connections.
    engine = init_db("sqlite://")
    save_lead(engine, make_lead())
    assert get_lead(engine, "L001") is not None


# --------------------------------------------------------------------------
# Listing: ordering + filtering
# --------------------------------------------------------------------------


def test_list_orders_by_priority_desc():
    engine = _engine()
    save_lead(engine, make_lead("LOW", priority=20))
    save_lead(engine, make_lead("HIGH", priority=90))
    save_lead(engine, make_lead("MID", priority=55))

    ids = [s.lead_id for s in list_leads(engine)]
    assert ids == ["HIGH", "MID", "LOW"]


def test_list_filters_by_status():
    engine = _engine()
    save_lead(engine, make_lead("P1", status="pending"))
    save_lead(engine, make_lead("A1", status="approved"))
    save_lead(engine, make_lead("P2", status="pending"))

    pending = {s.lead_id for s in list_leads(engine, status="pending")}
    assert pending == {"P1", "P2"}
    approved = [s.lead_id for s in list_leads(engine, status="approved")]
    assert approved == ["A1"]


def test_summary_mirrors_denormalized_columns():
    engine = _engine()
    save_lead(engine, make_lead("L001", priority=77, segment="enterprise"))
    s = list_leads(engine)[0]
    assert s.company_name == "Aalto Contract Interiors"
    assert s.segment == "enterprise"
    assert s.priority_score == 77
    assert s.is_lead is True
    assert s.flagged_count == 2  # len(review.flagged_paths)
    assert s.model_calls == 3
    assert s.cost_usd == 0.021
    # auto_commit_rate is a @property on metrics: 16/20 = 0.8
    assert s.auto_commit_rate == 0.8


# --------------------------------------------------------------------------
# Corrections
# --------------------------------------------------------------------------


def test_record_and_read_back_corrections():
    engine = _engine()
    save_lead(engine, make_lead())

    c1 = Correction(
        field_path="line_items[0].matched_sku",
        old_value="ASH-TSK-01",
        new_value="ASH-TSK-02",
        old_confidence=0.91,
        reviewer="reviewer-1",
        corrected_at=datetime(2026, 3, 15, 10, 0),
        reason_code="wrong_sku",
    )
    c2 = Correction(
        field_path="line_items[0].quantity",
        old_value=6,
        new_value=8,
        old_confidence=0.94,
        reviewer="reviewer-1",
        corrected_at=datetime(2026, 3, 15, 10, 5),
        reason_code="unit_error",
    )
    record_correction(engine, "L001", c1)
    record_correction(engine, "L001", c2)

    got = get_corrections(engine, "L001")
    assert [c.field_path for c in got] == [
        "line_items[0].matched_sku",
        "line_items[0].quantity",
    ]
    # Heterogeneous Any-typed values survive the JSON projection round-trip.
    assert got[0].new_value == "ASH-TSK-02"
    assert got[1].old_value == 6 and got[1].new_value == 8
    assert got[0].reason_code == "wrong_sku"

    # And the JSON stays the source of truth: corrections also land there.
    lead = get_lead(engine, "L001")
    assert [c.field_path for c in lead.review.corrections] == [
        "line_items[0].matched_sku",
        "line_items[0].quantity",
    ]


# --------------------------------------------------------------------------
# Review status
# --------------------------------------------------------------------------


def test_set_review_status_updates_column_and_json():
    engine = _engine()
    save_lead(engine, make_lead(status="pending"))

    set_review_status(engine, "L001", ReviewStatus.APPROVED)

    # Column (projection) reflects the change...
    assert list_leads(engine)[0].review_status == "approved"
    # ...and so does the authoritative JSON.
    assert get_lead(engine, "L001").review.status is ReviewStatus.APPROVED
