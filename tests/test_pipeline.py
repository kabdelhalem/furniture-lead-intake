"""
Tests for the LangGraph pipeline.

The model call replays from a seeded cache (no key), so we can exercise the full
graph offline: the straight-through batch path (extract -> assemble -> route)
and the human-in-the-loop path, where the graph interrupts on flagged fields and
resumes with a reviewer's correction.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime

from langgraph.types import Command

from src.extract import _EXTRACT_SYSTEM, render_source
from src.ingest import Block, IngestedArtifact
from src.llm import LLM, TIER_MODELS, LLMMode, ModelTier, _request_key
from src.pipeline import apply_corrections, build_pipeline, run_lead
from src.schema import CanonicalLead, FieldStatus, ReviewStatus, iter_extracted

RECEIVED = datetime(2026, 8, 14, 9, 0)


def _art(kind="email", blocks=(("body line 1", "hello"),), aid="A::x"):
    a = IngestedArtifact(artifact_id=aid, kind=kind, filename=f"f.{kind}", sha256="0", bytes=1)
    a.blocks = [Block(loc, txt) for loc, txt in blocks]
    return a


def _seed(tmp_path: pathlib.Path, artifacts, response: dict) -> LLM:
    """Seed the FAST-extraction cache entry for these artifacts and return a
    replay-mode LLM bound to that cache."""
    source = render_source(artifacts)
    request = LLM._build_request(TIER_MODELS[ModelTier.FAST], _EXTRACT_SYSTEM,
                                 source, 4096, None, None)
    key = _request_key(request)
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "text": json.dumps(response),
        "input_tokens": 800, "output_tokens": 200, "latency_ms": 600,
    }))
    return LLM(mode=LLMMode.REPLAY, cache_dir=tmp_path)


# --------------------------------------------------------------------------
# Batch path
# --------------------------------------------------------------------------

_CLEAN = {
    "is_lead": {"value": "true", "certainty": 0.98},
    "channel": {"value": "email", "certainty": 0.99},
    "company_name": {"value": "Northgate Labs", "certainty": 0.95},
    "site_state": {"value": "MA", "certainty": 0.9},
    "line_items": [{
        "raw_description": "Ashfield task chairs, high-back, graphite",
        "quantity": {"value": "8", "certainty": 0.95},
        "finish": {"value": "graphite", "certainty": 0.9},
    }],
}


def test_batch_run_produces_routed_lead(tmp_path):
    artifacts = [_art()]
    llm = _seed(tmp_path, artifacts, _CLEAN)
    lead = run_lead(artifacts, lead_id="L001", received_at=RECEIVED, llm=llm)

    assert isinstance(lead, CanonicalLead)
    assert lead.is_lead.value is True
    assert lead.line_items[0].matched_sku.value == "ASH-TSK-30H"
    # routing ran: a real lead gets a segment and a territory rule
    assert lead.routing.segment in ("smb", "mid_market", "enterprise")
    assert any(r.startswith("territory_MA") for r in lead.routing.rules_fired)
    # the model call was accounted for on the FAST tier
    assert llm.metrics.model_calls == 1
    assert llm.tier_usage()["fast"] == 1
    # metrics were populated by apply_policy
    assert lead.metrics.fields_total > 0


def test_batch_run_is_deterministic(tmp_path):
    artifacts = [_art()]
    a = run_lead(artifacts, lead_id="L001", received_at=RECEIVED, llm=_seed(tmp_path, artifacts, _CLEAN))
    b = run_lead(artifacts, lead_id="L001", received_at=RECEIVED, llm=_seed(tmp_path, artifacts, _CLEAN))
    assert a.model_dump() == b.model_dump()


# --------------------------------------------------------------------------
# Human-in-the-loop: interrupt then resume with a correction
# --------------------------------------------------------------------------

_AMBIGUOUS = {
    "is_lead": {"value": "true", "certainty": 0.9},
    "line_items": [{
        "raw_description": "the big walnut conference table",
        "quantity": {"value": "3", "certainty": 0.9},
    }],
}


def test_interactive_run_interrupts_on_flagged_field(tmp_path):
    artifacts = [_art(blocks=(("body line 1", "3 of the big walnut conference table"),))]
    llm = _seed(tmp_path, artifacts, _AMBIGUOUS)
    app = build_pipeline(artifacts, llm, lead_id="L007", received_at=RECEIVED)
    cfg = {"configurable": {"thread_id": "L007"}}

    out = app.invoke({"interactive": True}, cfg)
    # The ambiguous SKU is flagged, so the graph paused at review.
    assert "__interrupt__" in out
    payload = out["__interrupt__"][0].value
    assert "line_items[0].matched_sku" in payload["flagged_paths"]

    # A reviewer resolves the SKU; resume the graph with the correction.
    resumed = app.invoke(
        Command(resume=[{
            "field_path": "line_items[0].matched_sku",
            "new_value": "MER-CT-120",
            "reviewer": "kareem",
            "reason_code": "wrong_sku",
        }]),
        cfg,
    )
    lead = CanonicalLead.model_validate_json(resumed["lead_json"])
    sku = lead.line_items[0].matched_sku
    assert sku.value == "MER-CT-120"
    assert sku.status is FieldStatus.HUMAN_CORRECTED
    assert lead.review.status is ReviewStatus.APPROVED
    assert lead.review.corrections[0].reason_code == "wrong_sku"
    assert lead.review.reviewer == "kareem"


def test_batch_run_never_interrupts_even_when_flagged(tmp_path):
    # Same ambiguous lead, but a non-interactive run must complete, not pause.
    artifacts = [_art(blocks=(("body line 1", "3 of the big walnut conference table"),))]
    llm = _seed(tmp_path, artifacts, _AMBIGUOUS)
    lead = run_lead(artifacts, lead_id="L007", received_at=RECEIVED, llm=llm)
    assert "line_items[0].matched_sku" in lead.review.flagged_paths  # still flagged
    assert lead.review.status is ReviewStatus.PENDING                 # ...just not reviewed


# --------------------------------------------------------------------------
# Corrections helper
# --------------------------------------------------------------------------

def test_apply_corrections_records_confirmations_and_corrections(tmp_path):
    artifacts = [_art()]
    lead = run_lead(artifacts, lead_id="L001", received_at=RECEIVED, llm=_seed(tmp_path, artifacts, _CLEAN))
    applied = apply_corrections(lead, [
        {"field_path": "customer.company_name", "new_value": "Northgate Laboratories",
         "reviewer": "kareem", "reason_code": "typo"},
        {"field_path": "line_items[0].finish"},   # a confirmation, not a correction
    ])
    envelopes = dict(iter_extracted(lead))
    assert envelopes["customer.company_name"].value == "Northgate Laboratories"
    assert envelopes["customer.company_name"].status is FieldStatus.HUMAN_CORRECTED
    assert envelopes["line_items[0].finish"].status is FieldStatus.HUMAN_CONFIRMED
    assert len(applied) == 1  # only the correction is an audit-trail entry
