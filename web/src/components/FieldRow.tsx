import { useState } from "react";
import type { FieldRow as FieldRowT } from "../lib/fields";
import { isHumanTouched, statusMeta } from "../lib/fields";
import type { Evidence, ReviewDecision } from "../types";
import { formatValue, humanize } from "../lib/format";
import ConfidenceRail from "./ConfidenceRail";
import { StatusChip } from "./ui";

const REASON_CODES = ["wrong_sku", "hallucinated", "missed", "unit_error", "other"];

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
  const meta = statusMeta(field.status);
  const present = hasValue(field.value);
  const [open, setOpen] = useState(flagged);
  const [editing, setEditing] = useState(false);

  // The alternatives payload for matched_sku is a list of plain SKU strings.
  const alternatives = (field.alternatives ?? []).filter(
    (a): a is string => typeof a === "string",
  );

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
          <div className="w-full sm:max-w-[130px]">
            <ConfidenceRail
              confidence={field.confidence}
              threshold={threshold}
              tone={meta.tone}
              hasValue={present}
            />
          </div>
          <span className="font-mono text-[10px] tabular-nums text-ink-faint">
            {present ? `${Math.round(field.confidence * 100)}%` : "no value"} · thr{" "}
            {Math.round(threshold * 100)}%
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
              alternatives={alternatives}
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

function CorrectionForm({
  row,
  alternatives,
  pending,
  onCancel,
  onSubmit,
}: {
  row: FieldRowT;
  alternatives: string[];
  pending: boolean;
  onCancel: () => void;
  onSubmit: (d: ReviewDecision) => void;
}) {
  const { field, path, kind } = row;
  const hasAlts = alternatives.length > 0;
  // Editor type is derived from the field path (see lib/fields.kindFor), never
  // from the current value — flagged fields are frequently null.
  const isBool = kind === "bool";
  const isNum = kind === "number";

  const [text, setText] = useState(field.value == null ? "" : String(field.value));
  const [bool, setBool] = useState<boolean>(field.value === true);
  const [sku, setSku] = useState<string>(alternatives[0] ?? "");
  const [reason, setReason] = useState<string>(hasAlts ? "wrong_sku" : "other");

  const numInvalid = isNum && !hasAlts && (text.trim() === "" || !Number.isFinite(Number(text)));
  const textInvalid = kind === "text" && !hasAlts && text.trim() === "";
  const invalid = numInvalid || textInvalid;

  const submit = () => {
    if (invalid) return;
    let newValue: unknown;
    if (hasAlts) newValue = sku;
    else if (isBool) newValue = bool;
    else if (isNum) newValue = Number(text);
    else newValue = text;
    onSubmit({ field_path: path, new_value: newValue, reason_code: reason });
  };

  return (
    <div className="space-y-3 rounded-md bg-panel p-3 ring-1 ring-line">
      <p className="eyebrow">Correct this field</p>

      {hasAlts ? (
        <fieldset className="space-y-1.5">
          <legend className="sr-only">Pick a SKU</legend>
          {alternatives.map((alt) => (
            <label
              key={alt}
              className={`flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2 text-sm transition-colors ${
                sku === alt ? "border-brand bg-brand-tint" : "border-line hover:bg-panel-2"
              }`}
            >
              <input
                type="radio"
                name={`sku-${path}`}
                checked={sku === alt}
                onChange={() => setSku(alt)}
                className="accent-brand"
              />
              <span className="font-mono">{alt}</span>
            </label>
          ))}
        </fieldset>
      ) : isBool ? (
        <div className="flex gap-2">
          {[true, false].map((v) => (
            <button
              key={String(v)}
              onClick={() => setBool(v)}
              className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
                bool === v ? "border-brand bg-brand text-panel" : "border-line bg-panel text-ink-soft"
              }`}
            >
              {v ? "Yes" : "No"}
            </button>
          ))}
        </div>
      ) : (
        <input
          type={isNum ? "number" : "text"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
          placeholder="New value"
          className="w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none"
        />
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`reason-${path}`} className="eyebrow">
          Reason
        </label>
        <select
          id={`reason-${path}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="rounded-md border border-line bg-panel px-2 py-1 font-mono text-2xs text-ink-soft focus:outline-none"
        >
          {REASON_CODES.map((r) => (
            <option key={r} value={r}>
              {humanize(r)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-2 pt-0.5">
        <button
          onClick={submit}
          disabled={pending || invalid}
          className="rounded-full bg-brand px-4 py-1.5 text-sm font-medium text-panel hover:bg-brand-deep disabled:opacity-50"
        >
          Save correction
        </button>
        <button
          onClick={onCancel}
          disabled={pending}
          className="rounded-full px-3 py-1.5 text-sm font-medium text-ink-soft hover:bg-panel-2"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// "L007::L007.eml" -> "L007.eml"
function shortArtifact(id: string): string {
  const parts = id.split("::");
  return parts[parts.length - 1] || id;
}
