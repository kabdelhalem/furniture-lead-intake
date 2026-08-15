# CLAUDE.md

## What this is

A working reference implementation of an inbound-lead intake pipeline for a
furniture manufacturer. The customer problem: inbound leads arrive as
unstructured email, PDFs, scanned faxes, spreadsheets, CAD files, and phone
calls, and reps hand-parse each one into a quote.

The thesis of the build: **heterogeneous inbound collapses into one canonical
shape, and every field in that shape carries its own confidence.** Per-field
confidence is what makes human review cheap — a reviewer touches the ~15% of
fields the system is unsure about, not the whole record.

The design bias is depth in the extraction and confidence layer; everything
around it (API, persistence, UI) is scaffolding that exists to exercise that
layer, not to be a product.

## Invariants — do not violate without asking

**The schema in `src/schema.py` is the contract.** Field paths are shared by the
pipeline, the eval harness, and the UI. Adding an optional field is fine.
Renaming or restructuring anything under `customer.`, `project.`,
`line_items[].` breaks ground truth and eval simultaneously. If you believe a
path must change, stop and say so rather than changing it.

**Ground truth lives in `src/corpus/specs.py`.** It is authored before the
artifacts are rendered, so the labels are correct by construction. The
`corpus/ground_truth/*.json` files are a *build artifact* generated from
`specs.py` — treat `specs.py` as authoritative and regenerate the JSON, never
hand-edit it. If extraction disagrees with ground truth, the extractor is wrong.
If you find a genuine labelling error, flag it and fix it in `specs.py`.

**`apply_policy()` is the only place that decides what a human sees.** Keep it a
pure function of confidence and thresholds. No extractor may set
`FieldStatus.AUTO_COMMITTED` directly.

**Routing is deterministic rules, not a model.** `src/routing.py` uses plain
Python conditionals and logs `rules_fired`. This is a deliberate design
position: routing doesn't need a model, and spending tokens on a lookup table
erodes trust in an AI system's cost profile.

**Never invent a value to fill a field.** If the source doesn't state it, emit
`None`. `L011` exists specifically to catch hallucinated quantities and it is a
hard eval failure, not a soft one.

## Stack

- Python 3.11+ (developed and tested on 3.14), Pydantic v2, FastAPI
- **Claude** for the model calls, via the Anthropic SDK. Tiered: a fast, cheap
  model (Haiku) for per-format extraction, a stronger model only for the
  ambiguity-resolution pass. Log which tier ran per lead.
- All model calls are cached to disk keyed on `(model, prompt)`. The corpus
  eval **replays from that cache**, so `make eval` runs offline and
  reproducibly with no API key. Re-recording is behind an explicit flag.
- LangGraph for the pipeline — justified here because the human-review step is a
  real interrupt/resume, not because it looks impressive.
- SQLite via SQLModel for persistence (Postgres is not worth the setup cost for
  a reference implementation).
- React + Vite + Tailwind for the UI.

## Conventions

- Every model call goes through one wrapper in `src/llm.py` that records tokens,
  cost, latency, and model tier into `PipelineMetrics`. No bare SDK calls.
- Extractors return `Extracted[T]` envelopes with `evidence` populated. A value
  with no evidence is a bug — the UI needs to show the reviewer where it came from.
- Confidence is an ordinal **level** (`Certain > High > Medium > Low > Severe`),
  not a float — models are poorly calibrated at numeric probabilities, and a
  level reads better to a reviewer. The model reports a level; the deterministic
  signals (regex validation, catalog match distance, cross-artifact agreement,
  source hedging) promote or demote it. `SEVERE` is the alarm floor. Thresholds
  are a per-field-class **minimum level** to auto-commit. Don't rely on the
  model's self-reported level alone.
- Run `python -m src.corpus.generate --out ./corpus` after any spec change.
- `make eval` must stay green-ish and fast enough to run constantly.

## Scope boundaries — deliberately out of scope

No auth beyond a hardcoded reviewer identity. No real IMAP ingestion (a
"simulate inbox" button is the demo affordance). No pricing engine beyond the
stub catalog. No DXF geometry parsing — annotation layer only. No
multi-tenancy. No websockets. No Docker. No CI. No cloud infra.

These are cut on purpose to keep the focus on the extraction and confidence
layer. Reach for one only if it directly serves that layer.
