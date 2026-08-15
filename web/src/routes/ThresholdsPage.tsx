import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { ConfidenceLevel, ThresholdResult } from "../types";
import { CONFIDENCE_ORDER, levelLabel, rank } from "../lib/confidence";
import { ErrorNote, Spinner } from "../components/ui";
import { useToast } from "../components/Toast";

// The field classes worth exposing — the ones whose threshold visibly moves the
// queue. Ordered high-stakes first. Paths match schema.THRESHOLDS keys exactly.
const SLIDERS: { path: string; label: string; blurb: string }[] = [
  {
    path: "customer.primary_contact.email",
    label: "Contact email",
    blurb: "Unrecoverable if wrong — the quote goes to the wrong inbox. Sits high.",
  },
  {
    path: "line_items[].quantity",
    label: "Line-item quantity",
    blurb: "A quantity error scales the whole quote.",
  },
  {
    path: "line_items[].matched_sku",
    label: "Matched SKU",
    blurb: "Fuzzy catalog match; expensive to get wrong.",
  },
  {
    path: "customer.customer_type",
    label: "Customer type",
    blurb: "Dealer vs. designer vs. end customer — drives segment and pricing.",
  },
  {
    path: "is_lead",
    label: "Is a genuine lead",
    blurb: "The classifier gate that keeps non-leads out of the queue.",
  },
  {
    path: "line_items[].finish",
    label: "Finish",
    blurb: "Descriptive; caught downstream by the rep, so it sits low.",
  },
];

export default function ThresholdsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const thrQ = useQuery({ queryKey: ["thresholds"], queryFn: () => api.thresholds() });
  // Seeds the "review queue now" readout so it's populated on arrival, before
  // the reviewer has moved a slider.
  const dashQ = useQuery({ queryKey: ["dashboard"], queryFn: () => api.dashboard() });

  const [values, setValues] = useState<Record<string, ConfidenceLevel>>({});
  const [lastResult, setLastResult] = useState<ThresholdResult | null>(null);

  // Seed local slider state once the server values arrive (and after a reset).
  useEffect(() => {
    if (thrQ.data) {
      const data = thrQ.data;
      setValues(Object.fromEntries(SLIDERS.map((s) => [s.path, data[s.path] ?? "high"])));
    }
  }, [thrQ.data]);

  const put = useMutation({
    mutationFn: (payload: { overrides?: Record<string, ConfidenceLevel> } | { reset: true }) =>
      api.putThresholds(payload),
    onSuccess: (r) => {
      setLastResult(r);
      // apply_policy re-ran server-side across every lead — everything downstream
      // of a threshold is now stale.
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["thresholds"] });
      qc.invalidateQueries({ queryKey: ["lead"] });
    },
    onError: (e: unknown) =>
      toast.push({
        tone: "warn",
        title: "Couldn't apply thresholds",
        detail: e instanceof Error ? e.message : undefined,
      }),
  });

  const commit = (next: Record<string, ConfidenceLevel>) => put.mutate({ overrides: next });

  const onReset = () => {
    put.mutate(
      { reset: true },
      {
        onSuccess: () => {
          thrQ.refetch();
          toast.push({ tone: "info", title: "Thresholds reset to defaults" });
        },
      },
    );
  };

  if (thrQ.isLoading) return <Spinner label="Loading thresholds…" />;
  if (thrQ.isError)
    return (
      <ErrorNote
        title="Couldn't load thresholds"
        detail={thrQ.error instanceof Error ? thrQ.error.message : undefined}
        onRetry={() => thrQ.refetch()}
      />
    );

  const delta = lastResult ? lastResult.review_queue_after - lastResult.review_queue_before : 0;
  const queueNow = lastResult ? lastResult.review_queue_after : dashQ.data?.review_queue;

  return (
    <div className="animate-rise-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Tune the bar</p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Thresholds</h1>
          <p className="mt-1.5 max-w-xl text-sm text-ink-soft">
            Confidence is per field; the bar is per field <em>class</em>. Raise a bar and more
            fields fall to a human; lower it and the queue shrinks. Watch it move.
          </p>
        </div>
        <button
          onClick={onReset}
          disabled={put.isPending}
          className="rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft shadow-panel hover:bg-panel-2 disabled:opacity-60"
        >
          Reset to defaults
        </button>
      </div>

      {/* live queue readout */}
      <div className="card mt-6 flex flex-wrap items-center gap-x-8 gap-y-3 p-5">
        <div>
          <p className="eyebrow">Review queue now</p>
          <p className="mt-1 font-display text-4xl font-semibold tabular-nums text-ink">
            {queueNow ?? "—"}
            <span className="ml-1 text-base font-normal text-ink-faint">leads</span>
          </p>
        </div>
        {lastResult && (
          <div className="flex items-center gap-2 font-mono text-sm">
            <span className="text-ink-faint">{lastResult.review_queue_before}</span>
            <span aria-hidden className="text-ink-faint">→</span>
            <span className="font-bold text-ink">{lastResult.review_queue_after}</span>
            {delta !== 0 && (
              <span
                className={`rounded-full px-2 py-0.5 text-2xs font-medium ${
                  delta > 0
                    ? "bg-review-bg text-review-ink"
                    : "bg-commit-bg text-commit-ink"
                }`}
              >
                {delta > 0 ? `+${delta}` : delta} lead{Math.abs(delta) === 1 ? "" : "s"}
              </span>
            )}
          </div>
        )}
        <p className="max-w-xs text-xs text-ink-soft">
          Moving a slider re-runs the policy across every stored lead — the same{" "}
          <code className="font-mono text-[10px]">apply_policy()</code> the pipeline uses.
        </p>
      </div>

      {/* sliders — five ordinal stops: Severe · Low · Medium · High · Certain */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {SLIDERS.map((s) => {
          const v = values[s.path] ?? "high";
          const idx = rank(v);
          return (
            <div key={s.path} className="card p-4">
              <div className="flex items-baseline justify-between gap-2">
                <label htmlFor={s.path} className="text-sm font-medium text-ink">
                  {s.label}
                </label>
                <span className="rounded-full border border-brand/30 bg-brand-tint px-2.5 py-0.5 font-mono text-2xs font-bold uppercase tracking-[0.08em] text-brand-deep">
                  ≥ {levelLabel(v)}
                </span>
              </div>
              <p className="mt-0.5 font-mono text-[10px] text-ink-faint">{s.path}</p>
              <input
                id={s.path}
                type="range"
                min={0}
                max={CONFIDENCE_ORDER.length - 1}
                step={1}
                value={idx}
                onChange={(e) =>
                  setValues((prev) => ({ ...prev, [s.path]: CONFIDENCE_ORDER[Number(e.target.value)] }))
                }
                onPointerUp={() => commit({ ...values })}
                onKeyUp={() => commit({ ...values })}
                className="mt-3 w-full accent-brand"
                disabled={put.isPending}
                aria-valuetext={levelLabel(v)}
              />
              <div className="mt-1 flex justify-between font-mono text-[10px] text-ink-faint">
                {CONFIDENCE_ORDER.map((lvl) => (
                  <span key={lvl} className={lvl === v ? "font-bold text-brand-deep" : ""}>
                    {levelLabel(lvl).slice(0, 3)}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-xs leading-snug text-ink-soft">{s.blurb}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
