# Review Bench — the UI

A single-page review console for the lead-intake pipeline. It makes the one idea
the pipeline is built around visible: **every field carries its own confidence,
and a reviewer only touches the fields that fall below their threshold.**

Four views:

- **Queue** — inbound leads, highest priority first. Flagged leads carry an amber
  edge; each row shows segment, priority, auto-commit rate, and review status.
  Seed the demo corpus or simulate a single inbound from the toolbar.
- **Lead detail** — the canonical record, every field colored by status and
  plotted on a confidence rail against the threshold for its class. Flagged
  fields surface first under **Needs your eye**; expand any field for its
  evidence ("show me why"), and confirm or correct it inline. A flagged SKU
  offers its runner-up matches as a picker.
- **Dashboard** — the auto-commit rate as the hero, reviewer time saved as the
  ROI, plus cost, queue size, and the leads-vs-not-leads split.
- **Thresholds** — sliders for the field classes that move the queue. Each change
  re-runs the policy server-side and the queue count resizes live.

## Run it

The Python backend must be running and seeded first (from the repo root):

```bash
make serve          # uvicorn on :8000
# then, once it's up, seed the corpus (or use the "Seed corpus" button in the UI):
curl -X POST localhost:8000/seed
```

Then, in this directory:

```bash
npm install
npm run dev         # Vite dev server on :5173
```

Open http://localhost:5173. The app calls the backend through a dev proxy
(`/api/*` → `http://localhost:8000`), so there's a single origin in the browser
and no CORS setup.

> The backend replays model calls from a committed cache, so it runs offline with
> no API key. The one exception is the scanned-fax lead (L004), whose vision path
> isn't cached — `POST /seed` reports it under `skipped`, and the UI surfaces
> that rather than failing.

## Build

```bash
npm run build       # tsc -b && vite build
npm run preview     # serve the production build
```

## Stack

React 18 · TypeScript · Vite · Tailwind CSS · TanStack Query · React Router.
Type shapes in `src/types.ts` mirror the FastAPI responses; the field-path logic
in `src/lib/fields.ts` mirrors `src/schema.py` (traversal order and
`threshold_for`) so paths round-trip through the review and threshold endpoints.
