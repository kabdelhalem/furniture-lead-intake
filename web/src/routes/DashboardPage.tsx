import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatMoney, formatPct } from "../lib/format";
import { ErrorNote, Spinner } from "../components/ui";

export default function DashboardPage() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.dashboard() });

  if (q.isLoading) return <Spinner label="Tallying the bench…" />;
  if (q.isError || !q.data)
    return (
      <ErrorNote
        title="Couldn't load the dashboard"
        detail={q.error instanceof Error ? q.error.message : undefined}
        onRetry={() => q.refetch()}
      />
    );

  const d = q.data;
  const empty = d.total_leads === 0;

  return (
    <div className="animate-rise-in">
      <p className="eyebrow">The bench, at a glance</p>
      <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Dashboard</h1>
      <p className="mt-1.5 max-w-xl text-sm text-ink-soft">
        What the confidence layer buys you: the share of fields committed with no human, and the
        review time that share saves.
      </p>

      {empty ? (
        <div className="card mt-6 p-8 text-center">
          <p className="font-display text-lg font-semibold">No leads yet</p>
          <p className="mt-1 text-sm text-ink-soft">
            Seed the corpus from the{" "}
            <Link to="/queue" className="font-medium text-brand underline-offset-2 hover:underline">
              queue
            </Link>{" "}
            to populate these numbers.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
            {/* hero: the auto-commit rate */}
            <div className="card flex flex-col items-center justify-center p-6">
              <ArcGauge value={d.auto_commit_rate} />
              <p className="mt-3 text-center font-display text-lg font-semibold">
                Auto-commit rate
              </p>
              <p className="mt-0.5 max-w-[16rem] text-center text-sm text-ink-soft">
                {d.fields_auto_committed.toLocaleString()} of {d.fields_total.toLocaleString()}{" "}
                fields cleared their threshold with no human review.
              </p>
            </div>

            {/* ROI + supporting */}
            <div className="grid grid-cols-2 gap-4">
              <BigStat
                label="Reviewer time saved"
                value={`${d.reviewer_minutes_saved_estimate}`}
                unit="min"
                sub="vs. hand-parsing every field"
                accent
              />
              <BigStat
                label="In the review queue"
                value={`${d.review_queue}`}
                unit={`of ${d.total_leads}`}
                sub="leads with a flagged field"
              />
              <BigStat
                label="Model cost"
                value={formatMoney(d.cost_usd)}
                sub={`${d.model_calls} model call${d.model_calls === 1 ? "" : "s"}`}
              />
              <BigStat
                label="Fields flagged"
                value={`${d.fields_flagged}`}
                unit={`of ${d.fields_total}`}
                sub="sent to a human"
                warn={d.fields_flagged > 0}
              />
            </div>
          </div>

          {/* split bars */}
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <SplitBar
              title="Genuine leads vs. filtered"
              caption="The classifier gate keeps non-leads out of the queue."
              parts={[
                { label: "Genuine leads", value: d.genuine_leads, tone: "commit" },
                { label: "Not a lead", value: d.not_leads, tone: "muted" },
              ]}
            />
            <SplitBar
              title="Fields: committed vs. reviewed"
              caption="The whole pitch — a human touches the small remainder."
              parts={[
                { label: "Auto-committed", value: d.fields_auto_committed, tone: "commit" },
                { label: "Flagged", value: d.fields_flagged, tone: "review" },
              ]}
            />
          </div>
        </>
      )}
    </div>
  );
}

function ArcGauge({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value));
  const size = 176;
  const stroke = 14;
  const r = (size - stroke) / 2;
  const cx = size / 2;
  // 270° sweep, opening at the bottom — a dial the VP reads instantly.
  const startDeg = 135;
  const sweep = 270;
  const circ = 2 * Math.PI * r;
  const arcLen = (sweep / 360) * circ;
  const dash = `${arcLen} ${circ}`;
  const rot = `rotate(${startDeg} ${cx} ${cx})`;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
      aria-label={`Auto-commit rate ${Math.round(pct * 100)} percent`}>
      <circle
        cx={cx} cy={cx} r={r} fill="none" stroke="#DBE1DB" strokeWidth={stroke}
        strokeLinecap="round" strokeDasharray={dash} transform={rot}
      />
      <circle
        cx={cx} cy={cx} r={r} fill="none" stroke="#3F7A54" strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${arcLen * pct} ${circ}`}
        transform={rot}
        style={{ transition: "stroke-dasharray 0.7s cubic-bezier(0.2,0.8,0.2,1)" }}
      />
      <text x="50%" y="49%" textAnchor="middle" dominantBaseline="middle"
        className="fill-ink font-display" fontSize="40" fontWeight="700">
        {formatPct(pct)}
      </text>
      <text x="50%" y="66%" textAnchor="middle" className="fill-ink-faint font-mono"
        fontSize="11" letterSpacing="1.5">
        COMMITTED
      </text>
    </svg>
  );
}

function BigStat({
  label,
  value,
  unit,
  sub,
  accent,
  warn,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  accent?: boolean;
  warn?: boolean;
}) {
  return (
    <div className={`card p-5 ${warn ? "border-review/25" : ""}`}>
      <p className="eyebrow">{label}</p>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span
          className={`font-display text-4xl font-semibold tabular-nums ${
            accent ? "text-brand-deep" : "text-ink"
          }`}
        >
          {value}
        </span>
        {unit && <span className="text-sm text-ink-faint">{unit}</span>}
      </p>
      {sub && <p className="mt-1 text-xs text-ink-soft">{sub}</p>}
    </div>
  );
}

const TONE_BG: Record<string, string> = {
  commit: "bg-commit",
  review: "bg-review",
  muted: "bg-muted",
};

function SplitBar({
  title,
  caption,
  parts,
}: {
  title: string;
  caption: string;
  parts: { label: string; value: number; tone: string }[];
}) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  return (
    <div className="card p-5">
      <p className="font-display font-semibold">{title}</p>
      <p className="mt-0.5 text-xs text-ink-soft">{caption}</p>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-line">
        {parts.map((p) => (
          <div
            key={p.label}
            className={`${TONE_BG[p.tone]} transition-all duration-500`}
            style={{ width: `${(p.value / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {parts.map((p) => (
          <span key={p.label} className="inline-flex items-center gap-1.5 text-xs text-ink-soft">
            <span aria-hidden className={`h-2 w-2 rounded-full ${TONE_BG[p.tone]}`} />
            {p.label}
            <span className="font-mono font-medium text-ink tabular-nums">{p.value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
