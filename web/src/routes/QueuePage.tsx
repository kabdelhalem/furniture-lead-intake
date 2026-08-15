import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, CORPUS_LEAD_IDS } from "../api";
import type { LeadSummary } from "../types";
import { formatPct, relativeReceived } from "../lib/format";
import {
  ErrorNote,
  PriorityMeter,
  ReviewStatusBadge,
  SegmentBadge,
  Spinner,
} from "../components/ui";
import { useToast } from "../components/Toast";

type Filter = "all" | "queue" | "approved";

export default function QueuePage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("all");
  const [simId, setSimId] = useState<string>(CORPUS_LEAD_IDS[6]); // L007, the SKU-ambiguity one

  const leadsQ = useQuery({
    queryKey: ["leads"],
    queryFn: () => api.leads({ orderByPriority: true }),
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["leads"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const seed = useMutation({
    mutationFn: () => api.seed(),
    onSuccess: (r) => {
      invalidateAll();
      toast.push({
        tone: r.skipped.length ? "warn" : "success",
        title: `Seeded ${r.loaded} lead${r.loaded === 1 ? "" : "s"} from the corpus`,
        detail: r.skipped.length
          ? `Skipped ${r.skipped.join(", ")} — not in the replay cache (the scanned-fax vision path needs \`make record\`).`
          : undefined,
      });
    },
    onError: (e: unknown) =>
      toast.push({ tone: "warn", title: "Seed failed", detail: msg(e) }),
  });

  const simulate = useMutation({
    mutationFn: (id: string) => api.simulateInbox(id),
    onSuccess: (s) => {
      invalidateAll();
      toast.push({
        tone: "success",
        title: `${s.company_name ?? s.lead_id} landed in the queue`,
        detail: `Priority ${s.priority_score} · ${s.flagged_count} field${s.flagged_count === 1 ? "" : "s"} flagged`,
      });
    },
    onError: (e: unknown, id) =>
      toast.push({
        tone: "warn",
        title: `Couldn't ingest ${id}`,
        detail:
          e instanceof ApiError && e.status === 500
            ? `${id} isn't in the replay cache. Record it with \`make record\`, or pick another lead.`
            : msg(e),
      }),
  });

  const leads = leadsQ.data ?? [];
  const shown = useMemo(() => {
    if (filter === "queue") return leads.filter((l) => l.flagged_count > 0);
    if (filter === "approved") return leads.filter((l) => l.review_status === "approved");
    return leads;
  }, [leads, filter]);

  const inQueue = leads.filter((l) => l.flagged_count > 0).length;

  return (
    <div className="animate-rise-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">The bench</p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Review queue</h1>
          <p className="mt-1.5 max-w-xl text-sm text-ink-soft">
            Inbound leads, highest priority first. The system auto-commits what it's sure of;
            you touch only the flagged fields.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-full border border-line bg-panel px-1.5 py-1.5 shadow-panel">
            <label htmlFor="sim" className="sr-only">
              Corpus lead to simulate
            </label>
            <select
              id="sim"
              value={simId}
              onChange={(e) => setSimId(e.target.value)}
              className="rounded-full bg-transparent px-2 py-1 font-mono text-sm text-ink focus:outline-none"
            >
              {CORPUS_LEAD_IDS.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
            <button
              onClick={() => simulate.mutate(simId)}
              disabled={simulate.isPending}
              className="rounded-full bg-brand px-3.5 py-1.5 text-sm font-medium text-panel transition-colors hover:bg-brand-deep disabled:opacity-60"
            >
              {simulate.isPending ? "Ingesting…" : "Simulate inbox"}
            </button>
          </div>
          <button
            onClick={() => seed.mutate()}
            disabled={seed.isPending}
            className="rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft shadow-panel transition-colors hover:bg-panel-2 disabled:opacity-60"
          >
            {seed.isPending ? "Seeding…" : "Seed corpus"}
          </button>
        </div>
      </div>

      {/* filter tabs */}
      <div className="mt-6 flex items-center gap-2 border-b border-line pb-3">
        {(
          [
            ["all", `All (${leads.length})`],
            ["queue", `Needs review (${inQueue})`],
            ["approved", "Approved"],
          ] as [Filter, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded-full px-3 py-1 text-sm font-medium transition-colors ${
              filter === key ? "bg-ink text-panel" : "text-ink-soft hover:bg-panel-2"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {leadsQ.isLoading ? (
        <Spinner label="Loading the queue…" />
      ) : leadsQ.isError ? (
        <div className="mt-6">
          <ErrorNote
            title="Couldn't load the queue"
            detail={msg(leadsQ.error)}
            onRetry={() => leadsQ.refetch()}
          />
        </div>
      ) : leads.length === 0 ? (
        <EmptyQueue onSeed={() => seed.mutate()} seeding={seed.isPending} />
      ) : (
        <ul className="mt-4 flex flex-col gap-2">
          <li className="hidden grid-cols-[1.6fr_0.8fr_1fr_0.9fr_auto] gap-4 px-4 md:grid">
            <span className="eyebrow">Company</span>
            <span className="eyebrow">Segment</span>
            <span className="eyebrow">Priority</span>
            <span className="eyebrow">Confidence</span>
            <span className="eyebrow text-right">Status</span>
          </li>
          {shown.map((l) => (
            <QueueRow key={l.lead_id} lead={l} onOpen={() => navigate(`/leads/${l.lead_id}`)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function QueueRow({ lead, onOpen }: { lead: LeadSummary; onOpen: () => void }) {
  const flagged = lead.flagged_count;
  const notLead = lead.is_lead === false;
  return (
    <li>
      <button
        onClick={onOpen}
        className={`card group grid w-full grid-cols-1 gap-3 p-4 text-left transition-all hover:-translate-y-0.5 hover:shadow-lift md:grid-cols-[1.6fr_0.8fr_1fr_0.9fr_auto] md:items-center md:gap-4 ${
          flagged > 0 ? "border-l-[3px] border-l-review" : ""
        }`}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-ink">{lead.company_name ?? "Unknown sender"}</span>
            {notLead && (
              <span className="shrink-0 rounded-full border border-line-strong bg-muted-bg px-2 py-0.5 text-2xs text-ink-soft">
                Not a lead
              </span>
            )}
          </div>
          <span className="mt-0.5 block font-mono text-2xs text-ink-faint">
            {lead.lead_id} · {relativeReceived(lead.received_at)}
          </span>
        </div>

        <div className="md:justify-self-start">
          <SegmentBadge segment={lead.segment} />
        </div>

        <div>
          <PriorityMeter score={lead.priority_score} />
        </div>

        <div className="flex items-center gap-2">
          {flagged > 0 ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-review/40 bg-review-bg px-2 py-0.5 text-2xs font-medium text-review-ink">
              <span aria-hidden>▲</span> {flagged} flagged
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-commit/30 bg-commit-bg px-2 py-0.5 text-2xs font-medium text-commit-ink">
              <span aria-hidden>●</span> all clear
            </span>
          )}
          <span className="font-mono text-2xs text-ink-faint">{formatPct(lead.auto_commit_rate)} auto</span>
        </div>

        <div className="flex items-center justify-between gap-2 md:justify-end">
          <ReviewStatusBadge status={lead.review_status} />
          <span
            aria-hidden
            className="text-ink-faint transition-transform group-hover:translate-x-0.5"
          >
            →
          </span>
        </div>
      </button>
    </li>
  );
}

function EmptyQueue({ onSeed, seeding }: { onSeed: () => void; seeding: boolean }) {
  return (
    <div className="card mt-6 flex flex-col items-center gap-4 px-6 py-16 text-center">
      <span aria-hidden className="grid h-12 w-12 place-items-center rounded-full bg-brand-tint text-brand-deep">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M3 7h18M3 7l2 12h14l2-12M3 7l3-4h12l3 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <div>
        <p className="font-display text-lg font-semibold">The bench is empty</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">
          Seed the demo corpus to load the sample leads, or simulate a single inbound from the
          controls above.
        </p>
      </div>
      <button
        onClick={onSeed}
        disabled={seeding}
        className="rounded-full bg-brand px-5 py-2 text-sm font-medium text-panel hover:bg-brand-deep disabled:opacity-60"
      >
        {seeding ? "Seeding…" : "Seed corpus"}
      </button>
    </div>
  );
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : "Unexpected error";
}
