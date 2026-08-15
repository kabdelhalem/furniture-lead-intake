"""
Assemble a CanonicalLead from a raw ExtractionResult — the deterministic half of
extraction.

The model read strings and located them; here we type them (units, dates,
phones, money), match SKUs against the catalog, and attach a *calibrated*
confidence to every field via `confidence.score` — folding the model's
self-report together with the deterministic signals this layer produces (regex
validity, match score, clean parses, source hedging, cross-artifact conflict).
Nothing here calls a model. Finally `apply_policy` stamps auto-commit /
needs-review across the record.

Two behaviours worth stating outright:

- **Ambiguous SKUs decline to a value.** When the matcher reports genuine
  near-ties ("the big walnut one" -> four MER-CT-* tables, L007), we do NOT
  commit a guessed SKU: the value is None and the candidates go in
  `alternatives`. An off-nominal-but-identifiable size (1800mm ~ 70.87in, L008)
  is different — we DO name the SKU, but the off-nominal signal holds its
  confidence below the auto-commit bar.
- **A hedged quantity is detected from its own evidence.** "four, maybe five"
  carries the hedge in the snippet, so the deterministic layer can see it and
  damp the confidence without trusting the model to have flagged it.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from . import confidence, normalize
from .catalog import by_sku
from .confidence import Signals
from .extract_types import EField, ELineItem, ExtractionResult
from .ingest import IngestedArtifact
from .matching import match_sku, nominal_inches
from .schema import (
    ArtifactKind,
    CanonicalLead,
    Channel,
    Confidence,
    Contact,
    Customer,
    CustomerType,
    Dimensions,
    Evidence,
    Extracted,
    LineItem,
    ProjectContext,
    SourceArtifact,
    UnitSystem,
    apply_policy,
)

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_HEDGE_RE = re.compile(r"\bmaybe\b|\bapprox\w*|\baround\b|~|\bor\b|,\s*\d", re.I)
_TRUE = {"true", "yes", "y", "required", "include", "included", "needed"}
_FALSE = {"false", "no", "n", "not required", "excluded", "none"}

_KIND_MAP = {
    "email": ArtifactKind.EMAIL_BODY,
    "pdf_text": ArtifactKind.PDF_TEXT,
    "pdf_scanned": ArtifactKind.PDF_SCANNED,
    "xlsx": ArtifactKind.SPREADSHEET,
    "dxf": ArtifactKind.CAD_DXF,
    "transcript": ArtifactKind.CALL_TRANSCRIPT,
}


def assemble(
    extraction: ExtractionResult,
    artifacts: list[IngestedArtifact],
    *,
    lead_id: str,
    received_at: datetime,
    metrics=None,
) -> CanonicalLead:
    """Type, match, score, and policy-stamp a lead from its raw extraction."""
    primary_id = artifacts[0].artifact_id if artifacts else lead_id
    reference: date = received_at.date()

    def evidence(ef: EField) -> list[Evidence]:
        if ef.value is None and ef.snippet is None:
            return []
        return [Evidence(artifact_id=primary_id, locator=ef.locator, snippet=ef.snippet)]

    def mk(path, value, ef, sig, *, extractor, alternatives=None, note=None) -> Extracted:
        return Extracted(
            value=value,
            confidence=confidence.score(path, sig),
            extractor=extractor,
            evidence=evidence(ef),
            alternatives=alternatives or [],
            note=note or (ef.snippet and None),
        )

    def text(path, ef: EField, *, cross=None) -> Extracted:
        v = ef.value.strip() if ef.value else None
        sig = Signals(present=v is not None, model_level=ef.certainty,
                      cross_artifact="conflict" if ef.conflict else cross)
        return mk(path, v, ef, sig, extractor="fast:text")

    def email_field(path, ef: EField) -> Extracted:
        v = ef.value.strip() if ef.value else None
        valid = bool(v and _EMAIL_RE.fullmatch(v))
        sig = Signals(present=v is not None, model_level=ef.certainty,
                      regex_valid=valid if v else None)
        return mk(path, v, ef, sig, extractor="regex:email")

    def phone_field(path, ef: EField) -> Extracted:
        norm = normalize.normalize_phone(ef.value) if ef.value else None
        sig = Signals(present=norm is not None, model_level=ef.certainty,
                      regex_valid=norm is not None if ef.value else None)
        return mk(path, norm, ef, sig, extractor="regex:phone")

    def date_field(path, ef: EField) -> Extracted:
        iso = normalize.parse_date(ef.value, reference) if ef.value else None
        v = date.fromisoformat(iso) if iso else None
        sig = Signals(present=v is not None, model_level=ef.certainty,
                      normalized_ok=iso is not None if ef.value else None)
        return mk(path, v, ef, sig, extractor="normalize:date")

    def bool_field(path, ef: EField) -> Extracted:
        v = _parse_bool(ef.value)
        sig = Signals(present=v is not None, model_level=ef.certainty)
        return mk(path, v, ef, sig, extractor="fast:bool")

    # ---- customer -------------------------------------------------------
    pc = extraction.primary_contact
    contact = Contact(
        full_name=text("customer.primary_contact.full_name", pc.full_name),
        email=email_field("customer.primary_contact.email", pc.email),
        phone=phone_field("customer.primary_contact.phone", pc.phone),
        title=text("customer.primary_contact.title", pc.title),
        is_decision_maker=bool_field("customer.primary_contact.is_decision_maker", pc.is_decision_maker),
    )
    customer = Customer(
        company_name=text("customer.company_name", extraction.company_name),
        customer_type=_enum_field("customer.customer_type", extraction.customer_type,
                                  CustomerType, mk),
        primary_contact=contact,
        billing_city=text("customer.billing_city", extraction.billing_city),
        billing_state=text("customer.billing_state", extraction.billing_state),
        existing_account_id=text("customer.existing_account_id", extraction.existing_account_id),
    )

    # ---- project (budget span -> low/high) ------------------------------
    blow, bhigh = normalize.parse_money(extraction.budget.value or "")
    budget_ef = extraction.budget
    project = ProjectContext(
        project_name=text("project.project_name", extraction.project_name),
        site_city=text("project.site_city", extraction.site_city),
        site_state=text("project.site_state", extraction.site_state),
        requested_delivery=date_field("project.requested_delivery", extraction.requested_delivery),
        quote_deadline=date_field("project.quote_deadline", extraction.quote_deadline),
        budget_low=mk("project.budget_low", blow, budget_ef,
                      Signals(present=blow is not None, model_level=budget_ef.certainty,
                              normalized_ok=blow is not None if budget_ef.value else None),
                      extractor="normalize:money"),
        budget_high=mk("project.budget_high", bhigh, budget_ef,
                       Signals(present=bhigh is not None, model_level=budget_ef.certainty,
                               normalized_ok=bhigh is not None if budget_ef.value else None),
                       extractor="normalize:money"),
        install_required=bool_field("project.install_required", extraction.install_required),
    )

    # ---- line items -----------------------------------------------------
    line_items = [
        _assemble_line_item(i, li, reference, mk) for i, li in enumerate(extraction.line_items)
    ]

    lead = CanonicalLead(
        lead_id=lead_id,
        received_at=received_at,
        channel=_channel_field(extraction.channel, artifacts, mk),
        is_lead=bool_field("is_lead", extraction.is_lead),
        source_artifacts=[_source_artifact(a) for a in artifacts],
        customer=customer,
        project=project,
        line_items=line_items,
    )
    # Carry the run's token/cost/tier accounting onto the lead so the dashboard
    # shows a real cost per lead. apply_policy fills the field counts next.
    if metrics is not None:
        lead.metrics.extraction_ms = metrics.extraction_ms
        lead.metrics.total_tokens = metrics.total_tokens
        lead.metrics.cost_usd = metrics.cost_usd
        lead.metrics.model_calls = metrics.model_calls
    return apply_policy(lead)


# --------------------------------------------------------------------------
# Line item
# --------------------------------------------------------------------------

def _assemble_line_item(i: int, li: ELineItem, reference: date, mk) -> LineItem:
    p = f"line_items[{i}]"

    # dimensions first — a parsed width feeds the SKU matcher and unit detection.
    width = normalize.parse_length_to_in(li.dimensions.width.value or "")
    depth = normalize.parse_length_to_in(li.dimensions.depth.value or "")
    height = normalize.parse_length_to_in(li.dimensions.height.value or "")
    raw_dims = " ".join(d.value or "" for d in
                        (li.dimensions.width, li.dimensions.depth, li.dimensions.height))
    units = (UnitSystem.METRIC if re.search(r"\bmm\b|\bcm\b", raw_dims, re.I)
             else UnitSystem.IMPERIAL if raw_dims.strip() else None)

    def dim(name, value, ef):
        sig = Signals(present=value is not None, model_level=ef.certainty,
                      normalized_ok=value is not None if ef.value else None)
        return mk(f"{p}.dimensions.{name}", value, ef, sig, extractor="normalize:length")

    dimensions = Dimensions(
        width_in=dim("width_in", width, li.dimensions.width),
        depth_in=dim("depth_in", depth, li.dimensions.depth),
        height_in=dim("height_in", height, li.dimensions.height),
        source_units=mk(f"{p}.dimensions.source_units", units, EField(),
                        Signals(present=units is not None, model_level=Confidence.HIGH),
                        extractor="normalize:units"),
    )

    # SKU match against the catalog.
    mr = match_sku(li.raw_description, width_in=width)
    is_ambiguous = bool(mr.note and mr.note.startswith("ambiguous"))
    off_nominal = bool(
        mr.sku and width is not None
        and nominal_inches(mr.sku) is not None
        and abs(nominal_inches(mr.sku) - width) > 1.0
    )
    sku_value = None if (mr.sku is None or is_ambiguous) else mr.sku
    alts = ([mr.sku] + mr.alternatives) if (is_ambiguous and mr.sku) else mr.alternatives
    sku = mk(
        f"{p}.matched_sku", sku_value, EField(snippet=li.raw_description or None),
        Signals(present=sku_value is not None, match_score=mr.score,
                ambiguous=is_ambiguous, off_nominal=off_nominal),
        extractor="fuzzy:sku", alternatives=alts, note=mr.note,
    )
    category = by_sku(sku_value)["category"] if sku_value else None

    # quantity — hedge detected from the evidence snippet.
    qty = _parse_int(li.quantity.value)
    hedged = bool(_HEDGE_RE.search(li.quantity.snippet or li.quantity.value or ""))
    quantity = mk(
        f"{p}.quantity", qty, li.quantity,
        Signals(present=qty is not None, model_level=li.quantity.certainty,
                normalized_ok=qty is not None if li.quantity.value else None, hedged=hedged),
        extractor="normalize:int",
    )

    price = normalize.parse_money(li.target_unit_price.value or "")[0]

    def li_text(name, ef):
        v = ef.value.strip() if ef.value else None
        sig = Signals(present=v is not None, model_level=ef.certainty,
                      cross_artifact="conflict" if ef.conflict else None)
        return mk(f"{p}.{name}", v, ef, sig, extractor="fast:text")

    return LineItem(
        raw_description=li.raw_description,
        matched_sku=sku,
        product_category=mk(f"{p}.product_category", category, EField(),
                            Signals(present=category is not None, model_level=Confidence.HIGH),
                            extractor="lookup:category"),
        quantity=quantity,
        dimensions=dimensions,
        material=li_text("material", li.material),
        finish=li_text("finish", li.finish),
        com_fabric=li_text("com_fabric", li.com_fabric),
        target_unit_price=mk(f"{p}.target_unit_price", price, li.target_unit_price,
                             Signals(present=price is not None,
                                     model_level=li.target_unit_price.certainty),
                             extractor="normalize:money"),
    )


# --------------------------------------------------------------------------
# Field helpers
# --------------------------------------------------------------------------

def _enum_field(path, ef: EField, enum_cls, mk) -> Extracted:
    raw = (ef.value or "").strip().lower().replace(" ", "_")
    value = next((m for m in enum_cls if m.value == raw), None)
    if value is None and ef.value:
        value = getattr(enum_cls, "UNKNOWN", None)
    sig = Signals(present=value is not None, model_level=ef.certainty)
    return mk(path, value, ef, sig, extractor="fast:enum")


def _channel_field(ef: EField, artifacts, mk) -> Extracted:
    raw = (ef.value or "").strip().lower()
    value = next((c for c in Channel if c.value == raw), None)
    if value is None and artifacts:  # infer from artifact kinds
        kinds = {a.kind for a in artifacts}
        if "transcript" in kinds:
            value = Channel.PHONE
        elif "pdf_scanned" in kinds:
            value = Channel.FAX
        else:
            value = Channel.EMAIL
    sig = Signals(present=value is not None, model_level=ef.certainty)
    return mk("channel", value, ef, sig, extractor="fast:channel")


def _source_artifact(a: IngestedArtifact) -> SourceArtifact:
    return SourceArtifact(
        artifact_id=a.artifact_id,
        kind=_KIND_MAP.get(a.kind, ArtifactKind.EMAIL_BODY),
        filename=a.filename,
        sha256=a.sha256,
        bytes=a.bytes,
        page_count=a.page_count,
        ocr_applied=a.needs_ocr,
    )


def _parse_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    m = re.search(r"\d+", raw.replace(",", ""))
    return int(m.group(0)) if m else None
