import type { StatusMeta } from "../lib/fields";
import { statusMeta } from "../lib/fields";
import type { FieldStatus } from "../types";
import { reviewStatusLabel, segmentLabel } from "../lib/format";

// ---- status chip (field-level) -------------------------------------------
const CHIP_CLASS: Record<StatusMeta["tone"], string> = {
  commit: "border-commit/30 bg-commit-bg text-commit-ink",
  review: "border-review/40 bg-review-bg text-review-ink",
  muted: "border-line-strong bg-muted-bg text-ink-soft",
  human: "border-human/30 bg-human-bg text-brand-deep",
};

export function StatusChip({ status }: { status: FieldStatus }) {
  const meta = statusMeta(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-2xs font-medium ${CHIP_CLASS[meta.tone]}`}
    >
      <span aria-hidden className="text-[9px] leading-none">
        {meta.glyph}
      </span>
      {meta.label}
    </span>
  );
}

// ---- segment badge (brand/ink channel, kept off the confidence hues) ------
const SEGMENT_CLASS: Record<string, string> = {
  enterprise: "border-brand/40 bg-brand text-panel",
  mid_market: "border-brand/30 bg-brand-tint text-brand-deep",
  smb: "border-line-strong bg-panel-2 text-ink-soft",
  unclassified: "border-line bg-panel text-ink-faint",
};

export function SegmentBadge({ segment }: { segment: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-2xs uppercase tracking-[0.08em] ${
        SEGMENT_CLASS[segment] ?? SEGMENT_CLASS.unclassified
      }`}
    >
      {segmentLabel(segment)}
    </span>
  );
}

// ---- review-status badge --------------------------------------------------
const REVIEW_CLASS: Record<string, string> = {
  pending: "border-review/40 bg-review-bg text-review-ink",
  in_review: "border-brand/30 bg-brand-tint text-brand-deep",
  approved: "border-commit/30 bg-commit-bg text-commit-ink",
  rejected: "border-line-strong bg-muted-bg text-ink-soft",
  duplicate: "border-line-strong bg-muted-bg text-ink-soft",
};

export function ReviewStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-2xs font-medium ${
        REVIEW_CLASS[status] ?? REVIEW_CLASS.pending
      }`}
    >
      {reviewStatusLabel(status)}
    </span>
  );
}

// ---- priority meter -------------------------------------------------------
export function PriorityMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div
      className="h-1.5 w-28 overflow-hidden rounded-full bg-line"
      role="meter"
      aria-valuenow={score}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Priority ${score} of 100`}
      title={`Priority ${score}/100`}
    >
      <div
        className="h-full rounded-full bg-gradient-to-r from-brand to-brand-deep"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---- generic states -------------------------------------------------------
export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-16 text-ink-faint">
      <span
        aria-hidden
        className="h-4 w-4 animate-spin rounded-full border-2 border-line-strong border-t-brand"
      />
      <span className="text-sm">{label ?? "Loading…"}</span>
    </div>
  );
}

export function ErrorNote({
  title,
  detail,
  onRetry,
}: {
  title: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="card animate-rise-in border-review/30 bg-review-bg/60 p-6">
      <p className="font-mono text-2xs uppercase tracking-[0.16em] text-review-ink">Can't load</p>
      <p className="mt-1 font-medium text-ink">{title}</p>
      {detail && <p className="mt-1 text-sm text-ink-soft">{detail}</p>}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 rounded-full border border-review/40 bg-panel px-4 py-1.5 text-sm font-medium text-review-ink hover:bg-review-bg"
        >
          Try again
        </button>
      )}
    </div>
  );
}
