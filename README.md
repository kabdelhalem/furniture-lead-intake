# Furniture lead intake — canonical extraction with per-field confidence

Inbound sales leads for a furniture manufacturer arrive as email, PDFs, scanned
faxes, spreadsheets, CAD files, and phone-call transcripts. Reps hand-parse each
one into a quote. This project collapses all of that heterogeneous inbound into
**one canonical record where every field carries its own confidence and
provenance** — so a human reviewer only touches the fields the system is unsure
about, not the whole record.

## How it works

```
┌─ PHASE 1  Ingest ─────────────────────────────────────────────────────────────┐
│   Inbound artifacts for one lead:                                             │
│     email   pdf   scanned-fax   xlsx   dxf   transcript                       │
│       └───────┴────────┬─────────┴──────┴──────┘                              │
│                        ▼                                                      │
│   ingest ──▶ IngestedArtifact - located blocks ("Sheet1!C14", "body line 7")  │
│              a scanned fax has no text layer ──▶ vision path (bytes to model) │
└───────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼  artifacts for one lead
┌─ PHASE 2  LangGraph pipeline   (src/pipeline.py) ─────────────────────────────┐
│   ┌──────────────┐   reconcile only when 2+ artifacts conflict (L014):        │
│   │   extract    │──▶┌──────────────┐   Claude Sonnet - the pricier tier,     │
│   │ Claude Haiku │   │  reconcile   │   spent only where ambiguity lives      │
│   │ read+locate  │◀──│  conflicts   │                                         │
│   └──────────────┘   └──────────────┘                                         │
│         │  ExtractionResult - each field: value + level (certain..severe)     │
│         ▼                                                                     │
│   ┌────────────────────────────────────────────────────────────────┐          │
│   │ assemble   (deterministic - no model call)                     │          │
│   │   normalize    mm->in / dates / money / phones                 │          │
│   │   match        fuzzy SKU vs 30-SKU catalog (+ alternatives)    │          │
│   │   confidence   model level  +  deterministic signals           │          │
│   │   apply_policy   level >= field-class minimum ?  auto : review │          │
│   └────────────────────────────────────────────────────────────────┘          │
│         │  CanonicalLead                                                      │
│         ▼                                                                     │
│   ┌───────────────────────────────────────────────────────────────────────┐   │
│   │ route    -  rules only:  segment / territory / priority / rules_fired │   │
│   └───────────────────────────────────────────────────────────────────────┘   │
│         │                                                                     │
│         ▼                                                                     │
│   ┌──────────────┐   any flagged fields?                                      │
│   │    review    │──── yes ──▶ interrupt ──▶ human corrects ──▶ resume        │
│   │  interrupt/  │              (LangGraph checkpoint - a durable pause)      │
│   │   resume     │──── none ──▶ auto-committed                                │
│   └──────────────┘                                                            │
└───────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼  a routed, level-scored lead
┌─ PHASE 3  Persist + serve ────────────────────────────────────────────────────┐
│   ┌───────────────────────┐         ┌───────────────────────┐                 │
│   │  Store  (SQLite)      │         │  FastAPI              │                 │
│   │  ─────────────────    │◀───────▶│  ───────────          │                 │
│   │  lead JSON = truth    │         │  /leads       queue   │                 │
│   │  projection columns   │         │  /leads/{id}  detail  │                 │
│   │  corrections          │         │  /dashboard   ROI     │                 │
│   └───────────────────────┘         │  /thresholds  sliders │                 │
│                                     └───────────────────────┘                 │
│                                               │                               │
│                                               ▼                               │
│                                      React review UI                          │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Ingest** (`src/ingest.py`) — every format becomes a uniform `IngestedArtifact`
  with located blocks (`Sheet1!C14`, `body line 7`) so each value can cite where
  it came from. A scanned fax with no text layer takes the vision path.
- **Extract** (`src/extract.py`) — a cheap, fast model *reads and locates* only.
  It copies values verbatim (no unit conversion, no SKU guessing) and rates its
  own certainty. A stronger model runs only to reconcile leads whose evidence
  spans multiple conflicting artifacts.
- **Assemble** (`src/assemble.py`) — the deterministic half: type the values
  (units, dates, phones, money), fuzzy-match SKUs against the catalog, and score
  **per-field confidence** by folding the model's self-report together with
  deterministic signals (`src/confidence.py`).
- **Route** (`src/routing.py`) — plain rules, no model. Every rule that fires is
  logged.
- **Review** — a real LangGraph `interrupt`/`resume`: a lead with flagged fields
  pauses for a reviewer and resumes with their corrections applied.

Every model call goes through one wrapper (`src/llm.py`) that records tokens,
cost, latency, and model tier, and caches responses to disk — so the eval
replays offline with no API key.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
make install          # dependencies
make corpus           # generate the synthetic corpus from specs.py
make test             # 220+ tests, all offline

# Record model responses once (needs ANTHROPIC_API_KEY), then score offline:
make record           # live calls -> writes cache/llm/  (commit it)
make eval             # replays the cache, scores against ground truth
```

`make eval` runs the pipeline over all 15 leads and prints field accuracy, a
calibration pass-rate, the L011/L013 gates, and the run's token/cost total. It
exits non-zero on a gate failure — a real CI-style check once the cache is
recorded.

## Three design decisions worth understanding

**Ground truth is authored first; artifacts are derived from it.** The normal way
a synthetic eval set dies is: generate plausible documents, then hand-label them
— which bakes the same misreadings into the labels that the extractor will make.
Going truth-first (`src/corpus/specs.py`) makes the labels correct by
construction.

**Confidence is an ordinal level, per field — not a float.** The ladder is
**Certain > High > Medium > Low > Severe**. Levels beat numbers here for two
reasons: models are poorly calibrated at emitting probabilities but decent at
coarse buckets, and "High" is more legible to a sales VP than `0.87`. The model
reports a level, and the deterministic signals promote or demote it (SEVERE is
the alarm floor — where an ambiguous SKU, a hallucination risk, or a
cross-artifact conflict lands). Thresholds are a per-field-*class* **minimum
level**: `primary_contact.email` must reach `Certain` (a wrong email is
unrecoverable), while `finish` only needs `Low` (a rep catches it downstream).
Raise a field class's minimum and the review queue grows — tunable, not hardcoded.

**`apply_policy()` is the only place that decides what a human sees.** Keeping it a
pure function of confidence is what lets the review queue stay tunable. Note the
denominator subtlety: absent *optional* fields are excluded from the auto-commit
rate (a field nobody asked for isn't a decision the system made), while absent
*required* fields count and cost a reviewer.

## What the corpus deliberately tests

Each fixture catches one named failure mode (`corpus/manifest.json` has the full
map). The ones that carry the most weight:

| Lead | Failure mode |
|---|---|
| L002 | Forwarded thread, three superseded scopes — naive extraction grabs the dead numbers |
| L003 | Header on row 7 under a merged title, `"14 ea"` quantities, a subtotal row masquerading as a line item |
| L004 | Scanned fax, **no text layer** — `pdfplumber` returns `""`, forcing the vision path |
| L006 | Phone transcript: `"four, maybe five"`, `"ten foot"` → 120in, chairs stated per-table |
| L007 | `"the big walnut one"` maps to 3 SKUs — correct behavior is decline + alternatives, **not** a guess |
| L008 | Metric throughout; 1800mm = 70.87in must not silently snap to the 72" SKU |
| L009 | Sender is an EA; the decision maker is someone else in the body |
| L011 | Quantity stated nowhere — the only correct answer is `null`, any number is a hard fail |
| L013 | Lead-shaped but it's an AP dispute — if this reaches the queue, the classifier gate is broken |
| L014 | Spec PDF says oat, quantity sheet says slate — the conflict must surface, not resolve silently |

L011 and L013 matter most: a system that declines to answer is a stronger signal
than one that answers everything.

## Layout

```
src/
  schema.py       canonical CanonicalLead shape + apply_policy + thresholds
  catalog.py      30-SKU stub catalog with deliberate near-collisions
  ingest.py       6 format loaders -> IngestedArtifact
  llm.py          the one model-call wrapper (tiers, cost, replay cache)
  extract.py      LLM read -> ExtractionResult   (+ extract_types.py contract)
  normalize.py    mm->in, dates, money, phones
  matching.py     fuzzy SKU matcher + per-match confidence
  confidence.py   per-field confidence from model + deterministic signals
  assemble.py     ExtractionResult -> typed, scored CanonicalLead
  routing.py      deterministic rules
  pipeline.py     LangGraph graph with the human-review interrupt/resume
  eval.py         field accuracy + calibration + gates
  run_corpus.py   drive the pipeline over the corpus and score it
  corpus/         ground-truth-first fixtures (specs.py) + renderers
```

## Scope boundaries — deliberately out of scope

No real IMAP (a "simulate inbox" button is the demo affordance). No pricing engine
beyond the stub catalog. No DXF geometry parsing — annotation layer only. No
multi-tenancy, no auth beyond a hardcoded reviewer. These are cut on purpose to
keep the focus on the extraction and confidence layer.
