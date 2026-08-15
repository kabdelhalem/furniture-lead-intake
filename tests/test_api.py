"""
Tests for the FastAPI layer.

`/seed` runs the real pipeline over the corpus, replaying the committed cache —
so these exercise the full stack (ingest -> pipeline -> store -> HTTP) offline,
with no API key. The store is in-memory and seeded once per module.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from src import schema
from src.api import create_app
from src.store import init_db

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Ensure the corpus exists (the cache was recorded against it).
    if not (REPO_ROOT / "corpus" / "manifest.json").exists():
        from src.corpus.generate import generate
        generate(REPO_ROOT / "corpus")
    app = create_app(engine=init_db("sqlite://"), corpus_dir=REPO_ROOT / "corpus")
    c = TestClient(app)
    seeded = c.post("/seed").json()
    assert seeded["loaded"] == 15 and seeded["skipped"] == [], seeded
    return c


@pytest.fixture(autouse=True)
def _restore_thresholds():
    snapshot = dict(schema.THRESHOLDS)
    yield
    schema.THRESHOLDS.clear()
    schema.THRESHOLDS.update(snapshot)


def test_health():
    c = TestClient(create_app(engine=init_db("sqlite://")))
    assert c.get("/health").json() == {"status": "ok"}


def test_queue_lists_all_leads_ordered_by_priority(client):
    leads = client.get("/leads").json()
    assert len(leads) == 15
    scores = [l["priority_score"] for l in leads]
    assert scores == sorted(scores, reverse=True)   # priority desc


def test_lead_detail_carries_envelopes(client):
    lead = client.get("/leads/L001").json()
    assert lead["is_lead"]["value"] is True
    item = lead["line_items"][0]
    assert item["matched_sku"]["value"] == "ASH-TSK-30H"
    # every committed value should carry evidence
    assert lead["customer"]["company_name"]["evidence"]


def test_not_a_lead_is_stored_but_gated(client):
    l013 = client.get("/leads/L013").json()
    assert l013["is_lead"]["value"] is False


def test_review_applies_a_correction(client):
    # L007's ambiguous SKU is flagged (value None); a reviewer resolves it.
    resp = client.post("/leads/L007/review", json={"decisions": [{
        "field_path": "line_items[0].matched_sku", "new_value": "MER-CT-120",
        "reviewer": "kareem", "reason_code": "wrong_sku",
    }]}).json()
    assert resp["status"] == "approved"
    assert resp["corrections"] == 1

    lead = client.get("/leads/L007").json()
    sku = lead["line_items"][0]["matched_sku"]
    assert sku["value"] == "MER-CT-120"
    assert sku["status"] == "human_corrected"


def test_dashboard_reports_auto_commit_and_roi(client):
    d = client.get("/dashboard").json()
    assert d["total_leads"] == 15
    assert d["not_leads"] >= 1                       # L013 is not a lead
    assert 0.0 < d["auto_commit_rate"] <= 1.0
    assert d["fields_auto_committed"] > 0
    assert d["reviewer_minutes_saved_estimate"] > 0
    assert d["cost_usd"] >= 0.0


def test_threshold_slider_resizes_the_queue(client):
    before = client.get("/dashboard").json()["review_queue"]
    # Raise every finish/material bar to make more fields need review.
    resp = client.put("/thresholds", json={"overrides": {
        "line_items[].finish": "certain", "line_items[].material": "certain",
        "customer.company_name": "certain",
    }}).json()
    assert resp["review_queue_after"] >= resp["review_queue_before"]
    after = client.get("/dashboard").json()["review_queue"]
    assert after >= before
    # Reset restores the baseline queue.
    client.put("/thresholds", json={"reset": True})


def test_simulate_inbox_runs_one_lead():
    app = create_app(engine=init_db("sqlite://"), corpus_dir=REPO_ROOT / "corpus")
    c = TestClient(app)
    assert c.get("/leads").json() == []              # empty to start
    summary = c.post("/simulate-inbox", json={"lead_id": "L001"}).json()
    assert summary["lead_id"] == "L001"
    assert len(c.get("/leads").json()) == 1
