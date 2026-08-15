import { cloneElement, isValidElement, useId, useState } from "react";
import type { ReactElement, ReactNode } from "react";
import { createPortal } from "react-dom";

// A small hover/focus tooltip. Rendered through a portal with fixed positioning
// so it never gets clipped by a card's rounding or overflow, and clamped to the
// viewport so edge triggers (the last column header) don't overflow. Shows on
// both hover and keyboard focus, and wires aria-describedby onto the trigger.

const MAX_W = 264;

interface Anchor {
  cx: number;
  top: number;
  bottom: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Handler = ((e: any) => void) | undefined;
const chain = (a: Handler, b: Handler) => (e: unknown) => {
  a?.(e);
  b?.(e);
};

export function Tooltip({
  content,
  children,
}: {
  content: ReactNode;
  // A single focusable/hoverable element (button, span, etc.).
  children: ReactElement;
}) {
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const id = useId();

  if (!isValidElement(children)) return children;

  const show = (e: { currentTarget: Element }) => {
    const r = e.currentTarget.getBoundingClientRect();
    setAnchor({ cx: r.left + r.width / 2, top: r.top, bottom: r.bottom });
  };
  const hide = () => setAnchor(null);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = children.props as any;
  const trigger = cloneElement(children, {
    onMouseEnter: chain(p.onMouseEnter, show),
    onMouseLeave: chain(p.onMouseLeave, hide),
    onFocus: chain(p.onFocus, show),
    onBlur: chain(p.onBlur, hide),
    "aria-describedby": anchor ? id : p["aria-describedby"],
  } as Record<string, unknown>);

  return (
    <>
      {trigger}
      {anchor &&
        createPortal(
          <Bubble id={id} anchor={anchor} content={content} />,
          document.body,
        )}
    </>
  );
}

function Bubble({ id, anchor, content }: { id: string; anchor: Anchor; content: ReactNode }) {
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const half = MAX_W / 2;
  const left = Math.min(Math.max(anchor.cx, 8 + half), vw - 8 - half);
  const flipBelow = anchor.top < 96; // not enough room above -> drop below
  const style: React.CSSProperties = flipBelow
    ? { left, top: anchor.bottom + 8, transform: "translateX(-50%)" }
    : { left, top: anchor.top - 8, transform: "translate(-50%, -100%)" };

  return (
    <div
      role="tooltip"
      id={id}
      style={{ position: "fixed", maxWidth: MAX_W, zIndex: 60, ...style }}
      className="pointer-events-none animate-rise-in rounded-md bg-ink px-3 py-2 text-xs leading-snug text-panel shadow-lift"
    >
      {content}
    </div>
  );
}

// A discreet "?" trigger for when there's no obvious element to hover.
export function InfoDot({ label }: { label: ReactNode }) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        aria-label="More info"
        className="ml-1 inline-grid h-3.5 w-3.5 place-items-center rounded-full border border-line-strong bg-panel text-[9px] font-bold text-ink-faint align-middle hover:border-brand hover:text-brand"
      >
        ?
      </button>
    </Tooltip>
  );
}
