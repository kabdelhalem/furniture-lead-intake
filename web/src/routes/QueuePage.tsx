import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, CORPUS_LEAD_IDS } from "../api";
import type { LeadSummary } from "../types";
import { relativeReceived } from "../lib/format";
import {
  ErrorNote,
  PriorityMeter,
  ReviewStatusBadge,
  SegmentBadge,
  Spinner,
} from "../components/ui";
import { useToast } from "../components/Toast";
import { Tooltip } from "../components/Tooltip";

type Filter = "all" | "queue" | "approved";

type SortKey = "company" | "segment" | "priority" | "flags" | "status";
type Dir = "asc" | "desc";

// A newly-picked column starts in its most useful direction.
const DEFAULT_DIR: Record<SortKey, Dir> = {
  company: "asc",
  segment: "desc",
  priority: "desc",
  flags: "desc",
  status: "asc",
};

const SEGMENT_RANK: Record<string, number> = {
  enterprise: 3,
  mid_market: 2,
  smb: 1,
  unclassified: 0,
};
const STATUS_RANK: Record<string, number> = {
  pending: 0,
  in_review: 1,
  approved: 2,
  rejected: 3,
  duplicate: 4,
};

function compare(a: LeadSummary, b: LeadSummary, key: SortKey): number {
  switch (key) {
    case "company": {
      // null company ("Unknown sender") always sorts last in ascending order —
      // locale collation puts a punctuation sentinel first, so handle it here.
      const an = a.company_name;
      const bn = b.company_name;
      if (!an && !bn) return 0;
      if (!an) return 1;
      if (!bn) return -1;
      return an.localeCompare(bn, undefined, { sensitivity: "base" });
    }
    case "segment":
      return (SEGMENT_RANK[a.segment] ?? -1) - (SEGMENT_RANK[b.segment] ?? -1);
    case "priority":
      return a.priority_score - b.priority_score;
    case "flags":
      return a.flagged_count - b.flagged_count;
    case "status":
      return (STATUS_RANK[a.review_status] ?? 9) - (STATUS_RANK[b.review_status] ?? 9);
  }
}

export default function QueuePage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>("queue"); // land on what needs review
  const [sort, setSort] = useState<{ key: SortKey; dir: Dir }>({ key: "priority", dir: "desc" });

  const toggleSort = (key: SortKey) =>
    setSort((s) =>
      s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: DEFAULT_DIR[key] },
    );

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
  const seededIds = useMemo(() => new Set(leads.map((l) => l.lead_id)), [leads]);

  // "Simulate inbox" drops the next sample lead that isn't in the queue yet, so
  // each click feels like a fresh inbound arriving (the demo stand-in for IMAP).
  const simulateNext = () => {
    const next = CORPUS_LEAD_IDS.find((id) => !seededIds.has(id));
    if (!next) {
      toast.push({
        tone: "info",
        title: "Every sample lead is already in the queue",
        detail: "Paste a fresh one under “Try a lead” to run a live extraction.",
      });
      return;
    }
    simulate.mutate(next);
  };

  const shown = useMemo(() => {
    const filtered =
      filter === "queue"
        ? leads.filter((l) => l.flagged_count > 0)
        : filter === "approved"
          ? leads.filter((l) => l.review_status === "approved")
          : leads;
    const sorted = [...filtered].sort((a, b) => compare(a, b, sort.key));
    if (sort.dir === "desc") sorted.reverse();
    return sorted;
  }, [leads, filter, sort]);

  const inQueue = leads.filter((l) => l.flagged_count > 0).length;

  return (
    <div className="animate-rise-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">The bench</p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Review queue</h1>
          <p className="mt-1.5 max-w-xl text-sm text-ink-soft">
            Leads that need a decision, highest priority first. Click a column to re-sort, or
            open a lead to review its flagged fields.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Tooltip content="Drops the next sample lead into the queue — the demo stand-in for a new email arriving (replays a pre-recorded corpus lead, so it's instant).">
            <button
              onClick={simulateNext}
              disabled={simulate.isPending}
              className="rounded-full bg-brand px-4 py-2 text-sm font-medium text-panel transition-colors hover:bg-brand-deep disabled:opacity-60"
            >
              {simulate.isPending ? "Ingesting…" : "Simulate a new lead"}
            </button>
          </Tooltip>
          <Tooltip content="Loads all the pre-built sample leads at once, so the queue and dashboard are populated. Safe to click again — it won't duplicate.">
            <button
              onClick={() => seed.mutate()}
              disabled={seed.isPending}
              className="rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft shadow-panel transition-colors hover:bg-panel-2 disabled:opacity-60"
            >
              {seed.isPending ? "Loading…" : "Load all samples"}
            </button>
          </Tooltip>
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
          <li className="hidden grid-cols-[1.6fr_0.8fr_1fr_0.9fr_auto] items-center gap-4 px-4 md:grid">
            <SortHeader k="company" label="Company" sort={sort} onSort={toggleSort} />
            <SortHeader
              k="segment"
              label="Segment"
              sort={sort}
              onSort={toggleSort}
              tip="Deal-size band from the routing rules — Enterprise, Mid-market, or SMB."
            />
            <SortHeader
              k="priority"
              label="Priority"
              sort={sort}
              onSort={toggleSort}
              tip="How soon to work this lead (0–100), set by deterministic routing rules — deal-size segment, deadline urgency, order value, and territory. Higher means work it sooner."
            />
            <SortHeader
              k="flags"
              label="Flags"
              sort={sort}
              onSort={toggleSort}
              tip="How many fields on this lead still need a human. 'All clear' means the system captured everything with high confidence."
            />
            <SortHeader k="status" label="Status" sort={sort} onSort={toggleSort} align="right" />
          </li>
          {shown.length === 0 ? (
            <li className="card px-4 py-10 text-center text-sm text-ink-soft">
              No leads {filter === "queue" ? "need review" : "in this view"} right now.
            </li>
          ) : (
            shown.map((l) => (
              <QueueRow key={l.lead_id} lead={l} onOpen={() => navigate(`/leads/${l.lead_id}`)} />
            ))
          )}
        </ul>
      )}
    </div>
  );
}

function SortHeader({
  k,
  label,
  sort,
  onSort,
  align,
  tip,
}: {
  k: SortKey;
  label: string;
  sort: { key: SortKey; dir: Dir };
  onSort: (k: SortKey) => void;
  align?: "right";
  tip?: string;
}) {
  const active = sort.key === k;
  const btn = (
    <button
      onClick={() => onSort(k)}
      aria-label={`Sort by ${label}${active ? (sort.dir === "asc" ? ", ascending" : ", descending") : ""}`}
      className={`eyebrow flex w-full items-center gap-1 transition-colors hover:text-ink ${
        align === "right" ? "justify-end" : ""
      } ${active ? "text-ink" : ""}`}
    >
      {label}
      <span
        aria-hidden
        className={`text-[8px] leading-none ${active ? "opacity-100" : "opacity-30"}`}
      >
        {active && sort.dir === "asc" ? "▲" : "▼"}
      </span>
    </button>
  );
  return tip ? <Tooltip content={tip}>{btn}</Tooltip> : btn;
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
          Load the sample leads to fill the queue, or use “Simulate a new lead” above to watch
          them arrive one at a time.
        </p>
      </div>
      <button
        onClick={onSeed}
        disabled={seeding}
        className="rounded-full bg-brand px-5 py-2 text-sm font-medium text-panel hover:bg-brand-deep disabled:opacity-60"
      >
        {seeding ? "Loading…" : "Load all samples"}
      </button>
    </div>
  );
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : "Unexpected error";
}
