"""
Tests for raw (pasted/uploaded) lead ingestion and the /ingest-raw endpoint.

build_artifacts is deterministic and tested directly. The endpoint's live model
call is replayed from a seeded cache (via the injectable live_llm_factory), so
the whole throw-any-lead-at-it path is exercised offline.
"""

from __future__ import annotations

import json
import pathlib

from fastapi.testclient import TestClient

from src.api import create_app
from src.extract import _EXTRACT_SYSTEM, render_source
from src.llm import LLM, TIER_MODELS, LLMMode, ModelTier, _request_key
from src.rawlead import build_artifacts, kind_for
from src.store import init_db

_EMAIL = ("From: Jane Roe <jroe@acme.com>\n"
          "Subject: quick quote\n\n"
          "Hi, we need 5 Ashfield task chairs in black. Ship to Austin TX.\n\nJane")


# --------------------------------------------------------------------------
# build_artifacts (deterministic)
# --------------------------------------------------------------------------

def test_kind_for_guesses_by_extension():
    assert kind_for("x.eml") == "email"
    assert kind_for("takeoff.xlsx") == "xlsx"
    assert kind_for("call.txt") == "transcript"
    assert kind_for("plain") == "email"          # default

def test_build_from_pasted_text():
    arts = build_artifacts("pasted.eml", text=_EMAIL)
    assert len(arts) == 1 and arts[0].kind == "email"
    assert "jroe@acme.com" in arts[0].text
    assert any(b.locator for b in arts[0].blocks)

def test_build_requires_input():
    import pytest
    with pytest.raises(ValueError):
        build_artifacts("x.eml")


# --------------------------------------------------------------------------
# /ingest-raw end to end (replayed)
# --------------------------------------------------------------------------

_RESPONSE = {
    "is_lead": {"value": "true", "certainty": "certain"},
    "channel": {"value": "email", "certainty": "certain"},
    "company_name": {"value": "Acme", "certainty": "high"},
    "primary_contact": {"email": {"value": "jroe@acme.com", "certainty": "high"},
                        "full_name": {"value": "Jane Roe", "certainty": "high"}},
    "site_city": {"value": "Austin", "certainty": "high"},
    "site_state": {"value": "TX", "certainty": "high"},
    "line_items": [{
        "raw_description": "Ashfield task chair, black",
        "quantity": {"value": "5", "certainty": "high"},
        "finish": {"value": "black", "certainty": "high"},
    }],
}


def test_ingest_raw_runs_the_pipeline_on_pasted_text(tmp_path: pathlib.Path):
    # Seed the extraction cache for exactly what /ingest-raw will request.
    arts = build_artifacts("pasted.eml", text=_EMAIL, artifact_id="RAW-001::pasted.eml")
    source = render_source(arts)
    key = _request_key(LLM._build_request(TIER_MODELS[ModelTier.FAST], _EXTRACT_SYSTEM,
                                          source, 4096, None, None))
    (tmp_path / f"{key}.json").write_text(json.dumps({
        "text": json.dumps(_RESPONSE),
        "input_tokens": 300, "output_tokens": 80, "latency_ms": 400}))

    app = create_app(engine=init_db("sqlite://"),
                     live_llm_factory=lambda: LLM(mode=LLMMode.REPLAY, cache_dir=tmp_path))
    c = TestClient(app)
    r = c.post("/ingest-raw", json={"text": _EMAIL, "filename": "pasted.eml"}).json()

    assert r["lead"]["lead_id"] == "RAW-001"
    assert r["lead"]["is_lead"]["value"] is True
    assert r["lead"]["line_items"][0]["matched_sku"]["value"] == "ASH-TSK-30"
    assert r["lead"]["line_items"][0]["quantity"]["value"] == 5
    # source is returned alongside so the UI can show source vs. extraction
    assert r["source"][0]["kind"] == "email"
    assert any(b["locator"] for b in r["source"][0]["blocks"])
    # ...and it's persisted (a second paste gets RAW-002)
    r2 = c.post("/ingest-raw", json={"text": _EMAIL, "filename": "pasted.eml"}).json()
    assert r2["lead"]["lead_id"] == "RAW-002"


def test_ingest_raw_requires_input():
    c = TestClient(create_app(engine=init_db("sqlite://")))
    assert c.post("/ingest-raw", json={}).status_code == 400
