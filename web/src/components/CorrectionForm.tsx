import { useState } from "react";
import type { FieldRow as FieldRowT } from "../lib/fields";
import type { ReviewDecision } from "../types";
import { humanize } from "../lib/format";

const REASON_CODES = ["wrong_sku", "hallucinated", "missed", "unit_error", "other"];

/** Runner-up SKUs live in `alternatives` as plain strings; nothing else populates it. */
export function skuAlternatives(row: FieldRowT): string[] {
  return (row.field.alternatives ?? []).filter((a): a is string => typeof a === "string");
}

/**
 * The one correction editor, shared by both the engineering field rows and the
 * sales review cards. Editor type comes from the field path (lib/fields.kindFor),
 * never the current value — flagged fields are frequently null — so a numeric
 * correction persists as an int, not a string.
 */
export default function CorrectionForm({
  row,
  pending,
  onCancel,
  onSubmit,
}: {
  row: FieldRowT;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (d: ReviewDecision) => void;
}) {
  const { field, path, kind } = row;
  const alternatives = skuAlternatives(row);
  const hasAlts = alternatives.length > 0;
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
      <p className="eyebrow">Set the correct value</p>

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
