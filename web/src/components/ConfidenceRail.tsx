import type { ConfidenceLevel } from "../types";
import { CONFIDENCE_ORDER, levelLabel, rank } from "../lib/confidence";
import type { RailTone } from "../lib/confidence";

const FILL: Record<RailTone, string> = {
  commit: "bg-commit",
  review: "bg-review",
  alarm: "bg-alarm",
  muted: "bg-muted",
  human: "bg-human",
};

interface Props {
  level: ConfidenceLevel;
  threshold: ConfidenceLevel;
  tone: RailTone;
  hasValue: boolean;
  showScale?: boolean;
}

/**
 * The bench's signature, now ordinal: five cells — Severe · Low · Medium · High ·
 * Certain — with the field's level filled from the left and a tick at the LEFT
 * edge of the minimum cell it must reach to auto-commit (apply_policy clears on
 * `>=`, so reaching the bar is enough). Severe is the alarm floor.
 */
export default function ConfidenceRail({
  level,
  threshold,
  tone,
  hasValue,
  showScale = false,
}: Props) {
  const levelRank = rank(level);
  const thrRank = rank(threshold);

  return (
    <div className="w-full">
      <div
        className="flex items-stretch gap-1"
        role="img"
        aria-label={
          hasValue
            ? `Confidence ${levelLabel(level)}; minimum to auto-commit is ${levelLabel(threshold)}`
            : `No value; minimum to auto-commit is ${levelLabel(threshold)}`
        }
      >
        {CONFIDENCE_ORDER.map((lvl, i) => {
          const filled = hasValue && i <= levelRank;
          return (
            <div key={lvl} className="relative h-2.5 flex-1">
              <div
                className={`h-full rounded-[3px] transition-colors duration-300 ${
                  filled ? FILL[tone] : "bg-line"
                }`}
              />
              {/* the threshold tick, sitting in the gap before its cell */}
              {i === thrRank && (
                <span
                  aria-hidden
                  className="absolute -left-1 top-1/2 h-4 w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink"
                />
              )}
            </div>
          );
        })}
      </div>
      {showScale && (
        <div className="mt-1 flex justify-between font-mono text-[10px] text-ink-faint">
          {CONFIDENCE_ORDER.map((lvl) => (
            <span key={lvl}>{levelLabel(lvl).slice(0, 3)}</span>
          ))}
        </div>
      )}
    </div>
  );
}
