// Turn envelope values into reviewer-facing text. Kept dumb and defensive: the
// backend copies values verbatim, so we may see strings, numbers, booleans,
// ISO dates, or arrays here.

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "number") return String(value);
  return String(value);
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value < 100 ? 2 : 0,
  });
}

export function formatPct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

// e.g. "2026-08-14T09:00:00" -> "Aug 14, 2026 · 9:00 AM"
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// A date-only ISO string ("2026-09-30") shown without a phantom timezone shift.
export function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }
  return iso;
}

export function relativeReceived(iso: string): string {
  return formatDateTime(iso);
}

const SEGMENT_LABEL: Record<string, string> = {
  smb: "SMB",
  mid_market: "Mid-market",
  enterprise: "Enterprise",
  unclassified: "Unclassified",
};

export function segmentLabel(segment: string): string {
  return SEGMENT_LABEL[segment] ?? segment;
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  in_review: "In review",
  approved: "Approved",
  rejected: "Not a lead",
  duplicate: "Duplicate",
};

export function reviewStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

// Prettify an artifact kind / territory / reason enum: "email_body" -> "Email body".
export function humanize(token: string | null | undefined): string {
  if (!token) return "—";
  return token
    .replace(/_/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

// Split a field path into a readable trail: "customer.primary_contact.email"
// -> "customer › primary contact › email".
export function prettyPath(path: string): string {
  return path
    .replace(/\[(\d+)\]/g, " $1")
    .split(".")
    .map((seg) => seg.replace(/_/g, " ").trim())
    .join(" › ");
}
