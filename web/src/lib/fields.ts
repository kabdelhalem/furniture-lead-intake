import type {
  CanonicalLead,
  ConfidenceLevel,
  Contact,
  Extracted,
  FieldStatus,
} from "../types";

// A flattened, display-ready field: the envelope plus everything the row and the
// confidence rail need. `path` matches the backend's iter_extracted format
// exactly (dotted, bracketed indices) so it round-trips through flagged_paths,
// threshold_for, and the review endpoint.
export type FieldKind = "number" | "bool" | "text";

export interface FieldRow {
  path: string;
  label: string;
  field: Extracted;
  threshold: ConfidenceLevel;
  kind: FieldKind;
}

// The editor type has to come from the path, not the current value: a flagged
// field is often null (e.g. L011's quantity, stated nowhere), and Pydantic v2
// doesn't validate on assignment — so a correction typed as a string would stick
// a "5" into an Extracted[int]. The reviewable set is small and closed.
const NUMBER_SUFFIXES = [
  ".quantity",
  ".width_in",
  ".depth_in",
  ".height_in",
  ".budget_low",
  ".budget_high",
  ".target_unit_price",
];
const BOOL_PATHS = ["is_lead"];
const BOOL_SUFFIXES = [".is_decision_maker", ".install_required"];

function kindFor(path: string): FieldKind {
  if (BOOL_PATHS.includes(path) || BOOL_SUFFIXES.some((s) => path.endsWith(s))) return "bool";
  if (NUMBER_SUFFIXES.some((s) => path.endsWith(s))) return "number";
  return "text";
}

export interface FieldGroup {
  key: string;
  title: string;
  rows: FieldRow[];
}

// Mirror of schema.threshold_for: collapse [3] -> [] then fall back to _default.
// The tick on the confidence rail depends on this being the same transform, or
// every line-item field would show the default level instead of its real class.
export function thresholdFor(
  path: string,
  thresholds: Record<string, ConfidenceLevel>,
): ConfidenceLevel {
  const generic = path.replace(/\[\d+\]/g, "[]");
  return thresholds[generic] ?? thresholds["_default"] ?? "high";
}

function row(
  path: string,
  label: string,
  field: Extracted,
  thresholds: Record<string, ConfidenceLevel>,
): FieldRow {
  return { path, label, field, threshold: thresholdFor(path, thresholds), kind: kindFor(path) };
}

function contactRows(
  prefix: string,
  c: Contact,
  thresholds: Record<string, ConfidenceLevel>,
): FieldRow[] {
  return [
    row(`${prefix}.full_name`, "Contact name", c.full_name, thresholds),
    row(`${prefix}.email`, "Email", c.email, thresholds),
    row(`${prefix}.phone`, "Phone", c.phone, thresholds),
    row(`${prefix}.title`, "Title", c.title, thresholds),
    row(`${prefix}.is_decision_maker`, "Decision maker", c.is_decision_maker, thresholds),
  ];
}

/** Non-line-item groups, in reading order. */
export function coreGroups(
  lead: CanonicalLead,
  thresholds: Record<string, ConfidenceLevel>,
): FieldGroup[] {
  const t = thresholds;
  const c = lead.customer;
  const p = lead.project;
  return [
    {
      key: "classification",
      title: "Classification",
      rows: [
        row("is_lead", "Is a genuine lead", lead.is_lead, t),
        row("channel", "Channel", lead.channel, t),
      ],
    },
    {
      key: "customer",
      title: "Customer",
      rows: [
        row("customer.company_name", "Company", c.company_name, t),
        row("customer.customer_type", "Customer type", c.customer_type, t),
        ...contactRows("customer.primary_contact", c.primary_contact, t),
        row("customer.billing_city", "Billing city", c.billing_city, t),
        row("customer.billing_state", "Billing state", c.billing_state, t),
        row("customer.existing_account_id", "Account ID", c.existing_account_id, t),
      ],
    },
    {
      key: "project",
      title: "Project",
      rows: [
        row("project.project_name", "Project name", p.project_name, t),
        row("project.site_city", "Site city", p.site_city, t),
        row("project.site_state", "Site state", p.site_state, t),
        row("project.requested_delivery", "Requested delivery", p.requested_delivery, t),
        row("project.quote_deadline", "Quote deadline", p.quote_deadline, t),
        row("project.budget_low", "Budget (low)", p.budget_low, t),
        row("project.budget_high", "Budget (high)", p.budget_high, t),
        row("project.install_required", "Install required", p.install_required, t),
      ],
    },
  ];
}

/** The fields inside one line item, in reading order. */
export function lineItemRows(
  lead: CanonicalLead,
  index: number,
  thresholds: Record<string, ConfidenceLevel>,
): FieldRow[] {
  const li = lead.line_items[index];
  const base = `line_items[${index}]`;
  const t = thresholds;
  const d = li.dimensions;
  return [
    row(`${base}.matched_sku`, "Matched SKU", li.matched_sku, t),
    row(`${base}.product_category`, "Category", li.product_category, t),
    row(`${base}.quantity`, "Quantity", li.quantity, t),
    row(`${base}.dimensions.width_in`, "Width (in)", d.width_in, t),
    row(`${base}.dimensions.depth_in`, "Depth (in)", d.depth_in, t),
    row(`${base}.dimensions.height_in`, "Height (in)", d.height_in, t),
    row(`${base}.dimensions.source_units`, "Source units", d.source_units, t),
    row(`${base}.material`, "Material", li.material, t),
    row(`${base}.finish`, "Finish", li.finish, t),
    row(`${base}.com_fabric`, "COM fabric", li.com_fabric, t),
    row(`${base}.options`, "Options", li.options, t),
    row(`${base}.target_unit_price`, "Target unit price", li.target_unit_price, t),
  ];
}

// ---- status presentation --------------------------------------------------
// Every status pairs a hue with a glyph and a word, so the confidence channel
// reads without relying on color (accessibility, and honesty about the state).

export interface StatusMeta {
  label: string;
  glyph: string;
  // Tailwind color families used across dot / text / fill.
  tone: "commit" | "review" | "muted" | "human";
}

const STATUS: Record<FieldStatus, StatusMeta> = {
  auto_committed: { label: "Auto-committed", glyph: "●", tone: "commit" },
  needs_review: { label: "Needs review", glyph: "▲", tone: "review" },
  not_found: { label: "Not found", glyph: "○", tone: "muted" },
  human_corrected: { label: "Corrected", glyph: "✎", tone: "human" },
  human_confirmed: { label: "Confirmed", glyph: "✓", tone: "human" },
};

export function statusMeta(status: FieldStatus): StatusMeta {
  return STATUS[status];
}

export function isHumanTouched(status: FieldStatus): boolean {
  return status === "human_corrected" || status === "human_confirmed";
}
