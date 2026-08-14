# Furniture lead intake — canonical extraction with per-field confidence

Inbound sales leads for a furniture manufacturer arrive as email, PDFs, scanned
faxes, spreadsheets, CAD files, and phone-call transcripts. Reps hand-parse each
one into a quote. This project collapses all of that heterogeneous inbound into
**one canonical record where every field carries its own confidence and
provenance** — so a human reviewer only touches the fields the system is unsure
about, not the whole record.

This repo is the foundation layer: the frozen schema and a synthetic,
ground-truth-first corpus that the extraction pipeline and eval harness are
built against.

1. **`src/schema.py`** — the canonical lead shape. Every field is an
   `Extracted[T]` envelope carrying a value, a confidence, provenance
   (`evidence`), and a review status.
2. **`src/corpus/`** — 15 ground-truth-first lead fixtures that render into 20
   messy artifacts across 6 formats.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.corpus.generate --out ./corpus
```

Output:

```
corpus/inbox/          20 artifacts — .eml, .pdf (text + scanned), .xlsx, .dxf, .txt
corpus/ground_truth/   15 JSON files, dotted-path -> expected value
corpus/manifest.json   index + failure-mode coverage map
```

Current: **15 leads · 20 artifacts · 242 labelled fields · 11 expected-uncertain fields**.

> `corpus/` is generated and git-ignored. `src/corpus/specs.py` is the source of
> truth; regenerate the artifacts rather than hand-editing anything under
> `corpus/`. Developed on Python 3.14; the schema targets 3.11+.

## Three design decisions worth understanding

**Ground truth is authored first; artifacts are derived from it.** The normal way
a synthetic eval set dies is: generate plausible documents, then hand-label them
— which bakes the same misreadings into the labels that the extractor will make.
Going truth-first makes the labels correct by construction. It's the single most
important property of the corpus.

**Confidence is per-field, and thresholds are per field *class*.** Getting a
contact email wrong is unrecoverable — the quote goes to the wrong inbox. Getting
a finish wrong is caught downstream by the rep. So `primary_contact.email` sits at
0.95 and `finish` sits at 0.65. See `THRESHOLDS` in `schema.py`. Moving a
threshold grows or shrinks the review queue — the queue is tunable, not
hardcoded.

**`apply_policy()` is the only place that decides what a human sees.** Keeping it
a pure function of confidence is what lets the review queue stay tunable rather
than hardcoded.

Note the denominator subtlety in `apply_policy`: absent *optional* fields are
excluded from the auto-commit rate, because a field nobody asked for isn't a
decision the system made. Absent *required* fields do count, and do cost a
reviewer. Left naive, this metric reads 16% instead of 78% and understates the
system.

## What the corpus deliberately tests

Every fixture exists to catch one named failure mode; `manifest.json` has the
full map. The ones that carry the most weight:

| Lead | Failure mode |
|---|---|
| L002 | Forwarded thread, three superseded scopes — naive extraction grabs the dead numbers |
| L003 | Header on row 7 under a merged title, `"14 ea"` quantities, a subtotal row masquerading as a line item |
| L004 | Scanned fax, **no text layer** — `pdfplumber` returns `""`, forcing the OCR branch |
| L006 | Phone transcript: `"four, maybe five"`, `"ten foot"` → 120in, chairs stated per-table |
| L007 | `"the big walnut one"` maps to 3 SKUs — correct behavior is flag + alternatives, **not** a guess |
| L008 | Metric throughout; 1800mm = 70.87in must not silently snap to the 72" SKU |
| L009 | Sender is an EA; the decision maker is someone else in the body |
| L011 | Quantity stated nowhere — the only correct answer is `null`, any number is a hard fail |
| L013 | Lead-shaped but it's an AP dispute — if this reaches the queue, the classifier gate is broken |
| L014 | Spec PDF says oat, quantity sheet says slate — the conflict must surface, not resolve silently |

L011 and L013 matter most: a system that declines to answer is a stronger signal
than one that answers everything.

## What this deliberately does not do

- **No DXF geometry parsing.** Text and DIMENSION entities only. Fabricators put
  the numbers in the annotation layer; chasing geometry is a lot of work for
  marginal recall.
- **No real IMAP.** The demo gets a "simulate inbox" button.
- **No pricing engine.** 30-SKU stub catalog in `src/catalog.py`, with deliberate
  near-collisions (`MER-CT-96` / `MER-CT-120`, the `ASH-TSK-*` family) so fuzzy
  matching produces genuinely low-confidence results rather than manufactured ones.

## Architecture

The schema is the contract. Three tracks build on it:

1. **Extraction** — classifier → per-format extractors → normalizer → SKU matcher → confidence scorer, orchestrated as a LangGraph pipeline with a real human-review interrupt/resume.
2. **Eval** — flatten predicted vs. truth via `flatten_values()`, field-level accuracy plus a calibration check against `expect_low_confidence`.
3. **UI** — review queue driven by `review.flagged_paths`, dashboard, ROI panel.

All model calls run through one wrapper (`src/llm.py`) that records tokens, cost,
latency, and model tier, and caches responses to disk so the eval replays
offline with no API key.
