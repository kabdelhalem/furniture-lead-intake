import type { StatusMeta } from "../lib/fields";

const FILL: Record<StatusMeta["tone"], string> = {
  commit: "bg-commit",
  review: "bg-review",
  muted: "bg-muted",
  human: "bg-human",
};

interface Props {
  confidence: number; // 0..1
  threshold: number; // 0..1
  tone: StatusMeta["tone"];
  hasValue: boolean;
  showScale?: boolean;
}

/**
 * The bench's signature: a field's confidence plotted against the threshold for
 * its *class*. The tick is the bar the value has to clear to auto-commit. When a
 * threshold slider moves, the tick slides and fields cross the line — the whole
 * tunable-queue idea, made visible on a single field.
 */
export default function ConfidenceRail({
  confidence,
  threshold,
  tone,
  hasValue,
  showScale = false,
}: Props) {
  const conf = Math.max(0, Math.min(1, confidence));
  const thr = Math.max(0, Math.min(1, threshold));
  const short = hasValue && conf < thr; // has a value but under the bar
  const gapLeft = Math.min(conf, thr);
  const gapWidth = Math.abs(thr - conf);

  return (
    <div className="w-full">
      <div
        className="relative h-2 rounded-full bg-line"
        role="img"
        aria-label={
          hasValue
            ? `Confidence ${Math.round(conf * 100)} percent against a threshold of ${Math.round(thr * 100)} percent`
            : `No value; threshold ${Math.round(thr * 100)} percent`
        }
      >
        {/* filled confidence */}
        {hasValue && (
          <div
            className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-500 ${FILL[tone]}`}
            style={{ width: `${conf * 100}%` }}
          />
        )}
        {/* the shortfall between value and the bar it needed to clear */}
        {short && (
          <div
            className="absolute inset-y-0 rounded-full bg-review-bg transition-all duration-500"
            style={{ left: `${gapLeft * 100}%`, width: `${gapWidth * 100}%` }}
          />
        )}
        {/* the threshold tick */}
        <div
          className="absolute top-1/2 z-10 h-3.5 w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink transition-[left] duration-500"
          style={{ left: `${thr * 100}%` }}
        />
      </div>
      {showScale && (
        <div className="mt-1 flex justify-between font-mono text-[10px] text-ink-faint">
          <span>0</span>
          <span>threshold {Math.round(thr * 100)}%</span>
          <span>100</span>
        </div>
      )}
    </div>
  );
}
