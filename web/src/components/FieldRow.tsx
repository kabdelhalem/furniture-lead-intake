import { useState } from "react";
import type { FieldRow as FieldRowT } from "../lib/fields";
import { isHumanTouched } from "../lib/fields";
import { levelLabel, railTone } from "../lib/confidence";
import type { RailTone } from "../lib/confidence";
import type { Evidence, ReviewDecision } from "../types";
import { formatValue } from "../lib/format";
import ConfidenceRail from "./ConfidenceRail";
import CorrectionForm from "./CorrectionForm";
import { StatusChip } from "./ui";

const LEVEL_TEXT: Record<RailTone, string> = {
  commit: "text-commit-ink",
  review: "text-review-ink",
  alarm: "text-alarm-ink",
  muted: "text-ink-faint",
  human: "text-brand-deep",
};

function hasValue(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (Array.isArray(v)) return v.length > 0;
  return true;
}

interface Props {
  row: FieldRowT;
  flagged: boolean;
  onDecision: (decision: ReviewDecision) => void;
  pending: boolean;
}

export default function FieldRow({ row, flagged, onDecision, pending }: Props) {
  const { field, path, label, threshold } = row;
  const present = hasValue(field.value);
  const tone = railTone(field.status, field.confidence, present);
  const [open, setOpen] = useState(flagged);
  const [editing, setEditing] = useState(false);

  const canReview = flagged || field.status === "needs_review";

  return (
    <div
      className={`rounded-lg border transition-colors ${
        flagged ? "border-review/30 bg-review-bg/25" : "border-transparent hover:bg-panel-2"
      }`}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="grid w-full grid-cols-[1fr_auto] items-start gap-3 rounded-lg px-3 py-2.5 text-left sm:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)_minmax(120px,0.9fr)]"
        aria-expanded={open}
      >
        {/* label */}
        <div className="min-w-0">
          <span className="block truncate text-sm font-medium text-ink">{label}</span>
          <span className="font-mono text-[10px] text-ink-faint">{path}</span>
        </div>

        {/* value */}
        <div className="min-w-0 sm:pl-2">
          <span
            className={`block truncate text-sm ${present ? "text-ink" : "italic text-ink-faint"}`}
            title={present ? formatValue(field.value) : "Not stated in the source"}
          >
            {present ? formatValue(field.value) : "Not stated in the source"}
          </span>
          {isHumanTouched(field.status) && (
            <span className="font-mono text-[10px] text-brand-deep">
              {field.status === "human_corrected" ? "edited by reviewer" : "confirmed by reviewer"}
            </span>
          )}
        </div>

        {/* status + rail */}
        <div className="col-span-2 flex flex-col items-stretch gap-1.5 sm:col-span-1 sm:items-end">
          <StatusChip status={field.status} />
          <div className="w-full sm:max-w-[140px]">
            <ConfidenceRail
              level={field.confidence}
              threshold={threshold}
              tone={tone}
              hasValue={present}
            />
          </div>
          <span className="font-mono text-[10px] text-ink-faint">
            <span className={present ? `font-medium ${LEVEL_TEXT[tone]}` : ""}>
              {present ? levelLabel(field.confidence) : "no value"}
            </span>{" "}
            · min {levelLabel(threshold)}
          </span>
        </div>
      </button>

      {open && (
        <div className="animate-rise-in space-y-3 px-3 pb-3.5 pt-1">
          {field.note && (
            <p className="rounded-md bg-panel px-3 py-2 text-xs leading-relaxed text-ink-soft ring-1 ring-line">
              <span className="font-medium text-ink">Why it hesitated: </span>
              {field.note}
            </p>
          )}

          <EvidenceList evidence={field.evidence} extractor={field.extractor} />

          {canReview && !editing && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => onDecision({ field_path: path })}
                disabled={pending}
                className="rounded-full border border-commit/40 bg-commit-bg px-3.5 py-1.5 text-sm font-medium text-commit-ink transition-colors hover:brightness-[0.97] disabled:opacity-60"
              >
                ✓ Confirm as-is
              </button>
              <button
                onClick={() => setEditing(true)}
                disabled={pending}
                className="rounded-full border border-line-strong bg-panel px-3.5 py-1.5 text-sm font-medium text-ink-soft transition-colors hover:bg-panel-2 disabled:opacity-60"
              >
                ✎ Correct value
              </button>
            </div>
          )}

          {editing && (
            <CorrectionForm
              row={row}
              pending={pending}
              onCancel={() => setEditing(false)}
              onSubmit={(decision) => {
                onDecision(decision);
                setEditing(false);
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceList({
  evidence,
  extractor,
}: {
  evidence: Evidence[];
  extractor: string | null;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <p className="eyebrow">Evidence · show me why</p>
        {extractor && <span className="font-mono text-[10px] text-ink-faint">{extractor}</span>}
      </div>
      {evidence.length === 0 ? (
        <p className="mt-1 text-xs text-ink-faint">No source citation recorded.</p>
      ) : (
        <ul className="mt-1.5 space-y-1.5">
          {evidence.map((ev, i) => (
            <li
              key={i}
              className="rounded-md border border-line bg-panel px-3 py-2 font-mono text-xs text-ink-soft"
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-ink-faint">
                <span className="text-brand-deep">{shortArtifact(ev.artifact_id)}</span>
                {ev.locator && <span>· {ev.locator}</span>}
              </div>
              {ev.snippet && <p className="mt-1 leading-relaxed text-ink">“{ev.snippet}”</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// "L007::L007.eml" -> "L007.eml"
function shortArtifact(id: string): string {
  const parts = id.split("::");
  return parts[parts.length - 1] || id;
}
