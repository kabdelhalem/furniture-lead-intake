import type {
  Calibration,
  CanonicalLead,
  ConfidenceLevel,
  Dashboard,
  LeadSummary,
  Observability,
  ReviewDecision,
  IngestRawResult,
  ReviewResult,
  SeedResult,
  SourceDoc,
  ThresholdResult,
} from "./types";

// Everything routes through the Vite proxy: /api/* -> http://localhost:8000/*.
const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    // Network-level failure: the dev server can reach the browser but not :8000.
    throw new ApiError("Can't reach the backend. Is `make serve` running?", 0);
  }
  if (!res.ok) {
    // FastAPI puts the useful text in `detail`; fall back to the status line.
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body — keep the status text */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  seed: () => request<SeedResult>("/seed", { method: "POST" }),

  simulateInbox: (lead_id: string) =>
    request<LeadSummary>("/simulate-inbox", {
      method: "POST",
      body: JSON.stringify({ lead_id }),
    }),

  leads: (opts?: { status?: string; orderByPriority?: boolean }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set("status", opts.status);
    q.set("order_by_priority", String(opts?.orderByPriority ?? true));
    return request<LeadSummary[]>(`/leads?${q.toString()}`);
  },

  lead: (id: string) => request<CanonicalLead>(`/leads/${id}`),

  review: (id: string, decisions: ReviewDecision[]) =>
    request<ReviewResult>(`/leads/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ decisions }),
    }),

  dashboard: () => request<Dashboard>("/dashboard"),

  // Offline reliability: per-level accuracy vs ground truth. Replays the whole
  // curated corpus server-side, so it's a few seconds, not instant.
  calibration: () => request<Calibration>("/calibration"),

  // The ingested view of a lead's artifacts: parsed text + located blocks.
  source: (id: string) => request<SourceDoc[]>(`/leads/${id}/source`),

  // Live extraction of arbitrary pasted text or an uploaded file (base64). Real
  // model call — takes a few seconds and needs ANTHROPIC_API_KEY on the server.
  ingestRaw: (payload: { text?: string; content_b64?: string; filename?: string }) =>
    request<IngestRawResult>("/ingest-raw", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Per-field-class calibration signal from real review outcomes: which
  // confidence thresholds to tighten (we auto-committed something wrong) or
  // loosen (we flagged something that was fine). Empty until a reviewer acts.
  observability: () => request<Observability>("/observability"),

  thresholds: () => request<Record<string, ConfidenceLevel>>("/thresholds"),

  putThresholds: (
    payload: { overrides?: Record<string, ConfidenceLevel> } | { reset: true },
  ) =>
    request<ThresholdResult>("/thresholds", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};

// URL for the raw original artifact bytes (the ingested email/PDF/xlsx/…),
// served with a real content-type for <iframe> embed / download. The artifact_id
// looks like "L007::L007.eml" and must be percent-encoded in the path.
export function artifactRawUrl(artifactId: string): string {
  return `${BASE}/artifacts/${encodeURIComponent(artifactId)}/raw`;
}

// The corpus lead ids (from src/corpus/specs.py). The manifest isn't exposed
// over HTTP, so the "simulate inbox" control offers these directly.
export const CORPUS_LEAD_IDS = [
  "L001", "L002", "L003", "L004", "L005", "L006", "L007", "L008",
  "L009", "L010", "L011", "L012", "L013", "L014", "L015",
] as const;
