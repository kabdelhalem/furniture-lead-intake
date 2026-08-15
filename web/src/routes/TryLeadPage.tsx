import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { CompareBody } from "../components/SourceCompare";
import { Spinner } from "../components/ui";

const SAMPLE = `From: Marcus Bell <mbell@harborviewhotels.com>
Subject: Lobby refresh - quote request

Hi - we're refreshing the lobby at our Harborview property in Savannah, GA.
We'll need about 12 lounge chairs in a walnut frame with a dark green COM,
and 6 round cafe tables around 36". Hoping to install before the holidays.
Budget is somewhere around 40-50k. Can you put a quote together?

Thanks,
Marcus Bell
Director of Facilities
404-555-0148`;

function fileToB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1] ?? "");
    r.onerror = () => reject(new Error("Couldn't read that file"));
    r.readAsDataURL(file);
  });
}

function friendlyError(e: unknown): { title: string; detail: string } {
  if (e instanceof ApiError) {
    if (e.status === 400) return { title: "Nothing to extract", detail: "Paste some text or choose a file first." };
    if (e.status === 503)
      return {
        title: "Live extraction is off",
        detail: "The demo server is in replay mode. Set ANTHROPIC_API_KEY in .env and run `make serve` to try live leads.",
      };
    if (e.status === 502)
      return {
        title: "The model call didn't complete",
        detail: "Live extraction failed — check the server's API key and connection, then try again.",
      };
    if (e.status === 0) return { title: "Can't reach the backend", detail: e.message };
    return { title: "Extraction failed", detail: e.message };
  }
  return { title: "Extraction failed", detail: e instanceof Error ? e.message : "Unexpected error" };
}

export default function TryLeadPage() {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const extract = useMutation({
    mutationFn: async () => {
      if (file) {
        const content_b64 = await fileToB64(file);
        return api.ingestRaw({ content_b64, filename: file.name });
      }
      return api.ingestRaw({ text, filename: "pasted.eml" });
    },
  });

  const hasInput = text.trim().length > 0 || file !== null;

  const reset = () => {
    setText("");
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
    extract.reset();
  };

  const result = extract.data;

  return (
    <div className="animate-rise-in">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">The live curveball</p>
          <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">Try a lead</h1>
          <p className="mt-1.5 max-w-xl text-sm text-ink-soft">
            Paste any inbound email — or upload a real PDF or spreadsheet — and watch the pipeline
            read it in real time. This one isn't pre-computed: it's a live model call.
          </p>
        </div>
        {result && (
          <button
            onClick={reset}
            className="rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft shadow-panel hover:bg-panel-2"
          >
            Try another
          </button>
        )}
      </div>

      {!result && !extract.isPending && (
        <div className="card mt-6 p-5">
          <label htmlFor="paste" className="eyebrow">
            Paste an inbound email
          </label>
          <textarea
            id="paste"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (file) setFile(null);
            }}
            placeholder="From: ...&#10;Subject: ...&#10;&#10;Hi, we're looking for..."
            rows={12}
            className="mt-2 w-full rounded-md border border-line bg-panel-2 px-3 py-2 font-mono text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
          />

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              onClick={() => extract.mutate()}
              disabled={!hasInput}
              className="rounded-full bg-brand px-5 py-2 text-sm font-medium text-panel transition-colors hover:bg-brand-deep disabled:opacity-50"
            >
              Extract
            </button>

            <span className="text-2xs text-ink-faint">or</span>

            <label className="cursor-pointer rounded-full border border-line-strong bg-panel px-4 py-2 text-sm font-medium text-ink-soft hover:bg-panel-2">
              {file ? file.name : "Upload a file"}
              <input
                ref={fileInput}
                type="file"
                accept=".eml,.txt,.pdf,.xlsx,.xls,.csv,.dxf"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  if (f) setText("");
                }}
              />
            </label>
            {file && (
              <button onClick={() => { setFile(null); if (fileInput.current) fileInput.current.value = ""; }} className="text-2xs text-ink-faint underline-offset-2 hover:underline">
                clear
              </button>
            )}

            <button
              onClick={() => { setFile(null); setText(SAMPLE); }}
              className="ml-auto text-2xs text-brand-deep underline-offset-2 hover:underline"
            >
              Paste a sample
            </button>
          </div>

          {extract.isError && <ErrorNotice error={extract.error} />}
        </div>
      )}

      {extract.isPending && (
        <div className="card mt-6 flex flex-col items-center gap-2 p-12 text-center">
          <Spinner label="Reading the lead — a live model call, this takes a few seconds…" />
          <p className="max-w-sm text-xs text-ink-faint">
            The corpus leads are instant because they replay from cache. This one is running the
            real extraction, so give it a moment.
          </p>
        </div>
      )}

      {result && (
        <>
          <p className="mt-4 text-sm text-ink-soft">
            Here's the email you gave us on the left, and everything the pipeline pulled out — with
            its confidence and reasons — on the right. Hover a field to see where it came from.
          </p>
          <div className="mt-3 flex h-[78vh] flex-col overflow-hidden rounded-card border border-line bg-panel shadow-panel">
            <CompareBody lead={result.lead} docs={result.source} />
          </div>
        </>
      )}
    </div>
  );
}

function ErrorNotice({ error }: { error: unknown }) {
  const { title, detail } = friendlyError(error);
  return (
    <div className="mt-3 rounded-md border border-review/30 bg-review-bg/60 px-4 py-3">
      <p className="font-medium text-review-ink">{title}</p>
      <p className="mt-0.5 text-sm text-ink-soft">{detail}</p>
    </div>
  );
}
