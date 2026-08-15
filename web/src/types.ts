// Shapes mirror the FastAPI responses in `src/api.py` and the Pydantic models in
// `src/schema.py`. Enums serialize as plain strings (model_dump(mode="json"));
// dates/datetimes as ISO strings. Every nested object uses a default factory on
// the backend, so it is always present — only an envelope's `value` is nullable,
// and the list fields may be empty.

export type FieldStatus =
  | "auto_committed"
  | "needs_review"
  | "human_corrected"
  | "human_confirmed"
  | "not_found";

export interface Evidence {
  artifact_id: string;
  locator: string | null;
  snippet: string | null;
}

// The confidence envelope wrapping every extracted leaf value.
export interface Extracted<T = unknown> {
  value: T | null;
  confidence: number; // 0..1
  status: FieldStatus;
  extractor: string | null;
  note: string | null;
  alternatives: unknown[];
  evidence: Evidence[];
}

export interface Contact {
  full_name: Extracted<string>;
  email: Extracted<string>;
  phone: Extracted<string>;
  title: Extracted<string>;
  is_decision_maker: Extracted<boolean>;
}

export interface Customer {
  company_name: Extracted<string>;
  customer_type: Extracted<string>;
  primary_contact: Contact;
  additional_contacts: Contact[];
  billing_city: Extracted<string>;
  billing_state: Extracted<string>;
  existing_account_id: Extracted<string>;
}

export interface ProjectContext {
  project_name: Extracted<string>;
  site_city: Extracted<string>;
  site_state: Extracted<string>;
  requested_delivery: Extracted<string>;
  quote_deadline: Extracted<string>;
  budget_low: Extracted<number>;
  budget_high: Extracted<number>;
  install_required: Extracted<boolean>;
}

export interface Dimensions {
  width_in: Extracted<number>;
  depth_in: Extracted<number>;
  height_in: Extracted<number>;
  source_units: Extracted<string>;
}

export interface LineItem {
  raw_description: string;
  matched_sku: Extracted<string>;
  product_category: Extracted<string>;
  quantity: Extracted<number>;
  dimensions: Dimensions;
  material: Extracted<string>;
  finish: Extracted<string>;
  com_fabric: Extracted<string>;
  options: Extracted<string[]>;
  target_unit_price: Extracted<number>;
}

export interface SourceArtifact {
  artifact_id: string;
  kind: string;
  filename: string;
  sha256: string | null;
  bytes: number;
  page_count: number | null;
  ocr_applied: boolean;
}

export interface Routing {
  assigned_rep: string | null;
  territory: string | null;
  segment: "smb" | "mid_market" | "enterprise" | "unclassified";
  priority_score: number;
  rules_fired: string[];
  routed_at: string | null;
}

export interface Correction {
  field_path: string;
  old_value: unknown;
  new_value: unknown;
  old_confidence: number;
  reviewer: string;
  corrected_at: string | null;
  reason_code: string | null;
}

export interface ReviewState {
  status: string;
  flagged_paths: string[];
  reviewer: string | null;
  review_seconds: number | null;
  corrections: Correction[];
  duplicate_of: string | null;
}

export interface Metrics {
  extraction_ms: number;
  total_tokens: number;
  cost_usd: number;
  model_calls: number;
  fields_total: number;
  fields_auto_committed: number;
}

export interface CanonicalLead {
  lead_id: string;
  received_at: string;
  channel: Extracted<string>;
  is_lead: Extracted<boolean>;
  source_artifacts: SourceArtifact[];
  customer: Customer;
  project: ProjectContext;
  line_items: LineItem[];
  routing: Routing;
  review: ReviewState;
  metrics: Metrics;
}

export interface LeadSummary {
  lead_id: string;
  received_at: string;
  is_lead: boolean;
  company_name: string | null;
  segment: string;
  priority_score: number;
  review_status: string;
  auto_commit_rate: number;
  flagged_count: number;
  cost_usd: number;
  model_calls: number;
}

export interface Dashboard {
  total_leads: number;
  genuine_leads: number;
  not_leads: number;
  review_queue: number;
  fields_total: number;
  fields_auto_committed: number;
  fields_flagged: number;
  auto_commit_rate: number;
  cost_usd: number;
  model_calls: number;
  reviewer_minutes_saved_estimate: number;
}

export interface SeedResult {
  loaded: number;
  skipped: string[];
}

export interface ReviewResult {
  lead_id: string;
  status: string;
  corrections: number;
  flagged_remaining: number;
}

export interface ThresholdResult {
  thresholds: Record<string, number>;
  review_queue_before: number;
  review_queue_after: number;
}

export interface ReviewDecision {
  field_path: string;
  new_value?: unknown;
  reviewer?: string;
  reason_code?: string;
}
