"""
Model-driven extraction: ingested artifacts -> a raw ExtractionResult.

This is the *read and locate* half (the deterministic typing/matching/scoring
half is `assemble.py`). One FAST-tier call does the bulk read; a STRONG-tier
reconciliation pass runs only for leads whose evidence spans two or more
content artifacts, where a cheaper model is most likely to miss a cross-source
conflict (L014). That is the whole justification for the tiered-model design:
spend the expensive model only where ambiguity actually lives.

Every call goes through `src/llm.py`, so tokens, cost, and tier are recorded,
and responses replay from the on-disk cache when offline.
"""

from __future__ import annotations

import json
import re

from .extract_types import ExtractionResult
from .ingest import IngestedArtifact
from .llm import LLM, ModelTier

# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------

_JSON_SHAPE = """
Return a single JSON object. Every leaf marked <field> is an object:
  {"value": <verbatim string or null>,
   "certainty": "<certain|high|medium|low|severe>",
   "locator": "<where you found it, e.g. 'body line 7' or 'Takeoff!C14'>",
   "snippet": "<the source text you read it from>", "conflict": <true|false>}

certainty is a LEVEL, not a number — report how sure you are that you read this
field correctly:
  certain = stated explicitly and unambiguously, verbatim
  high    = clearly stated, minor interpretation
  medium  = inferred or lightly ambiguous
  low     = hedged, unclear, or you had to guess between readings
  severe  = you are extracting this against real doubt (conflicting or garbled)
Do not fabricate certainty — a hedged or inferred value must not be "high".

Shape:
{
  "is_lead": <field>,           // true only for a genuine purchase/quote inquiry
  "channel": <field>,           // email | phone | fax | web_form
  "company_name": <field>,
  "customer_type": <field>,     // dealer | designer | contractor | end_customer | unknown
  "primary_contact": {"full_name": <field>, "email": <field>, "phone": <field>,
                      "title": <field>, "is_decision_maker": <field>},
  "billing_city": <field>, "billing_state": <field>, "existing_account_id": <field>,
  "project_name": <field>, "site_city": <field>, "site_state": <field>,
  "requested_delivery": <field>, "quote_deadline": <field>,
  "budget": <field>,            // the raw budget span, e.g. "180-220k"
  "install_required": <field>,
  "line_items": [
    {"raw_description": "<verbatim product phrase>", "quantity": <field>,
     "material": <field>, "finish": <field>, "com_fabric": <field>,
     "dimensions": {"width": <field>, "depth": <field>, "height": <field>},
     "target_unit_price": <field>}
  ]
}
""".strip()

_EXTRACT_SYSTEM = f"""You extract structured sales-lead data for a furniture \
manufacturer from raw inbound artifacts (email, PDF, spreadsheet, CAD notes, \
call transcripts). You READ and LOCATE only — you do not convert units, resolve \
product codes, or reformat values. The downstream system does that.

Hard rules:
- NEVER invent a value. If the source does not state it, value is null. A guessed \
number is worse than null.
- Copy values VERBATIM as strings. Keep "1800mm" as "1800mm" (no conversion), \
"14 ea" as "14 ea", "October 15" as "October 15".
- Cite where you read each value in `locator`, using the [bracketed locators] shown \
in the source, and put the exact source text in `snippet`.
- Forwarded/threaded email: quote the LATEST instruction only. Earlier superseded \
scopes in the chain are dead — ignore their numbers.
- The primary contact is the actual BUYER / decision-maker, not necessarily the \
sender. If someone writes on behalf of a principal, the principal is the contact.
- Quantities: give your single best number as `value`; if the source hedges \
("four, maybe five"), keep the hedged wording in `snippet` and lower `certainty`.
- If two artifacts disagree on a field, set `conflict`: true on it and do not \
silently pick one at high certainty.
- is_lead is false for anything that is not a purchase inquiry (invoice/AP disputes, \
order-status questions, complaints). If is_lead is false, leave other fields null.
- One line_items entry per distinct product. `raw_description` is the verbatim \
product phrase — do NOT resolve it to a product code.

{_JSON_SHAPE}

Output ONLY the JSON object. No prose, no code fences."""

_RECONCILE_SYSTEM = """You are a careful reviewer reconciling a draft extraction \
against two or more source artifacts that may disagree. You are given the draft \
JSON and the sources. Return the SAME JSON shape, changed ONLY where the sources \
require it:
- If two artifacts state different values for the same field, set "conflict": true \
on that field and lower its certainty; keep the value the sources instruct to prefer \
(e.g. "go with whatever's cheaper"), else keep the draft value.
- If the draft left a value null but a source clearly states it, fill it in.
- Do not otherwise change values, and never invent one.
Output ONLY the JSON object."""


# --------------------------------------------------------------------------
# Source rendering
# --------------------------------------------------------------------------

def render_source(artifacts: list[IngestedArtifact]) -> str:
    """Artifact-labelled, locator-annotated text for the model to read."""
    parts: list[str] = []
    for a in artifacts:
        parts.append(f"=== {a.filename}  [{a.kind}] ===")
        if a.needs_ocr:
            parts.append("(scanned image with no text layer — read the attached document)")
        else:
            parts.extend(f"[{b.locator}] {b.text}" for b in a.blocks)
        parts.append("")
    return "\n".join(parts).strip()


def _vision_artifacts(artifacts: list[IngestedArtifact]) -> list[IngestedArtifact]:
    return [a for a in artifacts if a.needs_ocr and a.raw_b64 and a.media_type]


def _documents(artifacts: list[IngestedArtifact]) -> list[dict[str, str]]:
    return [{"media_type": a.media_type, "data_b64": a.raw_b64}
            for a in _vision_artifacts(artifacts)]


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def extract(artifacts: list[IngestedArtifact], llm: LLM) -> ExtractionResult:
    """FAST-tier read of a lead's artifacts into a raw ExtractionResult."""
    source = render_source(artifacts)
    vision = _vision_artifacts(artifacts)
    result = llm.complete(
        ModelTier.FAST,
        system=_EXTRACT_SYSTEM,
        user=source,
        documents=_documents(artifacts) or None,
        doc_ids=[a.artifact_id for a in vision] or None,
        max_tokens=4096,
    )
    return ExtractionResult.model_validate(_loads(result.text))


def reconcile(
    draft: ExtractionResult, artifacts: list[IngestedArtifact], llm: LLM
) -> ExtractionResult:
    """STRONG-tier cross-artifact reconciliation. Additive: it sets conflict
    flags and fills genuine gaps, and is only worth running when evidence spans
    multiple content artifacts."""
    source = render_source(artifacts)
    user = f"DRAFT EXTRACTION:\n{draft.model_dump_json(indent=0)}\n\nSOURCES:\n{source}"
    result = llm.complete(
        ModelTier.STRONG, system=_RECONCILE_SYSTEM, user=user, max_tokens=4096,
    )
    try:
        return ExtractionResult.model_validate(_loads(result.text))
    except (ValueError, json.JSONDecodeError):
        # A reconciliation that comes back unparseable must never regress the
        # draft — fall back to it rather than failing the lead.
        return draft


def needs_reconciliation(artifacts: list[IngestedArtifact]) -> bool:
    """True when two or more artifacts carry line-item content — the case where a
    cheaper model is most likely to miss a cross-source conflict."""
    content_kinds = {"pdf_text", "pdf_scanned", "xlsx", "dxf"}
    return sum(1 for a in artifacts if a.kind in content_kinds) >= 2


# --------------------------------------------------------------------------
# JSON parsing
# --------------------------------------------------------------------------

def _loads(text: str) -> dict:
    """Parse the model's JSON, tolerating code fences or stray prose around it."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    return json.loads(text)
