import { createContext, useCallback, useContext, useRef, useState } from "react";

type ToastTone = "info" | "success" | "warn";
interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  detail?: string;
}

interface ToastApi {
  push: (t: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

const TONE_CLASS: Record<ToastTone, string> = {
  info: "border-brand/30 bg-brand-tint text-brand-deep",
  success: "border-commit/30 bg-commit-bg text-commit-ink",
  warn: "border-review/40 bg-review-bg text-review-ink",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { ...t, id }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, 5200);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`animate-rise-in pointer-events-auto rounded-card border px-4 py-3 shadow-lift ${TONE_CLASS[t.tone]}`}
          >
            <p className="font-mono text-2xs uppercase tracking-[0.16em] opacity-70">
              {t.tone === "warn" ? "Heads up" : t.tone === "success" ? "Done" : "Note"}
            </p>
            <p className="mt-0.5 text-sm font-medium leading-snug">{t.title}</p>
            {t.detail && <p className="mt-1 text-xs leading-snug opacity-80">{t.detail}</p>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
