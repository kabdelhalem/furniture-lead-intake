"""
FastAPI layer over the pipeline, store, and policy.

This is scaffolding around the extraction/confidence core — it exists to make
that core touchable: a review queue ordered by priority, a lead detail view with
per-field confidence/evidence/alternatives, a correction endpoint, a dashboard
with the auto-commit rate and a rough ROI, and a threshold endpoint that
re-runs `apply_policy` across the stored leads so a reviewer can watch the queue
grow and shrink as the sliders move.

`create_app()` is a factory so tests can inject an in-memory store. Endpoints
that run the pipeline (`/seed`, `/simulate-inbox`) replay from the committed
cache, so the whole API runs offline once the cache is recorded.
"""

from __future__ import annotations

import pathlib
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from sqlalchemy import Engine

from . import schema, store
from .llm import LLM
from .pipeline import apply_corrections
from .run_corpus import DEMO_RECEIVED, ingest_lead
from .schema import Correction, ReviewStatus, apply_policy

# Rough demo ROI: a reviewer spends about this long eyeballing one field.
_SECONDS_PER_FIELD = 8.0

# The original thresholds, so a threshold reset can restore them.
_BASELINE_THRESHOLDS = dict(schema.THRESHOLDS)


def create_app(
    *,
    engine: Engine | None = None,
    corpus_dir: str | pathlib.Path = "./corpus",
    llm_factory=None,
) -> FastAPI:
    engine = engine or store.init_db()
    corpus_dir = pathlib.Path(corpus_dir)
    llm_factory = llm_factory or (lambda: LLM())

    app = FastAPI(title="Furniture lead intake", version="0.1.0")

    # ---- health -----------------------------------------------------------
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # ---- ingest (the "simulate inbox" affordance) -------------------------
    @app.post("/simulate-inbox")
    def simulate_inbox(lead_id: str = Body(..., embed=True)) -> dict:
        """Run one corpus lead through the pipeline and persist it — the demo's
        stand-in for a real IMAP ingest."""
        entry = _corpus_lead(corpus_dir, lead_id)
        if entry is None:
            raise HTTPException(404, f"no corpus lead {lead_id!r}")
        lead = _run(entry, corpus_dir, llm_factory)
        store.save_lead(engine, lead)
        return _summary_dict(store.list_leads(engine, status=None), lead_id)

    @app.post("/seed")
    def seed() -> dict:
        """Run the whole corpus into the store (idempotent upsert)."""
        import json
        manifest = json.loads((corpus_dir / "manifest.json").read_text())
        loaded, skipped = 0, []
        for entry in manifest["leads"]:
            try:
                lead = _run(entry, corpus_dir, llm_factory)
            except Exception:  # uncached in replay mode -> skip, don't 500 the seed
                skipped.append(entry["lead_id"])
                continue
            store.save_lead(engine, lead)
            loaded += 1
        return {"loaded": loaded, "skipped": skipped}

    # ---- review queue -----------------------------------------------------
    @app.get("/leads")
    def leads(status: str | None = None, order_by_priority: bool = True) -> list[dict]:
        return [s.model_dump() for s in
                store.list_leads(engine, status=status, order_by_priority=order_by_priority)]

    @app.get("/leads/{lead_id}")
    def lead_detail(lead_id: str) -> dict:
        lead = store.get_lead(engine, lead_id)
        if lead is None:
            raise HTTPException(404, f"no lead {lead_id!r}")
        return lead.model_dump(mode="json")

    @app.post("/leads/{lead_id}/review")
    def review(lead_id: str, payload: dict = Body(default_factory=dict)) -> dict:
        """Apply a reviewer's corrections/confirmations and persist."""
        lead = store.get_lead(engine, lead_id)
        if lead is None:
            raise HTTPException(404, f"no lead {lead_id!r}")
        decisions = payload.get("decisions", [])
        applied = apply_corrections(lead, decisions)
        store.save_lead(engine, lead)
        for c in applied:
            store.record_correction(engine, lead_id, c)
        return {
            "lead_id": lead_id,
            "status": lead.review.status.value,
            "corrections": len(applied),
            "flagged_remaining": len(lead.review.flagged_paths),
        }

    # ---- dashboard --------------------------------------------------------
    @app.get("/dashboard")
    def dashboard() -> dict:
        summaries = store.list_leads(engine, status=None)
        leads = [store.get_lead(engine, s.lead_id) for s in summaries]
        return _dashboard([l for l in leads if l is not None])

    # ---- threshold sliders ------------------------------------------------
    @app.get("/thresholds")
    def get_thresholds() -> dict:
        return dict(schema.THRESHOLDS)

    @app.put("/thresholds")
    def put_thresholds(payload: dict = Body(default_factory=dict)) -> dict:
        """Override thresholds (or reset) and re-run apply_policy across every
        stored lead. This is the tunable-queue demo: move a slider, watch the
        review queue resize."""
        before = _queue_size(engine)
        if payload.get("reset"):
            schema.THRESHOLDS.clear()
            schema.THRESHOLDS.update(_BASELINE_THRESHOLDS)
        for path, value in (payload.get("overrides") or {}).items():
            schema.THRESHOLDS[path] = schema.Confidence(str(value).lower())
        _repolicy_all(engine)
        return {
            "thresholds": dict(schema.THRESHOLDS),
            "review_queue_before": before,
            "review_queue_after": _queue_size(engine),
        }

    return app


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _corpus_lead(corpus_dir: pathlib.Path, lead_id: str) -> dict | None:
    import json
    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    return next((l for l in manifest["leads"] if l["lead_id"] == lead_id), None)


def _run(entry: dict, corpus_dir: pathlib.Path, llm_factory):
    from .pipeline import run_lead
    artifacts = ingest_lead(entry, corpus_dir / "inbox")
    return run_lead(artifacts, lead_id=entry["lead_id"],
                    received_at=DEMO_RECEIVED, llm=llm_factory())


def _summary_dict(summaries, lead_id: str) -> dict:
    return next((s.model_dump() for s in summaries if s.lead_id == lead_id), {"lead_id": lead_id})


def _queue_size(engine: Engine) -> int:
    return sum(1 for s in store.list_leads(engine, status=None) if s.flagged_count > 0)


def _repolicy_all(engine: Engine) -> None:
    for summ in store.list_leads(engine, status=None):
        lead = store.get_lead(engine, summ.lead_id)
        if lead is not None:
            apply_policy(lead)
            store.save_lead(engine, lead)


def _dashboard(leads: list) -> dict:
    """Aggregate the queue and a rough ROI from real per-lead metrics.

    Without the system a reviewer touches every field of every lead; with it,
    only the flagged ones. Time saved is the auto-committed field count valued at
    _SECONDS_PER_FIELD each — the whole per-field-confidence pitch, quantified.
    """
    total = len(leads)
    genuine = [l for l in leads if l.is_lead.value is True]
    fields_total = sum(l.metrics.fields_total for l in leads)
    committed = sum(l.metrics.fields_auto_committed for l in leads)
    flagged = sum(len(l.review.flagged_paths) for l in leads)
    review_queue = sum(1 for l in leads if l.review.flagged_paths)

    return {
        "total_leads": total,
        "genuine_leads": len(genuine),
        "not_leads": total - len(genuine),
        "review_queue": review_queue,
        "fields_total": fields_total,
        "fields_auto_committed": committed,
        "fields_flagged": flagged,
        "auto_commit_rate": round(committed / fields_total, 3) if fields_total else 0.0,
        "cost_usd": round(sum(l.metrics.cost_usd for l in leads), 4),
        "model_calls": sum(l.metrics.model_calls for l in leads),
        "reviewer_minutes_saved_estimate": round(committed * _SECONDS_PER_FIELD / 60.0, 1),
    }
