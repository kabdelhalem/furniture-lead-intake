"""
Persistence layer.

The full ``CanonicalLead`` is the source of truth: it is stored verbatim as
``model_dump_json()`` in a single ``data`` column and rehydrated with
``model_validate_json()``. Everything else in the ``leads`` table is a
*denormalized projection* — a handful of columns pulled off the lead on write so
the API can drive the review queue and the dashboard without deserializing every
row to filter or sort. The projection is never authoritative; if it ever
disagreed with the JSON, the JSON wins.

Corrections live in their own ``corrections`` table (a queryable projection of
the review flywheel) *and* are appended to the lead's own
``review.corrections`` in the JSON, which stays the source of truth — the same
dual-write contract ``set_review_status`` follows for review status.
"""

from __future__ import annotations

import json

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from .schema import CanonicalLead, Correction, ReviewStatus

# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class LeadRow(SQLModel, table=True):
    """One row per lead. ``data`` is the whole lead; the rest is projection.

    The projected columns are read straight off the lead's ``Extracted``
    envelopes / routing / review / metrics on write (see ``_project``). They
    exist only so the queue and dashboard queries stay index-friendly — none of
    them is authoritative.
    """

    __tablename__ = "leads"

    lead_id: str = Field(primary_key=True)
    data: str  # CanonicalLead.model_dump_json() — the source of truth

    # Denormalized projection (for LeadSummary + queue/dashboard filtering).
    received_at: str = ""
    is_lead: bool = False
    company_name: str | None = None
    segment: str = "unclassified"
    priority_score: int = Field(default=0, index=True)
    review_status: str = Field(default=ReviewStatus.PENDING.value, index=True)
    auto_commit_rate: float = 0.0
    flagged_count: int = 0
    cost_usd: float = 0.0
    model_calls: int = 0


class CorrectionRow(SQLModel, table=True):
    """A reviewer correction, keyed to its lead. Mirrors ``schema.Correction``.

    This is the queryable projection of the flywheel; the authoritative copy is
    appended to the lead JSON's ``review.corrections``. The autoincrement ``id``
    preserves insertion order on read-back.
    """

    __tablename__ = "corrections"

    id: int | None = Field(default=None, primary_key=True)
    lead_id: str = Field(index=True, foreign_key="leads.lead_id")
    field_path: str = ""
    old_value: str | None = None   # JSON-encoded (Correction.old/new_value are Any)
    new_value: str | None = None
    old_confidence: str = "severe"  # Confidence level value
    reviewer: str = ""
    corrected_at: str | None = None
    reason_code: str | None = None


# --------------------------------------------------------------------------
# LeadSummary — the projection handed back to callers
# --------------------------------------------------------------------------


class LeadSummary(SQLModel):
    """Detached projection of a lead for queue/dashboard listing.

    Not a table — a plain model mirroring ``LeadRow``'s denormalized columns so
    callers hold a value object, never a session-bound ORM row.
    """

    lead_id: str
    received_at: str = ""
    is_lead: bool = False
    company_name: str | None = None
    segment: str = "unclassified"
    priority_score: int = 0
    review_status: str = ReviewStatus.PENDING.value
    auto_commit_rate: float = 0.0
    flagged_count: int = 0
    cost_usd: float = 0.0
    model_calls: int = 0


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


def _is_memory(url: str) -> bool:
    return url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url


def init_db(url: str = "sqlite:///leads.db") -> Engine:
    """Create an engine and the tables. Accepts ``"sqlite://"`` (in-memory).

    A bare in-memory URL gets a ``StaticPool`` so every connection shares the one
    database — otherwise each connection would open its own empty ``:memory:``
    and writes would vanish between calls.
    """
    if _is_memory(url):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------


def _project(lead: CanonicalLead) -> dict:
    """Pull the denormalized columns off a lead. Never authoritative."""
    return {
        "received_at": lead.received_at.isoformat(),
        "is_lead": bool(lead.is_lead.value),
        "company_name": lead.customer.company_name.value,
        "segment": lead.routing.segment,
        "priority_score": lead.routing.priority_score,
        "review_status": lead.review.status.value,
        "auto_commit_rate": lead.metrics.auto_commit_rate,
        "flagged_count": len(lead.review.flagged_paths),
        "cost_usd": lead.metrics.cost_usd,
        "model_calls": lead.metrics.model_calls,
    }


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------


def save_lead(engine: Engine, lead: CanonicalLead) -> None:
    """Upsert a lead by ``lead_id``, re-deriving the projection on every write."""
    with Session(engine) as session:
        row = session.get(LeadRow, lead.lead_id)
        payload = {"data": lead.model_dump_json(), **_project(lead)}
        if row is None:
            row = LeadRow(lead_id=lead.lead_id, **payload)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        session.add(row)
        session.commit()


def get_lead(engine: Engine, lead_id: str) -> CanonicalLead | None:
    """Rehydrate a lead from its authoritative JSON, or ``None`` if absent."""
    with Session(engine) as session:
        row = session.get(LeadRow, lead_id)
        if row is None:
            return None
        return CanonicalLead.model_validate_json(row.data)


def list_leads(
    engine: Engine,
    *,
    status: str | None = None,
    order_by_priority: bool = True,
) -> list[LeadSummary]:
    """List lead summaries for the queue/dashboard.

    ``status`` filters on the (projected) review status. Ordering is
    ``priority_score`` desc when ``order_by_priority`` is set, else the
    queue-natural ``received_at`` desc; both break ties on ``received_at`` desc
    then ``lead_id`` so results are deterministic.
    """
    with Session(engine) as session:
        stmt = select(LeadRow)
        if status is not None:
            stmt = stmt.where(LeadRow.review_status == status)
        if order_by_priority:
            stmt = stmt.order_by(
                LeadRow.priority_score.desc(),
                LeadRow.received_at.desc(),
                LeadRow.lead_id,
            )
        else:
            stmt = stmt.order_by(LeadRow.received_at.desc(), LeadRow.lead_id)
        rows = session.exec(stmt).all()
        return [LeadSummary.model_validate(row, from_attributes=True) for row in rows]


def record_correction(engine: Engine, lead_id: str, correction: Correction) -> None:
    """Append a correction to both the ``corrections`` table and the lead JSON.

    The table is the queryable projection; the lead's ``review.corrections`` is
    the source of truth. A correction for an unknown lead still lands in the
    table — only the JSON dual-write is skipped.
    """
    with Session(engine) as session:
        session.add(
            CorrectionRow(
                lead_id=lead_id,
                field_path=correction.field_path,
                old_value=_encode(correction.old_value),
                new_value=_encode(correction.new_value),
                old_confidence=getattr(correction.old_confidence, "value", correction.old_confidence),
                reviewer=correction.reviewer,
                corrected_at=(
                    correction.corrected_at.isoformat()
                    if correction.corrected_at is not None
                    else None
                ),
                reason_code=correction.reason_code,
            )
        )
        row = session.get(LeadRow, lead_id)
        if row is not None:
            lead = CanonicalLead.model_validate_json(row.data)
            lead.review.corrections.append(correction)
            row.data = lead.model_dump_json()
            session.add(row)
        session.commit()


def get_corrections(engine: Engine, lead_id: str) -> list[Correction]:
    """Read back a lead's corrections from the table, in insertion order."""
    with Session(engine) as session:
        stmt = (
            select(CorrectionRow)
            .where(CorrectionRow.lead_id == lead_id)
            .order_by(CorrectionRow.id)
        )
        rows = session.exec(stmt).all()
        return [
            Correction(
                field_path=r.field_path,
                old_value=_decode(r.old_value),
                new_value=_decode(r.new_value),
                old_confidence=r.old_confidence,
                reviewer=r.reviewer,
                corrected_at=r.corrected_at,
                reason_code=r.reason_code,
            )
            for r in rows
        ]


def set_review_status(engine: Engine, lead_id: str, status: ReviewStatus) -> None:
    """Update a lead's review status in both the column and the JSON.

    Accepts a ``ReviewStatus`` (or a bare string) and stores its ``.value`` in
    the projection while rewriting ``review.status`` in the authoritative JSON,
    keeping the two in lockstep.
    """
    value = getattr(status, "value", status)
    with Session(engine) as session:
        row = session.get(LeadRow, lead_id)
        if row is None:
            return
        lead = CanonicalLead.model_validate_json(row.data)
        lead.review.status = ReviewStatus(value)
        row.data = lead.model_dump_json()
        row.review_status = value
        session.add(row)
        session.commit()


# --------------------------------------------------------------------------
# Correction value (de)serialization
# --------------------------------------------------------------------------
# Correction.old_value / new_value are `Any`. We JSON-encode them for the
# projection columns so heterogeneous scalars survive a round-trip intact.


def _encode(value: object) -> str | None:
    return None if value is None else json.dumps(value)


def _decode(raw: str | None) -> object:
    return None if raw is None else json.loads(raw)
