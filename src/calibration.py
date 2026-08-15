"""
Calibration report: is the pipeline's confidence *honest*?

Field accuracy (see `src/eval.py`) answers a different question — IS the
predicted value right? Calibration asks whether the confidence attached to that
value can be trusted: of the fields the pipeline marked `certain`, what fraction
were actually correct against ground truth? A well-calibrated system sits near
100% accuracy at `certain` and degrades monotonically as the level drops toward
`severe`. When it doesn't — when a lower level is *more* accurate than a higher
one — the confidence signal is lying, and every downstream decision built on it
(what auto-commits, what a reviewer sees) is standing on sand.

This is the evidence `THRESHOLDS` in `src/schema.py` is meant to be tuned from.
If `certain` only earns 85% accuracy, the bar for auto-commit is set too low; if
`low` fields are 99% correct, the review queue is doing wasted work. Reading the
per-level accuracy tells you which way to move each field class's minimum level.

The report buckets every labelled truth field by its *predicted* confidence
level and reports accuracy per bucket, plus a `monotonic` flag that fires the
moment the ladder stops behaving.
"""

from __future__ import annotations

from .eval import values_equal
from .schema import (
    CanonicalLead,
    Confidence,
    flatten_confidences,
    flatten_values,
)

# The confidence ladder, best-first. Every report carries all five rows in this
# order so an empty level is visibly empty (accuracy `None`), not missing.
_LADDER = [
    Confidence.CERTAIN,
    Confidence.HIGH,
    Confidence.MEDIUM,
    Confidence.LOW,
    Confidence.SEVERE,
]


def _accuracy(correct: int, n: int) -> float | None:
    """Accuracy of a bucket, or `None` when it has no fields — an empty level is
    unmeasured, which is a distinct thing from measured-and-zero."""
    return correct / n if n else None


def reliability(
    predicted: dict[str, CanonicalLead], truths: dict[str, dict]
) -> dict:
    """Bucket every labelled field by its predicted confidence and score accuracy.

    Only *curated* leads are scored — the volume leads (`curated=False`) run
    through the pipeline for the demo but carry no authored ground truth, so
    they cannot judge calibration. A lead present in `truths` but absent from
    `predicted` is skipped, exactly as `eval.evaluate` does.

    For each scored lead, every path in `truth["fields"]` that is not a meta key
    (`_`-prefixed) is compared: the predicted value against the expected value
    via `values_equal` (the same comparison the accuracy eval uses), bucketed by
    the field's predicted confidence level.
    """
    # counts[level] -> [n, correct]
    counts: dict[Confidence, list[int]] = {lvl: [0, 0] for lvl in _LADDER}

    for lead_id, truth in truths.items():
        # Mirror eval.evaluate: volume leads are not scored, and the default must
        # be True so real ground-truth records (which omit the key) still count.
        if not truth.get("curated", True):
            continue
        pred = predicted.get(lead_id)
        if pred is None:
            continue

        values = flatten_values(pred)
        confidences = flatten_confidences(pred)

        for path, expected in truth.get("fields", {}).items():
            if path.startswith("_"):
                continue
            got = values.get(path)
            # A path with no envelope in the prediction has no self-reported
            # level; fall back to SEVERE — the schema's own default for an
            # `Extracted.confidence` — so the field still lands in a bucket
            # rather than silently shrinking the denominator.
            level = confidences.get(path, Confidence.SEVERE)
            counts[level][0] += 1
            if values_equal(expected, got):
                counts[level][1] += 1

    levels = [
        {
            "level": lvl.value,
            "n": counts[lvl][0],
            "correct": counts[lvl][1],
            "accuracy": _accuracy(counts[lvl][1], counts[lvl][0]),
        }
        for lvl in _LADDER
    ]

    total_n = sum(c[0] for c in counts.values())
    total_correct = sum(c[1] for c in counts.values())

    # Monotonic: accuracy must never *increase* as the level drops. Empty levels
    # carry no measurement, so drop them before comparing consecutive rungs.
    measured = [row["accuracy"] for row in levels if row["n"]]
    monotonic = all(
        measured[i] <= measured[i - 1] for i in range(1, len(measured))
    )

    return {
        "levels": levels,
        "overall": {
            "n": total_n,
            "correct": total_correct,
            "accuracy": _accuracy(total_correct, total_n),
        },
        "monotonic": monotonic,
    }
