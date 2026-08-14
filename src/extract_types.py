"""
The contract between the model and the deterministic layer.

The extractor's job is deliberately narrow: *read and locate*. For every field
the model returns a raw string exactly as the source states it, where it found
it (`locator` + `snippet`), and how sure it is (`certainty`). It does not type,
normalize, convert units, or match SKUs — that is the deterministic layer's job
(`assemble.py`), because those steps carry their own, better-calibrated
confidence signals than the model's self-report.

Keeping this boundary sharp is what lets the same extraction feed the eval
harness and the UI without the model re-deciding anything downstream.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EField(BaseModel):
    """One read value: the raw source string, its provenance, and the model's
    self-reported certainty. `value` is None when the source doesn't state it —
    the model must never invent one (the L011 stance)."""
    value: str | None = None
    certainty: float = Field(0.5, ge=0.0, le=1.0)
    locator: str | None = None       # "body line 7", "Takeoff!C14", "page 2"
    snippet: str | None = None       # verbatim source span, <=200 chars
    conflict: bool = False           # two artifacts disagree on this field (L014)


class EDimensions(BaseModel):
    width: EField = Field(default_factory=EField)
    depth: EField = Field(default_factory=EField)
    height: EField = Field(default_factory=EField)


class ELineItem(BaseModel):
    raw_description: str = ""         # verbatim — the audit anchor, never normalized
    quantity: EField = Field(default_factory=EField)
    material: EField = Field(default_factory=EField)
    finish: EField = Field(default_factory=EField)
    com_fabric: EField = Field(default_factory=EField)
    dimensions: EDimensions = Field(default_factory=EDimensions)
    target_unit_price: EField = Field(default_factory=EField)


class EContact(BaseModel):
    full_name: EField = Field(default_factory=EField)
    email: EField = Field(default_factory=EField)
    phone: EField = Field(default_factory=EField)
    title: EField = Field(default_factory=EField)
    is_decision_maker: EField = Field(default_factory=EField)


class ExtractionResult(BaseModel):
    """Everything the model read out of a lead's artifacts, pre-typing."""
    is_lead: EField = Field(default_factory=EField)
    channel: EField = Field(default_factory=EField)

    company_name: EField = Field(default_factory=EField)
    customer_type: EField = Field(default_factory=EField)
    primary_contact: EContact = Field(default_factory=EContact)
    billing_city: EField = Field(default_factory=EField)
    billing_state: EField = Field(default_factory=EField)
    existing_account_id: EField = Field(default_factory=EField)

    project_name: EField = Field(default_factory=EField)
    site_city: EField = Field(default_factory=EField)
    site_state: EField = Field(default_factory=EField)
    requested_delivery: EField = Field(default_factory=EField)
    quote_deadline: EField = Field(default_factory=EField)
    budget: EField = Field(default_factory=EField)          # raw span; normalize splits low/high
    install_required: EField = Field(default_factory=EField)

    line_items: list[ELineItem] = Field(default_factory=list)
