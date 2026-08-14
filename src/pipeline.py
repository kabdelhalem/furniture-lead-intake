"""
The lead-intake pipeline, as a LangGraph graph.

    extract -> assemble -> route -> review -> END

LangGraph earns its place here for exactly one reason: the review step is a real
interrupt/resume. When a lead has flagged fields and the run is interactive, the
`review` node calls `interrupt(...)`, the graph checkpoints and pauses, and a
human (via the UI/API) resumes it with `Command(resume=corrections)`. That is a
durable, resumable human-in-the-loop step, not decoration — the rest of the flow
is deterministic and could be a plain function.

Checkpointed state is kept as JSON strings and plain lists, so it serializes
cleanly (no custom types in the checkpoint) and the pause can outlive the
process. The per-lead artifacts and the LLM client are captured in the node
closures instead of the state, so nothing unserializable is ever checkpointed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .assemble import assemble
from .extract import extract, needs_reconciliation, reconcile
from .extract_types import ExtractionResult
from .ingest import IngestedArtifact
from .llm import LLM
from .routing import route
from .schema import (
    CanonicalLead,
    Correction,
    FieldStatus,
    ReviewStatus,
    apply_policy,
    iter_extracted,
)


class PipelineState(TypedDict, total=False):
    interactive: bool
    extraction_json: str
    lead_json: str
    flagged: list[str]
    corrections: list[dict[str, Any]]


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------

def build_pipeline(
    artifacts: list[IngestedArtifact],
    llm: LLM,
    *,
    lead_id: str,
    received_at: datetime,
):
    """Compile a pipeline graph bound to one lead's artifacts and LLM client.

    Cheap to build per lead; keeps the heavy, unserializable objects out of the
    checkpointed state.
    """

    def _extract(state: PipelineState) -> dict:
        result = extract(artifacts, llm)
        if needs_reconciliation(artifacts):
            result = reconcile(result, artifacts, llm)
        return {"extraction_json": result.model_dump_json()}

    def _assemble(state: PipelineState) -> dict:
        result = ExtractionResult.model_validate_json(state["extraction_json"])
        lead = assemble(result, artifacts, lead_id=lead_id,
                        received_at=received_at, metrics=llm.metrics)
        return {"lead_json": lead.model_dump_json(), "flagged": lead.review.flagged_paths}

    def _route(state: PipelineState) -> dict:
        lead = CanonicalLead.model_validate_json(state["lead_json"])
        route(lead, now=received_at)
        return {"lead_json": lead.model_dump_json()}

    def _review(state: PipelineState) -> dict:
        # Nothing to review, or a batch run: straight through.
        if not state.get("interactive") or not state.get("flagged"):
            return {}
        lead = CanonicalLead.model_validate_json(state["lead_json"])
        decisions = interrupt({
            "lead_id": lead_id,
            "flagged_paths": state["flagged"],
            "message": "Confirm or correct the flagged fields.",
        })
        applied = apply_corrections(lead, decisions or [])
        return {
            "lead_json": lead.model_dump_json(),
            "corrections": [c.model_dump(mode="json") for c in applied],
        }

    g = StateGraph(PipelineState)
    g.add_node("extract", _extract)
    g.add_node("assemble", _assemble)
    g.add_node("route", _route)
    g.add_node("review", _review)
    g.add_edge(START, "extract")
    g.add_edge("extract", "assemble")
    g.add_edge("assemble", "route")
    g.add_edge("route", "review")
    g.add_edge("review", END)
    return g.compile(checkpointer=MemorySaver())


# --------------------------------------------------------------------------
# Convenience runners
# --------------------------------------------------------------------------

def run_lead(
    artifacts: list[IngestedArtifact],
    *,
    lead_id: str,
    received_at: datetime,
    llm: LLM,
) -> CanonicalLead:
    """Run a lead straight through with no human review — the eval/batch path."""
    app = build_pipeline(artifacts, llm, lead_id=lead_id, received_at=received_at)
    out = app.invoke({"interactive": False}, _config(lead_id))
    return CanonicalLead.model_validate_json(out["lead_json"])


def _config(lead_id: str) -> dict:
    return {"configurable": {"thread_id": lead_id}}


# --------------------------------------------------------------------------
# Applying human corrections
# --------------------------------------------------------------------------

def apply_corrections(lead: CanonicalLead, decisions: list[dict[str, Any]]) -> list[Correction]:
    """Apply reviewer decisions to a lead in place and return the audit trail.

    Each decision is {field_path, new_value, reviewer?, reason_code?}. A decision
    with no `new_value` key is a *confirmation* (the reviewer looked and agreed);
    one with `new_value` is a correction. Both stamp a human status so
    apply_policy keeps them committed, and both are recorded — a correction is a
    future eval case and few-shot example, a confirmation is a calibration
    signal.
    """
    envelopes = dict(iter_extracted(lead))
    corrections: list[Correction] = []
    reviewer = ""

    for d in decisions:
        path = d.get("field_path")
        field = envelopes.get(path)
        if field is None:
            continue
        reviewer = d.get("reviewer", reviewer)
        if "new_value" in d:
            corrections.append(Correction(
                field_path=path, old_value=field.value, new_value=d["new_value"],
                old_confidence=field.confidence, reviewer=d.get("reviewer", ""),
                reason_code=d.get("reason_code"),
            ))
            field.value = d["new_value"]
            field.status = FieldStatus.HUMAN_CORRECTED
        else:
            field.status = FieldStatus.HUMAN_CONFIRMED

    apply_policy(lead)                          # recompute rates; human statuses stick
    lead.review.corrections.extend(corrections)
    lead.review.reviewer = reviewer or lead.review.reviewer
    lead.review.status = ReviewStatus.APPROVED
    return corrections
