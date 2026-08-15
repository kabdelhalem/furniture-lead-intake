import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import type {
  ConfidenceLevel,
  FieldClassHealth,
  Observability,
  ThresholdSuggestion,
} from "../types";
import { CONFIDENCE_ORDER, levelLabel, rank } from "../lib/confidence";
import { humanize, prettyPath } from "../lib/format";
import { useMode } from "../lib/mode";
import { ErrorNote, Spinner } from "../components/ui";
import { InfoDot } from "../components/Tooltip";
import { useToast } from "../components/Toast";

// The "Pipeline health" panel closes the confidence loop: it turns real review
// outcomes — what a human corrected vs. confirmed — into a per-field-class
// verdict on whether each auto-commit bar is set too low or too high.

export default function HealthPage() {
  const q = useQuery({ queryKey: ["observability"], queryFn: () => api.observability() });

  if (q.isLoading) return <Spinner label="Reading review outcomes…" />;
  if (q.isError || !q.data)
    return (
      <ErrorNote
        title="Couldn't load pipeline health"
        detail={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => q.refetch()}
      />
    );

  const d = q.data;
  const empty = d.reviewed_fields === 0;

  return (
    <div className="animate-rise-in">
      <p className="eyebrow">Closing the loop</p>
      <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Pipeline health</h1>
      <p className="mt-1.5 max-w-2xl text-sm text-ink-soft">
        Every reviewed field is a graded prediction. Where we auto-committed a value a human then
        <b> corrected</b>, the bar was too low. Where we flagged a value the reviewer
        <b> confirmed</b> as-is, the bar was too high. This is which way to move each threshold.
      </p>

      {empty ? (
        <EmptyState />
      ) : (
        <>
          <HeroRow d={d} />
          <FieldClassTable byClass={d.by_field_class} />
          <ReasonCodes codes={d.reason_codes} />
        </>
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card mt-6 p-8 text-center">
      <p className="font-display text-lg font-semibold">No reviews yet</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-ink-soft">
        As reviewers confirm and correct flagged fields, this panel shows which confidence
        thresholds to tune. To demo it, resolve a few flagged fields first — e.g. correct
        L007's ambiguous SKU — from the{" "}
        <Link to="/queue" className="font-medium text-brand underline-offset-2 hover:underline">
          queue
        </Link>
        .
      </p>
    </div>
  );
}

// ---- hero stats -----------------------------------------------------------
function HeroRow({ d }: { d: Observability }) {
  return (
    <>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <HeroStat
          tone="alarm"
          label="Confidently wrong"
          value={d.false_auto_commits}
          blurb="Fields we auto-committed with no review that a human then had to correct. Each one reached a reviewer too late — the bar for its class is too low."
        />
        <HeroStat
          tone="review"
          label="Over-cautious"
          value={d.over_flags}
          blurb="Fields we flagged that the reviewer confirmed unchanged — wasted review effort. The bar for its class is set higher than it needs to be."
        />
      </div>

      {/* supporting context — the denominators behind the two hero numbers */}
      <div className="mt-4 grid grid-cols-3 gap-4">
        <MiniStat label="Fields reviewed" value={d.reviewed_fields} />
        <MiniStat label="Corrected" value={d.corrections} />
        <MiniStat label="Confirmed" value={d.confirmations} />
      </div>
    </>
  );
}

const HERO_TONE: Record<"alarm" | "review", { border: string; num: string; dot: string }> = {
  alarm: { border: "border-alarm/30", num: "text-alarm-ink", dot: "bg-alarm" },
  review: { border: "border-review/40", num: "text-review-ink", dot: "bg-review" },
};

function HeroStat({
  tone,
  label,
  value,
  blurb,
}: {
  tone: "alarm" | "review";
  label: string;
  value: number;
  blurb: string;
}) {
  const t = HERO_TONE[tone];
  return (
    <div className={`card p-5 ${t.border}`}>
      <p className="flex items-center gap-2 eyebrow">
        <span aria-hidden className={`h-2 w-2 rounded-full ${t.dot}`} />
        {label}
      </p>
      <p className={`mt-2 font-display text-5xl font-semibold tabular-nums ${t.num}`}>{value}</p>
      <p className="mt-1.5 text-xs leading-snug text-ink-soft">{blurb}</p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-ink">{value}</p>
    </div>
  );
}

// ---- per-field-class table ------------------------------------------------
// tighten rows need action, so they sort to the top; within a group the backend's
// alphabetical path order is preserved (Array.prototype.sort is stable).
const SUGGESTION_RANK: Record<ThresholdSuggestion, number> = { tighten: 0, loosen: 1, ok: 2 };

const SUGGESTION_PILL: Record<ThresholdSuggestion, string> = {
  tighten: "border-alarm/30 bg-alarm-bg text-alarm-ink",
  loosen: "border-review/40 bg-review-bg text-review-ink",
  ok: "border-line-strong bg-muted-bg text-ink-soft",
};

// One rung on the ladder (severe < low < medium < high < certain); null at the ends.
function bumpedLevel(
  current: ConfidenceLevel,
  suggestion: ThresholdSuggestion,
): ConfidenceLevel | null {
  const i = rank(current);
  if (suggestion === "tighten") return i < CONFIDENCE_ORDER.length - 1 ? CONFIDENCE_ORDER[i + 1] : null;
  if (suggestion === "loosen") return i > 0 ? CONFIDENCE_ORDER[i - 1] : null;
  return null;
}

function FieldClassTable({ byClass }: { byClass: Record<string, FieldClassHealth> }) {
  const { isEng } = useMode();
  const qc = useQueryClient();
  const toast = useToast();

  // Bump one field class's minimum level a rung and re-run apply_policy across
  // every stored lead — the same PUT the Thresholds page uses. Invalidate the
  // same query set (plus observability, which recomputes against the new bar).
  const bump = useMutation({
    mutationFn: (v: { path: string; level: ConfidenceLevel }) =>
      api.putThresholds({ overrides: { [v.path]: v.level } }),
    onSuccess: (r, v) => {
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["thresholds"] });
      qc.invalidateQueries({ queryKey: ["lead"] });
      qc.invalidateQueries({ queryKey: ["observability"] });
      const delta = r.review_queue_after - r.review_queue_before;
      toast.push({
        tone: "info",
        title: `${prettyPath(v.path)} → ≥ ${levelLabel(v.level)}`,
        detail:
          delta === 0
            ? "Queue unchanged."
            : `Review queue ${delta > 0 ? "grew" : "shrank"} by ${Math.abs(delta)} lead${
                Math.abs(delta) === 1 ? "" : "s"
              }.`,
      });
    },
    onError: (e: unknown) =>
      toast.push({
        tone: "warn",
        title: "Couldn't move the threshold",
        detail: e instanceof Error ? e.message : undefined,
      }),
  });

  const rows = Object.entries(byClass).sort(
    (a, b) => SUGGESTION_RANK[a[1].suggestion] - SUGGESTION_RANK[b[1].suggestion],
  );

  return (
    <section className="card mt-4 overflow-hidden p-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-5 py-4">
        <div>
          <p className="eyebrow">By field class</p>
          <h2 className="font-display text-lg font-semibold">Where the bar is wrong</h2>
        </div>
        <p className="flex items-center gap-1 text-xs text-ink-soft">
          Suggestion
          <InfoDot
            label={
              <span>
                <b>Tighten</b> = raise this class's minimum level; we auto-committed something a
                human had to correct. <b>Loosen</b> = lower it; we flagged something the reviewer
                confirmed unchanged.
                {isEng ? " Use the bump control to apply it and watch the queue resize." : ""}
              </span>
            }
          />
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-line text-left font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">
              <th className="px-5 py-2.5 font-normal">Field class</th>
              <th className="px-3 py-2.5 font-normal">Min level</th>
              <th className="px-3 py-2.5 text-right font-normal">Reviewed</th>
              <th className="px-3 py-2.5 text-right font-normal">Corrected</th>
              <th className="px-3 py-2.5 text-right font-normal">Confirmed</th>
              <th className="px-3 py-2.5 text-right font-normal">
                <span className="text-alarm-ink">False auto-commits</span>
              </th>
              <th className="px-3 py-2.5 text-right font-normal">
                <span className="text-review-ink">Over-flags</span>
              </th>
              <th className="px-5 py-2.5 font-normal">Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([path, c]) => {
              const next = bumpedLevel(c.current_min_level, c.suggestion);
              const actionable = isEng && next !== null && c.suggestion !== "ok";
              const pending = bump.isPending && bump.variables?.path === path;
              return (
                <tr key={path} className="border-b border-line/70 last:border-0">
                  <td className="px-5 py-3">
                    <p className="font-medium text-ink">{prettyPath(path)}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-ink-faint">{path}</p>
                  </td>
                  <td className="px-3 py-3">
                    <span className="rounded-full border border-brand/30 bg-brand-tint px-2 py-0.5 font-mono text-2xs font-bold uppercase tracking-[0.06em] text-brand-deep">
                      ≥ {levelLabel(c.current_min_level)}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-ink-soft">
                    {c.reviewed}
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-ink-soft">
                    {c.corrected}
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums text-ink-soft">
                    {c.confirmed}
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums">
                    <span className={c.false_auto_commits > 0 ? "font-bold text-alarm-ink" : "text-ink-faint"}>
                      {c.false_auto_commits}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono tabular-nums">
                    <span className={c.over_flags > 0 ? "font-bold text-review-ink" : "text-ink-faint"}>
                      {c.over_flags}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-2xs font-medium capitalize ${SUGGESTION_PILL[c.suggestion]}`}
                      >
                        {c.suggestion}
                      </span>
                      {actionable && next && (
                        <button
                          onClick={() => bump.mutate({ path, level: next })}
                          disabled={bump.isPending}
                          className="rounded-full border border-line-strong bg-panel px-2.5 py-0.5 font-mono text-2xs font-medium text-ink-soft hover:bg-panel-2 disabled:opacity-50"
                          title={`Set ${path} to ≥ ${levelLabel(next)} and re-run the queue`}
                        >
                          {pending ? "…" : `→ ≥ ${levelLabel(next)}`}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {isEng && (
        <p className="border-t border-line px-5 py-3 text-xs text-ink-soft">
          Bumping a bar re-runs the same <code className="font-mono text-[10px]">apply_policy()</code>{" "}
          across every stored lead — the queue and dashboard update to match.
        </p>
      )}
    </section>
  );
}

// ---- reason codes ---------------------------------------------------------
function ReasonCodes({ codes }: { codes: Record<string, number> }) {
  const entries = Object.entries(codes).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, n]) => n));

  return (
    <section className="card mt-4 p-5">
      <p className="eyebrow">Why fields were corrected</p>
      <h2 className="font-display text-lg font-semibold">Reason codes</h2>
      <p className="mt-1 max-w-2xl text-sm text-ink-soft">
        What reviewers cited when they changed a value — the recurring failure modes worth chasing
        upstream in extraction.
      </p>
      <ul className="mt-4 space-y-2.5">
        {entries.map(([code, n]) => (
          <li key={code} className="flex items-center gap-3">
            <span className="w-40 shrink-0 text-sm text-ink">{humanize(code)}</span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-line">
              <span
                className="block h-full rounded-full bg-review transition-all duration-500"
                style={{ width: `${(n / max) * 100}%` }}
              />
            </span>
            <span className="w-8 shrink-0 text-right font-mono text-sm tabular-nums text-ink-soft">
              {n}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
