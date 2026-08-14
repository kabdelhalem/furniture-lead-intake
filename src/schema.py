"""
Canonical lead schema.

The thesis of this project: heterogeneous inbound (email / PDF / scanned fax /
Excel / DXF / call transcript) collapses into ONE shape, and every field in that
shape carries its own confidence and provenance.

That per-field confidence is what makes the human-in-the-loop step cheap: a
reviewer touches the 10-15% of fields the system is unsure about, not the whole
record.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class Channel(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    WEB_FORM = "web_form"
    FAX = "fax"


class ArtifactKind(str, Enum):
    EMAIL_BODY = "email_body"
    PDF_TEXT = "pdf_text"
    PDF_SCANNED = "pdf_scanned"
    SPREADSHEET = "spreadsheet"
    CAD_DXF = "cad_dxf"
    CALL_TRANSCRIPT = "call_transcript"
    IMAGE = "image"


class CustomerType(str, Enum):
    DEALER = "dealer"
    DESIGNER = "designer"          # A&D firm specifying on behalf of an end client
    CONTRACTOR = "contractor"
    END_CUSTOMER = "end_customer"
    UNKNOWN = "unknown"


class FieldStatus(str, Enum):
    AUTO_COMMITTED = "auto_committed"    # cleared threshold, no human touched it
    NEEDS_REVIEW = "needs_review"        # below threshold, queued
    HUMAN_CORRECTED = "human_corrected"  # human changed the value
    HUMAN_CONFIRMED = "human_confirmed"  # human looked, agreed
    NOT_FOUND = "not_found"              # genuinely absent in source


class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"       # not a real lead
    DUPLICATE = "duplicate"


class UnitSystem(str, Enum):
    IMPERIAL = "imperial"
    METRIC = "metric"


# --------------------------------------------------------------------------
# The confidence envelope
# --------------------------------------------------------------------------

class Evidence(BaseModel):
    """Where this value came from. Drives the 'show me why' UI affordance."""
    artifact_id: str
    locator: str | None = None      # "page 2", "Sheet1!C14", "line 37", "$DIMSTYLE"
    snippet: str | None = None      # verbatim source text, <=200 chars


class Extracted(BaseModel, Generic[T]):
    """Every extracted value is wrapped. No bare values in the canonical record."""
    value: T | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    status: FieldStatus = FieldStatus.NEEDS_REVIEW
    extractor: str | None = None    # "claude-haiku:email_v2", "regex:phone", "fuzzy:sku"
    evidence: list[Evidence] = Field(default_factory=list)
    alternatives: list[Any] = Field(default_factory=list)  # runner-up candidates
    note: str | None = None         # why the model hesitated — shown to reviewer

    @property
    def needs_review(self) -> bool:
        return self.status == FieldStatus.NEEDS_REVIEW


def E(value: T | None = None, confidence: float = 0.0, **kw: Any) -> Extracted[T]:
    """Terse constructor for extractor code."""
    return Extracted(value=value, confidence=confidence, **kw)


# --------------------------------------------------------------------------
# Sub-records
# --------------------------------------------------------------------------

class Contact(BaseModel):
    full_name: Extracted[str] = Field(default_factory=Extracted)
    email: Extracted[str] = Field(default_factory=Extracted)
    phone: Extracted[str] = Field(default_factory=Extracted)
    title: Extracted[str] = Field(default_factory=Extracted)
    is_decision_maker: Extracted[bool] = Field(default_factory=Extracted)


class Customer(BaseModel):
    company_name: Extracted[str] = Field(default_factory=Extracted)
    customer_type: Extracted[CustomerType] = Field(default_factory=Extracted)
    primary_contact: Contact = Field(default_factory=Contact)
    additional_contacts: list[Contact] = Field(default_factory=list)
    billing_city: Extracted[str] = Field(default_factory=Extracted)
    billing_state: Extracted[str] = Field(default_factory=Extracted)
    existing_account_id: Extracted[str] = Field(default_factory=Extracted)


class Dimensions(BaseModel):
    """Normalized to inches internally; original units preserved for the reviewer."""
    width_in: Extracted[float] = Field(default_factory=Extracted)
    depth_in: Extracted[float] = Field(default_factory=Extracted)
    height_in: Extracted[float] = Field(default_factory=Extracted)
    source_units: Extracted[UnitSystem] = Field(default_factory=Extracted)


class LineItem(BaseModel):
    raw_description: str = ""                 # verbatim, never normalized — the audit anchor
    matched_sku: Extracted[str] = Field(default_factory=Extracted)
    product_category: Extracted[str] = Field(default_factory=Extracted)
    quantity: Extracted[int] = Field(default_factory=Extracted)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    material: Extracted[str] = Field(default_factory=Extracted)
    finish: Extracted[str] = Field(default_factory=Extracted)
    com_fabric: Extracted[str] = Field(default_factory=Extracted)  # customer's own material
    options: Extracted[list[str]] = Field(default_factory=Extracted)
    target_unit_price: Extracted[float] = Field(default_factory=Extracted)


class ProjectContext(BaseModel):
    project_name: Extracted[str] = Field(default_factory=Extracted)
    site_city: Extracted[str] = Field(default_factory=Extracted)
    site_state: Extracted[str] = Field(default_factory=Extracted)
    requested_delivery: Extracted[date] = Field(default_factory=Extracted)
    budget_low: Extracted[float] = Field(default_factory=Extracted)
    budget_high: Extracted[float] = Field(default_factory=Extracted)
    install_required: Extracted[bool] = Field(default_factory=Extracted)
    quote_deadline: Extracted[date] = Field(default_factory=Extracted)


class Routing(BaseModel):
    """Deterministic. No model runs here — rules only, and they log which fired."""
    assigned_rep: str | None = None
    territory: str | None = None
    segment: Literal["smb", "mid_market", "enterprise", "unclassified"] = "unclassified"
    priority_score: int = 0        # 0-100
    rules_fired: list[str] = Field(default_factory=list)
    routed_at: datetime | None = None


class Correction(BaseModel):
    """The flywheel. Every correction is a future eval case + few-shot example."""
    field_path: str
    old_value: Any = None
    new_value: Any = None
    old_confidence: float = 0.0
    reviewer: str = ""
    corrected_at: datetime | None = None
    reason_code: str | None = None   # "wrong_sku", "hallucinated", "missed", "unit_error"


class ReviewState(BaseModel):
    status: ReviewStatus = ReviewStatus.PENDING
    flagged_paths: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    review_seconds: float | None = None
    corrections: list[Correction] = Field(default_factory=list)
    duplicate_of: str | None = None


class PipelineMetrics(BaseModel):
    extraction_ms: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_calls: int = 0
    fields_total: int = 0
    fields_auto_committed: int = 0

    @property
    def auto_commit_rate(self) -> float:
        return self.fields_auto_committed / self.fields_total if self.fields_total else 0.0


class SourceArtifact(BaseModel):
    artifact_id: str
    kind: ArtifactKind
    filename: str
    sha256: str | None = None
    bytes: int = 0
    page_count: int | None = None
    ocr_applied: bool = False


class CanonicalLead(BaseModel):
    lead_id: str
    received_at: datetime
    channel: Extracted[Channel] = Field(default_factory=Extracted)
    is_lead: Extracted[bool] = Field(default_factory=Extracted)  # negative-case gate
    source_artifacts: list[SourceArtifact] = Field(default_factory=list)

    customer: Customer = Field(default_factory=Customer)
    project: ProjectContext = Field(default_factory=ProjectContext)
    line_items: list[LineItem] = Field(default_factory=list)

    routing: Routing = Field(default_factory=Routing)
    review: ReviewState = Field(default_factory=ReviewState)
    metrics: PipelineMetrics = Field(default_factory=PipelineMetrics)


# --------------------------------------------------------------------------
# Confidence policy
# --------------------------------------------------------------------------
# Thresholds are per field CLASS, not global. Getting a customer's email wrong
# is unrecoverable (the quote goes to the wrong inbox); getting a finish wrong
# is caught downstream by the rep. So identity fields sit high and descriptive
# fields sit low. Tune these from the calibration report, not by vibes.

THRESHOLDS: dict[str, float] = {
    "_default":                         0.80,
    "is_lead":                          0.90,
    "customer.company_name":            0.85,
    "customer.primary_contact.email":   0.95,
    "customer.primary_contact.phone":   0.95,
    "customer.customer_type":           0.75,
    "project.requested_delivery":       0.85,
    "project.quote_deadline":           0.85,
    "project.budget_low":               0.80,
    "project.budget_high":              0.80,
    "line_items[].matched_sku":         0.90,   # fuzzy match, expensive to get wrong
    "line_items[].quantity":            0.92,   # a qty error scales the whole quote
    "line_items[].dimensions.width_in": 0.85,
    "line_items[].dimensions.depth_in": 0.85,
    "line_items[].dimensions.height_in": 0.85,
    "line_items[].material":            0.70,
    "line_items[].finish":              0.65,
    "line_items[].com_fabric":          0.65,
}


def threshold_for(path: str) -> float:
    """Index-insensitive lookup: line_items[3].quantity -> line_items[].quantity."""
    import re
    generic = re.sub(r"\[\d+\]", "[]", path)
    return THRESHOLDS.get(generic, THRESHOLDS["_default"])


def apply_policy(lead: CanonicalLead) -> CanonicalLead:
    """Stamp AUTO_COMMITTED / NEEDS_REVIEW / NOT_FOUND across every field.

    This is the only place that decides what a human sees. Keep it here so the
    review queue is a pure function of confidence, and the demo can show the
    threshold sliders changing the queue live.
    """
    flagged: list[str] = []
    total = committed = 0

    for path, field in iter_extracted(lead):
        if field.status in (FieldStatus.HUMAN_CORRECTED, FieldStatus.HUMAN_CONFIRMED):
            total += 1
            committed += 1
            continue
        if field.value is None:
            field.status = FieldStatus.NOT_FOUND
            # An absent OPTIONAL field is not a decision the system made, so it
            # does not belong in the denominator — counting it there tanks the
            # auto-commit rate with fields nobody ever asked for. An absent
            # REQUIRED field IS a decision (we looked and found nothing), so it
            # counts, and it costs a reviewer.
            if path in REQUIRED_PATHS:
                total += 1
                flagged.append(path)
            continue

        total += 1
        if field.confidence >= threshold_for(path):
            field.status = FieldStatus.AUTO_COMMITTED
            committed += 1
        else:
            field.status = FieldStatus.NEEDS_REVIEW
            flagged.append(path)

    lead.review.flagged_paths = flagged
    lead.metrics.fields_total = total
    lead.metrics.fields_auto_committed = committed
    return lead


REQUIRED_PATHS = {
    "customer.company_name",
    "customer.primary_contact.email",
    "line_items[0].quantity",
    "line_items[0].matched_sku",
}


# --------------------------------------------------------------------------
# Traversal helpers — used by apply_policy, the eval harness, and the UI
# --------------------------------------------------------------------------

def iter_extracted(model: BaseModel, prefix: str = "") -> list[tuple[str, Extracted]]:
    """Walk a model and yield (dotted_path, Extracted) for every envelope."""
    out: list[tuple[str, Extracted]] = []
    for name, _ in type(model).model_fields.items():
        val = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(val, Extracted):
            out.append((path, val))
        elif isinstance(val, BaseModel):
            out.extend(iter_extracted(val, path))
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, BaseModel):
                    out.extend(iter_extracted(item, f"{path}[{i}]"))
    return out


def flatten_values(lead: CanonicalLead) -> dict[str, Any]:
    """Dotted path -> plain value. This is what the eval harness diffs against
    the ground-truth dicts in corpus/specs.py."""
    flat: dict[str, Any] = {}
    for path, field in iter_extracted(lead):
        v = field.value
        flat[path] = v.value if isinstance(v, Enum) else v
    return flat


def flatten_confidences(lead: CanonicalLead) -> dict[str, float]:
    return {path: f.confidence for path, f in iter_extracted(lead)}
