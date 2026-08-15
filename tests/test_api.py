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
def client(tmp_path_factory) -> TestClient:
    # Curated-only corpus (15 leads) so /seed is deterministic and fully cached;
    # renders byte-identically to the real corpus, so it hits the committed cache.
    cdir = tmp_path_factory.mktemp("corpus")
    from src.corpus.generate import generate
    generate(cdir, synthetic=0)
    app = create_app(engine=init_db("sqlite://"), corpus_dir=cdir)
    c = TestClient(app)
    seeded = c.post("/seed").json()
    assert seeded["loaded"] == 15 and seeded["skipped"] == [], seeded
    return c


def test_simulate_inbox_runs_one_lead_curated(tmp_path_factory):
    cdir = tmp_path_factory.mktemp("corpus")
    from src.corpus.generate import generate
    generate(cdir, synthetic=0)
    app = create_app(engine=init_db("sqlite://"), corpus_dir=cdir)
    c = TestClient(app)
    assert c.get("/leads").json() == []
    summary = c.post("/simulate-inbox", json={"lead_id": "L001"}).json()
    assert summary["lead_id"] == "L001"
    assert len(c.get("/leads").json()) == 1


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


# --------------------------------------------------------------------------
# Dedup + source preview
# --------------------------------------------------------------------------

def test_resubmission_is_deduplicated_on_seed(client):
    # L012 is a resubmission of L001; seeding should link it, not queue it fresh.
    l012 = client.get("/leads/L012").json()
    assert l012["review"]["duplicate_of"] == "L001"
    assert l012["review"]["status"] == "duplicate"


def test_lead_source_returns_located_blocks(client):
    src = client.get("/leads/L001/source").json()
    assert src and src[0]["kind"] == "email"
    assert any(b["locator"] for b in src[0]["blocks"])          # blocks carry locators
    assert "dwhitfield@northgatelabs.com" in src[0]["text"]


def test_lead_source_marks_scanned_fax_as_ocr(client):
    src = client.get("/leads/L004/source").json()
    fax = next(a for a in src if a["kind"] == "pdf_scanned")
    assert fax["needs_ocr"] is True and fax["text"] == ""        # no text layer


def test_artifact_raw_serves_the_original_file(client):
    lead = client.get("/leads/L001").json()
    aid = lead["source_artifacts"][0]["artifact_id"]            # "L001::L001.eml"
    resp = client.get(f"/artifacts/{aid}/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("message/rfc822")
    assert b"Subject:" in resp.content                          # a real .eml

def test_artifact_raw_404_for_unknown(client):
    assert client.get("/artifacts/nope::nope.pdf/raw").status_code == 404


def test_calibration_reports_per_level_accuracy(client):
    cal = client.get("/calibration").json()
    assert [r["level"] for r in cal["levels"]] == \
        ["certain", "high", "medium", "low", "severe"]
    assert cal["overall"]["n"] == 239          # the curated scored fields
    by = {r["level"]: r for r in cal["levels"]}
    assert by["certain"]["accuracy"] >= 0.9     # the top of the ladder is trustworthy
    assert isinstance(cal["monotonic"], bool)


def test_observability_reflects_reviews(tmp_path_factory):
    cdir = tmp_path_factory.mktemp("corpus")
    from src.corpus.generate import generate
    generate(cdir, synthetic=0)
    c = TestClient(create_app(engine=init_db("sqlite://"), corpus_dir=cdir))
    c.post("/simulate-inbox", json={"lead_id": "L007"})     # ambiguous SKU -> flagged
    # Empty until a human acts.
    assert c.get("/observability").json()["reviewed_fields"] == 0
    c.post("/leads/L007/review", json={"decisions": [{
        "field_path": "line_items[0].matched_sku", "new_value": "MER-CT-120",
        "reviewer": "kareem", "reason_code": "wrong_sku"}]})
    obs = c.get("/observability").json()
    assert obs["corrections"] >= 1
    assert "wrong_sku" in obs["reason_codes"]
    assert "line_items[].matched_sku" in obs["by_field_class"]
