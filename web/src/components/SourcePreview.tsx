import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CanonicalLead, Evidence } from "../types";
import { artifactUrl } from "../api";
import { coreGroups, lineItemRows } from "../lib/fields";
import { humanize } from "../lib/format";

// The "Preview original" slide-over: the ingested lead (email / PDF / sheet /
// CAD) next to the review, available even when the lead is fully approved. The
// raw-file preview streams from the backend once that route exists; until then
// the drawer still earns its place by showing the verbatim excerpts the
// extractor pulled from each source — the real compare material.

function shortArtifact(id: string): string {
  const parts = id.split("::");
  return parts[parts.length - 1] || id;
}

export default function SourcePreview({
  lead,
  open,
  onClose,
}: {
  lead: CanonicalLead;
  open: boolean;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Verbatim excerpts the extractor cited, grouped by the file they came from.
  const excerptsByArtifact = useMemo(() => {
    const rows = [
      ...coreGroups(lead, {}).flatMap((g) => g.rows),
      ...lead.line_items.flatMap((_, i) => lineItemRows(lead, i, {})),
    ];
    const map = new Map<string, Evidence[]>();
    for (const r of rows) {
      for (const ev of r.field.evidence) {
        if (!ev.snippet) continue;
        const list = map.get(ev.artifact_id) ?? [];
        if (!list.some((e) => e.snippet === ev.snippet && e.locator === ev.locator)) {
          list.push(ev);
          map.set(ev.artifact_id, list);
        }
      }
    }
    return map;
  }, [lead]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Original lead">
      <button
        aria-label="Close preview"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-ink/40 animate-rise-in"
      />
      <div className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col bg-paper shadow-lift animate-[rise-in_0.28s_ease-out] duration-300">
        <header className="flex items-center justify-between border-b border-line bg-panel px-5 py-3.5">
          <div>
            <p className="eyebrow">Original lead · {lead.lead_id}</p>
            <p className="text-sm font-medium text-ink">As it was ingested</p>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full border border-line-strong bg-panel text-ink-soft transition-colors hover:bg-panel-2"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          {lead.source_artifacts.length === 0 ? (
            <p className="text-sm text-ink-faint">No source artifacts recorded for this lead.</p>
          ) : (
            lead.source_artifacts.map((a) => (
              <ArtifactBlock
                key={a.artifact_id}
                leadId={lead.lead_id}
                filename={a.filename}
                kind={a.kind}
                pageCount={a.page_count}
                excerpts={
                  excerptsByArtifact.get(a.artifact_id) ??
                  // artifact_id is "L007::L007.eml"; excerpts key on the same id
                  excerptsByArtifact.get(`${lead.lead_id}::${a.filename}`) ??
                  []
                }
              />
            ))
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

type PreviewState =
  | { kind: "loading" }
  | { kind: "text"; text: string }
  | { kind: "pdf"; url: string }
  | { kind: "download"; url: string }
  | { kind: "unavailable" };

function ArtifactBlock({
  leadId,
  filename,
  kind,
  pageCount,
  excerpts,
}: {
  leadId: string;
  filename: string;
  kind: string;
  pageCount: number | null;
  excerpts: Evidence[];
}) {
  const [state, setState] = useState<PreviewState>({ kind: "loading" });
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";

  useEffect(() => {
    let revoke: string | null = null;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(artifactUrl(leadId, filename));
        if (!res.ok) throw new Error(String(res.status));
        if (ext === "eml" || ext === "txt") {
          const text = await res.text();
          if (!cancelled) setState({ kind: "text", text });
        } else if (ext === "pdf") {
          const url = URL.createObjectURL(await res.blob());
          revoke = url;
          if (!cancelled) setState({ kind: "pdf", url });
        } else {
          const url = URL.createObjectURL(await res.blob());
          revoke = url;
          if (!cancelled) setState({ kind: "download", url });
        }
      } catch {
        if (!cancelled) setState({ kind: "unavailable" });
      }
    })();
    return () => {
      cancelled = true;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [leadId, filename, ext]);

  return (
    <section className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line bg-panel-2 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span aria-hidden className="text-ink-faint">▤</span>
          <span className="font-mono text-sm font-medium text-ink">{filename}</span>
        </div>
        <span className="font-mono text-2xs text-ink-faint">
          {humanize(kind)}
          {pageCount ? ` · ${pageCount}p` : ""}
        </span>
      </div>

      <div className="p-4">
        {state.kind === "loading" && <p className="text-sm text-ink-faint">Loading original…</p>}

        {state.kind === "text" && (
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-panel p-3 font-mono text-xs leading-relaxed text-ink ring-1 ring-line">
            {state.text}
          </pre>
        )}

        {state.kind === "pdf" && (
          <iframe title={filename} src={state.url} className="h-96 w-full rounded-md ring-1 ring-line" />
        )}

        {state.kind === "download" && (
          <a
            href={state.url}
            download={filename}
            className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft hover:bg-panel-2"
          >
            ↓ Download {filename}
          </a>
        )}

        {state.kind === "unavailable" && (
          <p className="rounded-md bg-panel-2 px-3 py-2 text-xs leading-relaxed text-ink-soft ring-1 ring-line">
            The full file preview connects here once the source-file route is live. Meanwhile, the
            verbatim excerpts the system read from it are below.
          </p>
        )}

        {excerpts.length > 0 && (
          <div className={state.kind === "unavailable" ? "mt-3" : "mt-4 border-t border-line pt-3"}>
            <p className="eyebrow">What we read from this source</p>
            <ul className="mt-1.5 space-y-1.5">
              {excerpts.map((ev, i) => (
                <li key={i} className="rounded-md border border-line bg-panel px-3 py-2">
                  {ev.locator && (
                    <p className="font-mono text-[10px] text-ink-faint">{ev.locator}</p>
                  )}
                  <p className="text-xs leading-relaxed text-ink">“{ev.snippet}”</p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {state.kind === "unavailable" && excerpts.length === 0 && (
          <p className="mt-3 text-xs text-ink-faint">
            No excerpts were cited from {shortArtifact(filename)}.
          </p>
        )}
      </div>
    </section>
  );
}
