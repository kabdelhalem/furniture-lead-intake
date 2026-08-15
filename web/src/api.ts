import type {
  CanonicalLead,
  Dashboard,
  LeadSummary,
  ReviewDecision,
  ReviewResult,
  SeedResult,
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

  thresholds: () => request<Record<string, number>>("/thresholds"),

  putThresholds: (payload: { overrides?: Record<string, number> } | { reset: true }) =>
    request<ThresholdResult>("/thresholds", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
};

// The corpus lead ids (from src/corpus/specs.py). The manifest isn't exposed
// over HTTP, so the "simulate inbox" control offers these directly.
export const CORPUS_LEAD_IDS = [
  "L001", "L002", "L003", "L004", "L005", "L006", "L007", "L008",
  "L009", "L010", "L011", "L012", "L013", "L014", "L015",
] as const;
