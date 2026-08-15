import type { ConfidenceLevel, FieldStatus } from "../types";

// The ordinal scale, weakest → strongest. Mirrors schema.Confidence._CONFIDENCE_RANK.
export const CONFIDENCE_ORDER: ConfidenceLevel[] = [
  "severe",
  "low",
  "medium",
  "high",
  "certain",
];

export function rank(level: ConfidenceLevel): number {
  return CONFIDENCE_ORDER.indexOf(level);
}

// apply_policy clears a field when confidence >= threshold, so reaching the
// threshold level is enough.
export function meetsThreshold(level: ConfidenceLevel, threshold: ConfidenceLevel): boolean {
  return rank(level) >= rank(threshold);
}

const LABEL: Record<ConfidenceLevel, string> = {
  severe: "Severe",
  low: "Low",
  medium: "Medium",
  high: "High",
  certain: "Certain",
};

export function levelLabel(level: ConfidenceLevel): string {
  return LABEL[level];
}

// The rail's fill/alarm hue. Distinct from the status chip: it answers "did this
// value clear its bar?", with SEVERE broken out as an alarm (conflict /
// hallucination risk) — but only when the value is actually present and pending.
// An absent field is `severe` by default; that stays muted, never alarm-red.
export type RailTone = "commit" | "review" | "muted" | "human" | "alarm";

export function railTone(
  status: FieldStatus,
  level: ConfidenceLevel,
  hasValue: boolean,
): RailTone {
  if (status === "human_corrected" || status === "human_confirmed") return "human";
  if (status === "auto_committed") return "commit";
  if (status === "not_found" || !hasValue) return "muted";
  // needs_review, value present:
  return level === "severe" ? "alarm" : "review";
}
