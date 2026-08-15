import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { CanonicalLead, Extracted, ReviewDecision } from "../types";
import type { FieldRow as FieldRowT } from "../lib/fields";
import { coreGroups, lineItemRows } from "../lib/fields";
import { formatDate, formatMoney, formatValue, humanize, relativeReceived, segmentLabel } from "../lib/format";
import CorrectionForm, { skuAlternatives } from "./CorrectionForm";

// Sales-facing names for a few fields whose engineering labels read wrong to a
// salesperson. Everything else falls back to the row's own label.
const SALES_LABEL: Record<string, string> = {
  is_lead: "Genuine inquiry",
  channel: "Came in by",
  "customer.company_name": "Company",
  "customer.customer_type": "Customer type",
  "line_items[].matched_sku": "Catalog product",
  "line_items[].quantity": "Quantity",
  "line_items[].target_unit_price": "Target price",
};

function salesLabel(path: string): string | undefined {
  return SALES_LABEL[path.replace(/\[\d+\]/g, "[]")];
}

function hasValue(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

// Plain-language prompt derived from the SHAPE of the problem, not the path — so
// it keeps working when the eval changes which fields flag.
function reviewPrompt(row: FieldRowT): string {
  const present = hasValue(row.field.value);
  if (!present) return "The source didn't state this — add it if you know it.";
  if (skuAlternatives(row).length > 0) return "A few close matches — pick the right one.";
  return "Worth a second look before it goes on the quote.";
}

export default function SalesLeadView({
  lead,
  onDecision,
  pending,
}: {
  lead: CanonicalLead;
  onDecision: (d: ReviewDecision) => void;
  pending: boolean;
}) {
  const flaggedSet = useMemo(() => new Set(lead.review.flagged_paths), [lead.review.flagged_paths]);

  // Build every reviewable row (thresholds don't matter to sales, so pass {}),
  // keyed by path — the review band pulls the same objects the record shows.
  const byPath = useMemo(() => {
    const rows: FieldRowT[] = [];
    coreGroups(lead, {}).forEach((g) => rows.push(...g.rows));
    lead.line_items.forEach((_, i) => rows.push(...lineItemRows(lead, i, {})));
    return new Map(rows.map((r) => [r.path, r]));
  }, [lead]);

  // The band shows every flagged path (so its count matches the queue), each as
  // a plain card.
  const reviewRows = lead.review.flagged_paths
    .map((p) => byPath.get(p))
    .filter((r): r is FieldRowT => Boolean(r));

  const c = lead.customer;
  const p = lead.project;
  const contact = c.primary_contact;

  return (
    <div className="animate-rise-in">
      <Link to="/queue" className="eyebrow inline-flex items-center gap-1.5 hover:text-ink">
        ← Back to leads
      </Link>

      {/* header */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {c.company_name.value ?? "New inquiry"}
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-soft">
            {contact.full_name.value && <span className="font-medium text-ink">{contact.full_name.value}</span>}
            {contact.email.value && <span>{contact.email.value}</span>}
            {contact.phone.value && <span>{contact.phone.value}</span>}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 text-2xs text-ink-faint">
            <span>Came in by {humanize(lead.channel.value)}</span>
            <span>·</span>
            <span>{relativeReceived(lead.received_at)}</span>
            <span>·</span>
            <span>{segmentLabel(lead.routing.segment)}</span>
          </p>
        </div>
        <ReadyPill count={reviewRows.length} />
      </div>

      {/* review band */}
      {reviewRows.length > 0 ? (
        <section className="card mt-6 border-l-[3px] border-l-review p-4">
          <div className="flex items-center gap-2">
            <span aria-hidden className="text-review">▲</span>
            <h2 className="font-display text-lg font-semibold">Needs your review</h2>
          </div>
          <p className="mt-1 text-sm text-ink-soft">
            We captured everything else with high confidence. Just confirm or fix these{" "}
            {reviewRows.length === 1 ? "detail" : `${reviewRows.length} details`}.
          </p>
          <div className="mt-4 space-y-3">
            {reviewRows.map((row) => (
              <ReviewCard key={row.path} row={row} onDecision={onDecision} pending={pending} />
            ))}
          </div>
        </section>
      ) : (
        <section className="card mt-6 border-l-[3px] border-l-commit p-4">
          <div className="flex items-center gap-2">
            <span aria-hidden className="text-commit">●</span>
            <h2 className="font-display text-lg font-semibold">Ready to quote</h2>
          </div>
          <p className="mt-1 text-sm text-ink-soft">
            Every detail was captured with high confidence — nothing needs your review.
          </p>
        </section>
      )}

      {/* the captured record */}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <RecordCard title="Customer">
          <SalesField label="Company" path="customer.company_name" field={c.company_name} flaggedSet={flaggedSet} />
          <SalesField label="Customer type" path="customer.customer_type" field={c.customer_type} flaggedSet={flaggedSet} format={(v) => humanize(v as string)} />
          <SalesField label="Contact" path="customer.primary_contact.full_name" field={contact.full_name} flaggedSet={flaggedSet} />
          <SalesField label="Email" path="customer.primary_contact.email" field={contact.email} flaggedSet={flaggedSet} />
          <SalesField label="Phone" path="customer.primary_contact.phone" field={contact.phone} flaggedSet={flaggedSet} />
          <PlainRow label="Billing" value={cityState(c.billing_city.value, c.billing_state.value)} />
        </RecordCard>

        <RecordCard title="Project">
          <PlainRow label="Site" value={cityState(p.site_city.value, p.site_state.value)} />
          <SalesField label="Requested delivery" path="project.requested_delivery" field={p.requested_delivery} flaggedSet={flaggedSet} format={(v) => formatDate(v as string)} />
          <SalesField label="Quote deadline" path="project.quote_deadline" field={p.quote_deadline} flaggedSet={flaggedSet} format={(v) => formatDate(v as string)} />
          <PlainRow label="Budget" value={budgetRange(p.budget_low.value, p.budget_high.value)} />
          <SalesField label="Install required" path="project.install_required" field={p.install_required} flaggedSet={flaggedSet} />
        </RecordCard>
      </div>

      {/* line items as product cards */}
      <section className="mt-6">
        <div className="flex items-baseline gap-2">
          <h2 className="font-display text-lg font-semibold">What they want</h2>
          <span className="font-mono text-2xs text-ink-faint">
            {lead.line_items.length} item{lead.line_items.length === 1 ? "" : "s"}
          </span>
        </div>
        {lead.line_items.length === 0 ? (
          <p className="mt-2 text-sm text-ink-faint">No products captured from this inquiry.</p>
        ) : (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {lead.line_items.map((_, i) => (
              <ProductCard key={i} lead={lead} index={i} flaggedSet={flaggedSet} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ReadyPill({ count }: { count: number }) {
  if (count === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-commit/30 bg-commit-bg px-3 py-1 text-sm font-medium text-commit-ink">
        <span aria-hidden>●</span> Ready to quote
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-review/40 bg-review-bg px-3 py-1 text-sm font-medium text-review-ink">
      <span aria-hidden>▲</span> {count} to review
    </span>
  );
}

function ReviewCard({
  row,
  onDecision,
  pending,
}: {
  row: FieldRowT;
  onDecision: (d: ReviewDecision) => void;
  pending: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const present = hasValue(row.field.value);
  const label = salesLabel(row.path) ?? row.label;
  const snippet = row.field.evidence.find((e) => e.snippet)?.snippet ?? null;

  return (
    <div className="rounded-lg border border-review/30 bg-review-bg/25 p-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="font-medium text-ink">{label}</p>
        <p className="text-sm">
          {present ? (
            <span className="font-medium text-ink">{formatValue(row.field.value)}</span>
          ) : (
            <span className="italic text-ink-faint">nothing captured</span>
          )}
        </p>
      </div>
      <p className="mt-1 text-sm text-ink-soft">{row.field.note || reviewPrompt(row)}</p>
      {snippet && (
        <p className="mt-2 rounded-md bg-panel px-3 py-2 text-xs leading-relaxed text-ink-soft ring-1 ring-line">
          From the source: “{snippet}”
        </p>
      )}

      {!editing ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => onDecision({ field_path: row.path })}
            disabled={pending}
            className="rounded-full border border-commit/40 bg-commit-bg px-3.5 py-1.5 text-sm font-medium text-commit-ink transition-colors hover:brightness-[0.97] disabled:opacity-60"
          >
            ✓ Looks right
          </button>
          <button
            onClick={() => setEditing(true)}
            disabled={pending}
            className="rounded-full border border-line-strong bg-panel px-3.5 py-1.5 text-sm font-medium text-ink-soft transition-colors hover:bg-panel-2 disabled:opacity-60"
          >
            ✎ Fix it
          </button>
        </div>
      ) : (
        <div className="mt-3">
          <CorrectionForm
            row={row}
            pending={pending}
            onCancel={() => setEditing(false)}
            onSubmit={(d) => {
              onDecision(d);
              setEditing(false);
            }}
          />
        </div>
      )}
    </div>
  );
}

function RecordCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="card p-4">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      <dl className="mt-2 divide-y divide-line/70">{children}</dl>
    </section>
  );
}

// A single captured field. A flagged field shows a review marker instead of the
// bare "Not provided", so the record never contradicts the review band above.
function SalesField({
  label,
  path,
  field,
  flaggedSet,
  format = formatValue,
}: {
  label: string;
  path: string;
  field: Extracted;
  flaggedSet: Set<string>;
  format?: (v: unknown) => string;
}) {
  const present = hasValue(field.value);
  const flagged = flaggedSet.has(path);
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-sm text-ink-faint">{label}</dt>
      <dd className="text-right text-sm">
        {present ? (
          <span className="font-medium text-ink">{format(field.value)}</span>
        ) : flagged ? (
          <span className="inline-flex items-center gap-1 text-review-ink">
            <span aria-hidden>▲</span> in review
          </span>
        ) : (
          <span className="text-ink-faint">Not provided</span>
        )}
        {flagged && present && (
          <span className="ml-2 inline-flex items-center gap-1 text-2xs text-review-ink">
            <span aria-hidden>▲</span> in review
          </span>
        )}
      </dd>
    </div>
  );
}

// For combined/derived values (location, budget) that aren't a single field.
function PlainRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="text-sm text-ink-faint">{label}</dt>
      <dd className="text-right text-sm">
        {value ? (
          <span className="font-medium text-ink">{value}</span>
        ) : (
          <span className="text-ink-faint">Not provided</span>
        )}
      </dd>
    </div>
  );
}

function ProductCard({
  lead,
  index,
  flaggedSet,
}: {
  lead: CanonicalLead;
  index: number;
  flaggedSet: Set<string>;
}) {
  const li = lead.line_items[index];
  const base = `line_items[${index}]`;
  const sku = li.matched_sku.value;
  const skuFlagged = flaggedSet.has(`${base}.matched_sku`);
  const dims = dimensions(li.dimensions.width_in.value, li.dimensions.depth_in.value, li.dimensions.height_in.value);
  const flaggedHere = [
    `${base}.matched_sku`,
    `${base}.quantity`,
    `${base}.finish`,
    `${base}.material`,
  ].filter((pth) => flaggedSet.has(pth)).length;

  return (
    <section className={`card p-4 ${flaggedHere ? "border-l-[3px] border-l-review" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {sku ? (
            <p className="font-mono text-sm font-semibold text-brand-deep">{sku}</p>
          ) : skuFlagged ? (
            <p className="inline-flex items-center gap-1 text-sm font-medium text-review-ink">
              <span aria-hidden>▲</span> No catalog match yet
            </p>
          ) : (
            <p className="text-sm font-medium text-ink-faint">No catalog match</p>
          )}
          <p className="mt-0.5 text-sm text-ink">{li.raw_description || "—"}</p>
        </div>
        <div className="shrink-0 text-right">
          <p className="eyebrow">Qty</p>
          <p className="font-display text-xl font-semibold tabular-nums text-ink">
            {li.quantity.value ?? (flaggedSet.has(`${base}.quantity`) ? "▲" : "—")}
          </p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line pt-3 text-sm">
        <Spec label="Dimensions" value={dims} />
        <Spec label="Material" value={val(li.material.value)} />
        <Spec label="Finish" value={val(li.finish.value)} flagged={flaggedSet.has(`${base}.finish`)} />
        <Spec label="Target price" value={li.target_unit_price.value != null ? formatMoney(li.target_unit_price.value) : null} />
      </dl>
    </section>
  );
}

function Spec({ label, value, flagged }: { label: string; value: string | null; flagged?: boolean }) {
  return (
    <div>
      <dt className="text-2xs text-ink-faint">{label}</dt>
      <dd className="mt-0.5">
        {value ? (
          <span className="font-medium text-ink">{value}</span>
        ) : flagged ? (
          <span className="inline-flex items-center gap-1 text-review-ink">
            <span aria-hidden>▲</span> in review
          </span>
        ) : (
          <span className="text-ink-faint">—</span>
        )}
      </dd>
    </div>
  );
}

// ---- small value helpers --------------------------------------------------
function val(v: unknown): string | null {
  return hasValue(v) ? formatValue(v) : null;
}

function cityState(city: string | null, state: string | null): string | null {
  if (city && state) return `${city}, ${state}`;
  return city || state || null;
}

function budgetRange(low: number | null, high: number | null): string | null {
  if (low != null && high != null) return `${formatMoney(low)} – ${formatMoney(high)}`;
  if (low != null) return `from ${formatMoney(low)}`;
  if (high != null) return `up to ${formatMoney(high)}`;
  return null;
}

function dimensions(w: number | null, d: number | null, h: number | null): string | null {
  const parts = [w, d, h].filter((x): x is number => x != null);
  if (parts.length === 0) return null;
  return parts.map((x) => `${x}"`).join(" × ");
}
