"""
Run the pipeline over the whole corpus and score it against ground truth.

    python -m src.run_corpus --corpus ./corpus            # replay from cache (offline)
    LLM_MODE=record python -m src.run_corpus --record     # record live, needs a key

This is what `make eval` and `make record` call. In replay mode a lead whose
model response isn't cached is skipped and reported as a *missing prediction*
rather than crashing the run, so a partial cache still produces a partial
report and a fresh clone prints clear "record first" guidance instead of a
stack trace.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime

from .eval import evaluate
from .eval import _print_report  # noqa: PLC2701 — internal formatter, reused intentionally
from .ingest import ingest_file
from .llm import LLM, LLMCacheMiss, PipelineMetrics
from .pipeline import run_lead
from .schema import CanonicalLead

# All corpus dates ("October 15", "Sept 30") resolve against the demo date.
DEMO_RECEIVED = datetime(2026, 8, 14, 9, 0)

# Field accuracy below this, with predictions present, fails `make eval`.
ACCURACY_FLOOR = 0.85


def ingest_lead(lead_entry: dict, inbox: pathlib.Path):
    """Ingest one manifest lead's artifacts (email first, attachments after)."""
    ordered = sorted(lead_entry["artifacts"], key=lambda a: a["kind"] != "email")
    return [ingest_file(inbox / a["filename"], a["kind"], a["artifact_id"]) for a in ordered]


def run_corpus(
    corpus_dir: pathlib.Path, llm_factory=None
) -> tuple[dict[str, CanonicalLead], list[str], PipelineMetrics]:
    """Run every lead through the pipeline.

    Returns (predicted, uncached_lead_ids, totals). `llm_factory()` makes a fresh
    LLM per lead (fresh metrics); defaults to one that reads LLM_MODE from the
    environment. Totals aggregate cost/tokens/calls across the corpus.
    """
    llm_factory = llm_factory or (lambda: LLM())
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    inbox = corpus_dir / "inbox"

    predicted: dict[str, CanonicalLead] = {}
    uncached: list[str] = []
    totals = PipelineMetrics()

    for entry in manifest["leads"]:
        lead_id = entry["lead_id"]
        artifacts = ingest_lead(entry, inbox)
        llm = llm_factory()
        try:
            lead = run_lead(artifacts, lead_id=lead_id, received_at=DEMO_RECEIVED, llm=llm)
        except LLMCacheMiss:
            uncached.append(lead_id)
            continue
        predicted[lead_id] = lead
        totals.total_tokens += llm.metrics.total_tokens
        totals.cost_usd = round(totals.cost_usd + llm.metrics.cost_usd, 6)
        totals.model_calls += llm.metrics.model_calls

    return predicted, uncached, totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="./corpus", type=pathlib.Path)
    ap.add_argument("--record", action="store_true",
                    help="record mode: make live calls and write the cache (needs a key)")
    args = ap.parse_args(argv)

    if args.record:
        import os
        os.environ["LLM_MODE"] = "record"

    if not (args.corpus / "manifest.json").exists():
        print(f"no corpus at {args.corpus} — run `python -m src.corpus.generate --out {args.corpus}`")
        return 2

    predicted, uncached, totals = run_corpus(args.corpus)

    if not predicted:
        print("No cached model responses found — nothing to score.\n"
              "Record them once with a live key:\n"
              "    LLM_MODE=record python -m src.run_corpus --record\n"
              "then re-run `make eval` (which replays from cache, offline).")
        return 0

    report = evaluate(predicted, args.corpus)
    _print_report(report)
    print(f"\ncost {totals.model_calls} calls · {totals.total_tokens} tokens · "
          f"${totals.cost_usd:.4f}")
    if uncached:
        print(f"uncached (skipped): {', '.join(uncached)} — run `make record` to fill them")

    failed = bool(report.gates_failed) or report.field_accuracy < ACCURACY_FLOOR
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
