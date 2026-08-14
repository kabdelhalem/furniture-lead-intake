"""
Tests for the model-driven extractor.

The model call itself can't run offline, so we test everything around it: JSON
parsing tolerance, source rendering, the reconciliation gate, and — most
importantly — the full replay path. We seed the on-disk cache with a model
response and confirm extract -> assemble -> eval scores 100% with no API key,
which is exactly what `make eval` does once the cache is recorded.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime

import pytest

from src.assemble import assemble
from src.eval import score_lead
from src.extract import (
    _EXTRACT_SYSTEM,
    _loads,
    extract,
    needs_reconciliation,
    render_source,
)
from src.extract_types import ExtractionResult
from src.ingest import Block, IngestedArtifact
from src.llm import LLM, TIER_MODELS, LLMMode, ModelTier, _request_key


# --------------------------------------------------------------------------
# JSON parsing tolerance
# --------------------------------------------------------------------------

def test_loads_bare_json():
    assert _loads('{"a": 1}') == {"a": 1}

def test_loads_code_fenced():
    assert _loads('```json\n{"a": 1}\n```') == {"a": 1}

def test_loads_with_surrounding_prose():
    assert _loads('Here is the JSON:\n{"a": 1}\nHope that helps!') == {"a": 1}

def test_loads_rejects_non_json():
    with pytest.raises(json.JSONDecodeError):
        _loads("not json at all")


# --------------------------------------------------------------------------
# Source rendering
# --------------------------------------------------------------------------

def _art(kind, blocks, *, needs_ocr=False, raw_b64=None, media_type_kind=None):
    a = IngestedArtifact(artifact_id=f"A::{kind}", kind=kind, filename=f"f.{kind}",
                         sha256="0", bytes=1, needs_ocr=needs_ocr, raw_b64=raw_b64)
    a.blocks = [Block(loc, txt) for loc, txt in blocks]
    return a

def test_render_source_labels_artifacts_and_locators():
    a = _art("email", [("body line 3", "We need 8 chairs")])
    out = render_source([a])
    assert "[email]" in out
    assert "[body line 3] We need 8 chairs" in out

def test_render_source_notes_scanned_document():
    a = _art("pdf_scanned", [], needs_ocr=True)
    out = render_source([a])
    assert "no text layer" in out


# --------------------------------------------------------------------------
# Reconciliation gate
# --------------------------------------------------------------------------

def test_needs_reconciliation_multi_content():
    arts = [_art("email", []), _art("pdf_text", []), _art("xlsx", [])]
    assert needs_reconciliation(arts) is True

def test_no_reconciliation_single_content():
    arts = [_art("email", []), _art("xlsx", [])]  # email is a cover note, xlsx the data
    assert needs_reconciliation(arts) is False


# --------------------------------------------------------------------------
# Full replay path: seed cache -> extract -> assemble -> eval = 100%
# --------------------------------------------------------------------------

_L001_RESPONSE = {
    "is_lead": {"value": "true", "certainty": 0.98},
    "channel": {"value": "email", "certainty": 0.99},
    "company_name": {"value": "Northgate Labs", "certainty": 0.95, "locator": "body line 4"},
    "customer_type": {"value": "end_customer", "certainty": 0.85},
    "primary_contact": {
        "full_name": {"value": "Dana Whitfield", "certainty": 0.95},
        "email": {"value": "dwhitfield@northgatelabs.com", "certainty": 0.92},
        "phone": {"value": "617-555-0182", "certainty": 0.92},
        "title": {"value": "Facilities Manager", "certainty": 0.85},
    },
    "site_city": {"value": "Cambridge", "certainty": 0.9},
    "site_state": {"value": "MA", "certainty": 0.9},
    "requested_delivery": {"value": "October 15", "certainty": 0.85},
    "line_items": [{
        "raw_description": "Ashfield task chairs, high-back, graphite",
        "quantity": {"value": "8", "certainty": 0.95, "snippet": "8 of the Ashfield task chairs"},
        "finish": {"value": "graphite", "certainty": 0.9},
    }],
}

_L001_TRUTH = {"fields": {
    "is_lead": True, "channel": "email",
    "customer.company_name": "Northgate Labs", "customer.customer_type": "end_customer",
    "customer.primary_contact.full_name": "Dana Whitfield",
    "customer.primary_contact.email": "dwhitfield@northgatelabs.com",
    "customer.primary_contact.phone": "617-555-0182",
    "customer.primary_contact.title": "Facilities Manager",
    "project.site_city": "Cambridge", "project.site_state": "MA",
    "project.requested_delivery": "2026-10-15",
    "line_items[0].matched_sku": "ASH-TSK-30H",
    "line_items[0].quantity": 8, "line_items[0].finish": "graphite",
}}


def test_extract_replay_then_assemble_scores_100(tmp_path: pathlib.Path):
    artifacts = [_art("email", [("body line 4", "Facilities Manager | Northgate Labs")])]
    source = render_source(artifacts)

    # Seed the cache for exactly the request extract() will build.
    request = LLM._build_request(TIER_MODELS[ModelTier.FAST], _EXTRACT_SYSTEM, source, 4096, None, None)
    key = _request_key(request)
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "text": json.dumps(_L001_RESPONSE),
        "input_tokens": 900, "output_tokens": 220, "latency_ms": 700,
    }))

    llm = LLM(mode=LLMMode.REPLAY, cache_dir=tmp_path)
    result = extract(artifacts, llm)
    assert isinstance(result, ExtractionResult)

    lead = assemble(result, artifacts, lead_id="L001", received_at=datetime(2026, 8, 14, 9, 0))
    score = score_lead(lead, _L001_TRUTH)
    assert score.field_accuracy == 1.0, [r for r in score.field_results if not r.ok]
    # ...and the model call was accounted for on the FAST tier.
    assert llm.metrics.model_calls == 1
    assert llm.tier_usage()["fast"] == 1


# --------------------------------------------------------------------------
# Document (vision) path threads through the wrapper + cache key
# --------------------------------------------------------------------------

def test_document_path_changes_request_and_key():
    with_doc = LLM._build_request(
        "claude-haiku-4-5", "sys", "read this", 4096, None,
        documents=[{"media_type": "application/pdf", "data_b64": "QUJD"}],
    )
    without = LLM._build_request("claude-haiku-4-5", "sys", "read this", 4096, None, None)
    assert isinstance(with_doc["messages"][0]["content"], list)
    assert with_doc["messages"][0]["content"][0]["type"] == "document"
    assert _request_key(with_doc) != _request_key(without)
