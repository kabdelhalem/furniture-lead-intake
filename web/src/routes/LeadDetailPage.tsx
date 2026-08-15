import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { CanonicalLead, ConfidenceLevel, ReviewDecision } from "../types";
import { coreGroups, lineItemRows } from "../lib/fields";
import type { FieldRow as FieldRowT } from "../lib/fields";
import { REVIEWER } from "../lib/reviewer";
import { formatMoney, humanize, relativeReceived, segmentLabel } from "../lib/format";
import FieldRow from "../components/FieldRow";
import SalesLeadView from "../components/SalesLeadView";
import SourceCompare from "../components/SourceCompare";
import { InfoDot } from "../components/Tooltip";
import { ErrorNote, ReviewStatusBadge, SegmentBadge, Spinner } from "../components/ui";
import { useToast } from "../components/Toast";
import { useMode } from "../lib/mode";

export default function LeadDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const { isEng } = useMode();

  const leadQ = useQuery({ queryKey: ["lead", id], queryFn: () => api.lead(id) });
  // The sales view doesn't show thresholds, so only fetch them for engineering.
  const thrQ = useQuery({
    queryKey: ["thresholds"],
    queryFn: () => api.thresholds(),
    enabled: isEng,
  });

  const review = useMutation({
    mutationFn: (decision: ReviewDecision) =>
      api.review(id, [{ ...decision, reviewer: REVIEWER.id }]),
    onSuccess: (r, decision) => {
      qc.invalidateQueries({ queryKey: ["lead", id] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.push({
        tone: "success",
        title: "new_value" in decision ? "Correction saved" : "Field confirmed",
        detail: `${r.flagged_remaining} field${r.flagged_remaining === 1 ? "" : "s"} still need review.`,
      });
    },
    onError: (e: unknown) =>
      toast.push({
        tone: "warn",
        title: "Couldn't save that decision",
        detail: e instanceof Error ? e.message : undefined,
      }),
  });

  if (leadQ.isLoading || (isEng && thrQ.isLoading)) return <Spinner label="Opening the record…" />;
  if (leadQ.isError || !leadQ.data)
    return (
      <ErrorNote
        title={`Couldn't open ${id}`}
        detail={leadQ.error instanceof Error ? leadQ.error.message : undefined}
        onRetry={() => leadQ.refetch()}
      />
    );

  const lead = leadQ.data;
  const onDecision = (d: ReviewDecision) => review.mutate(d);

  if (!isEng) {
    return <SalesLeadView lead={lead} onDecision={onDecision} pending={review.isPending} />;
  }

  return (
    <LeadDetail
      lead={lead}
      thresholds={thrQ.data ?? {}}
      onDecision={onDecision}
      pending={review.isPending}
    />
  );
}

function LeadDetail({
  lead,
  thresholds,
  onDecision,
  pending,
}: {
  lead: CanonicalLead;
  thresholds: Record<string, ConfidenceLevel>;
  onDecision: (d: ReviewDecision) => void;
  pending: boolean;
}) {
  const flaggedSet = useMemo(() => new Set(lead.review.flagged_paths), [lead.review.flagged_paths]);

  // Every reviewable field, keyed by path, so the flagged section can pull the
  // exact same row objects the grouped view renders below.
  const allRows = useMemo(() => {
    const rows: FieldRowT[] = [];
    coreGroups(lead, thresholds).forEach((g) => rows.push(...g.rows));
    lead.line_items.forEach((_, i) => rows.push(...lineItemRows(lead, i, thresholds)));
    const byPath = new Map(rows.map((r) => [r.path, r]));
    return { rows, byPath };
  }, [lead, thresholds]);

  const flaggedRows = lead.review.flagged_paths
    .map((p) => allRows.byPath.get(p))
    .filter((r): r is FieldRowT => Boolean(r));

  const groups = coreGroups(lead, thresholds);
  const committed = lead.metrics.fields_auto_committed;
  const total = lead.metrics.fields_total;
  const [showSource, setShowSource] = useState(false);

  return (
    <div className="animate-rise-in">
      <Link to="/queue" className="eyebrow inline-flex items-center gap-1.5 hover:text-ink">
        ← Back to queue
      </Link>

      {/* header */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="font-display text-3xl font-semibold tracking-tight">
              {lead.customer.company_name.value ?? "Unknown sender"}
            </h1>
            <ReviewStatusBadge status={lead.review.status} />
          </div>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-2xs text-ink-faint">
            <span>{lead.lead_id}</span>
            <span>· {relativeReceived(lead.received_at)}</span>
            <span>· via {humanize(lead.channel.value)}</span>
            {lead.is_lead.value === false && (
              <span className="rounded-full border border-line-strong bg-muted-bg px-2 py-0.5 text-ink-soft">
                Classified: not a lead
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSource(true)}
            className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-panel px-3.5 py-1.5 text-sm font-medium text-ink-soft shadow-panel transition-colors hover:bg-panel-2"
          >
            <span aria-hidden>⧉</span> Compare with source
          </button>
          <SegmentBadge segment={lead.routing.segment} />
        </div>
      </div>

      <SourceCompare lead={lead} open={showSource} onClose={() => setShowSource(false)} />

      {/* summary strip */}
      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Priority"
          value={String(lead.routing.priority_score)}
          accent
          tip={
            <span>
              <b>Why {lead.routing.priority_score}/100.</b> Priority is set by deterministic
              routing rules — deal-size segment, deadline urgency, order value, and territory.
              {lead.routing.rules_fired.length > 0 && (
                <>
                  {" "}
                  Fired here: {lead.routing.rules_fired.join(", ")}.
                </>
              )}
            </span>
          }
        />
        <Stat label="Auto-committed" value={total ? `${committed}/${total}` : "—"} />
        <Stat label="Flagged" value={String(flaggedRows.length)} warn={flaggedRows.length > 0} />
        <Stat label="Cost" value={formatMoney(lead.metrics.cost_usd)} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-6">
          {/* needs your eye */}
          {flaggedRows.length > 0 ? (
            <section className="card border-l-[3px] border-l-review p-4">
              <div className="flex items-center gap-2">
                <span aria-hidden className="text-review">▲</span>
                <h2 className="font-display text-lg font-semibold">Needs your eye</h2>
                <span className="font-mono text-2xs text-ink-faint">
                  {flaggedRows.length} field{flaggedRows.length === 1 ? "" : "s"} below threshold
                </span>
              </div>
              <p className="mt-1 text-sm text-ink-soft">
                Everything else auto-committed. Confirm or correct just these.
              </p>
              <div className="mt-3 space-y-1">
                {flaggedRows.map((r) => (
                  <FieldRow
                    key={r.path}
                    row={r}
                    flagged
                    onDecision={onDecision}
                    pending={pending}
                  />
                ))}
              </div>
            </section>
          ) : (
            <section className="card border-l-[3px] border-l-commit p-4">
              <div className="flex items-center gap-2">
                <span aria-hidden className="text-commit">●</span>
                <h2 className="font-display text-lg font-semibold">Nothing flagged</h2>
              </div>
              <p className="mt-1 text-sm text-ink-soft">
                Every field cleared its threshold — this record is ready as-is.
              </p>
            </section>
          )}

          {/* grouped canonical record */}
          {groups.map((g) => (
            <section key={g.key} className="card p-4">
              <h2 className="font-display text-lg font-semibold">{g.title}</h2>
              <div className="mt-2 divide-y divide-line/70">
                {g.rows.map((r) => (
                  <FieldRow
                    key={r.path}
                    row={r}
                    flagged={flaggedSet.has(r.path)}
                    onDecision={onDecision}
                    pending={pending}
                  />
                ))}
              </div>
            </section>
          ))}

          {/* line items */}
          <section>
            <div className="flex items-baseline gap-2">
              <h2 className="font-display text-lg font-semibold">Line items</h2>
              <span className="font-mono text-2xs text-ink-faint">
                {lead.line_items.length} item{lead.line_items.length === 1 ? "" : "s"}
              </span>
            </div>
            {lead.line_items.length === 0 ? (
              <p className="mt-2 text-sm text-ink-faint">No line items extracted.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {lead.line_items.map((li, i) => (
                  <LineItemCard
                    key={i}
                    index={i}
                    description={li.raw_description}
                    rows={lineItemRows(lead, i, thresholds)}
                    flaggedSet={flaggedSet}
                    onDecision={onDecision}
                    pending={pending}
                  />
                ))}
              </div>
            )}
          </section>
        </div>

        {/* sidebar */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <RoutingCard lead={lead} />
          <ArtifactsCard lead={lead} />
        </aside>
      </div>
    </div>
  );
}

function LineItemCard({
  index,
  description,
  rows,
  flaggedSet,
  onDecision,
  pending,
}: {
  index: number;
  description: string;
  rows: FieldRowT[];
  flaggedSet: Set<string>;
  onDecision: (d: ReviewDecision) => void;
  pending: boolean;
}) {
  const flaggedHere = rows.filter((r) => flaggedSet.has(r.path)).length;
  return (
    <section className={`card p-4 ${flaggedHere ? "border-l-[3px] border-l-review" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="eyebrow">Item {index + 1}</span>
          <p className="mt-0.5 text-sm font-medium text-ink">
            {description || "—"}
          </p>
        </div>
        {flaggedHere > 0 && (
          <span className="shrink-0 rounded-full border border-review/40 bg-review-bg px-2 py-0.5 text-2xs font-medium text-review-ink">
            ▲ {flaggedHere}
          </span>
        )}
      </div>
      <div className="mt-2 divide-y divide-line/70">
        {rows.map((r) => (
          <FieldRow
            key={r.path}
            row={r}
            flagged={flaggedSet.has(r.path)}
            onDecision={onDecision}
            pending={pending}
          />
        ))}
      </div>
    </section>
  );
}

function RoutingCard({ lead }: { lead: CanonicalLead }) {
  const r = lead.routing;
  return (
    <section className="card p-4">
      <h2 className="eyebrow">Routing · deterministic rules</h2>
      <dl className="mt-2.5 space-y-2 text-sm">
        <Row label="Assigned rep" value={r.assigned_rep ?? "—"} />
        <Row label="Territory" value={humanize(r.territory)} />
        <Row label="Segment" value={segmentLabel(r.segment)} />
        <Row label="Priority" value={String(r.priority_score)} />
      </dl>
      {r.rules_fired.length > 0 && (
        <div className="mt-3">
          <p className="eyebrow">Rules fired</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {r.rules_fired.map((rule) => (
              <span
                key={rule}
                className="rounded-md border border-line bg-panel-2 px-2 py-0.5 font-mono text-[10px] text-ink-soft"
              >
                {rule}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function ArtifactsCard({ lead }: { lead: CanonicalLead }) {
  return (
    <section className="card p-4">
      <h2 className="eyebrow">Source artifacts</h2>
      <ul className="mt-2.5 space-y-2">
        {lead.source_artifacts.map((a) => (
          <li key={a.artifact_id} className="text-sm">
            <div className="flex items-center gap-2">
              <span aria-hidden className="text-ink-faint">▤</span>
              <span className="truncate font-medium text-ink">{a.filename}</span>
            </div>
            <span className="ml-6 font-mono text-[10px] text-ink-faint">
              {humanize(a.kind)}
              {a.page_count ? ` · ${a.page_count}p` : ""}
              {a.ocr_applied ? " · OCR" : ""}
            </span>
          </li>
        ))}
      </ul>
      <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-sm">
        <Row label="Model calls" value={String(lead.metrics.model_calls)} />
        <Row label="Tokens" value={lead.metrics.total_tokens.toLocaleString()} />
      </dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  warn,
  tip,
}: {
  label: string;
  value: string;
  accent?: boolean;
  warn?: boolean;
  tip?: React.ReactNode;
}) {
  return (
    <div
      className={`rounded-card border p-3 ${
        warn ? "border-review/30 bg-review-bg/40" : "border-line bg-panel"
      }`}
    >
      <p className="eyebrow inline-flex items-center">
        {label}
        {tip && <InfoDot label={tip} />}
      </p>
      <p
        className={`mt-1 font-display text-2xl font-semibold tabular-nums ${
          accent ? "text-brand-deep" : "text-ink"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
