"""
Calibration observability from human review outcomes.

Every reviewed field carries enough to close the confidence loop without a
separate event log: after review a field keeps its original `confidence`, its
status records what the human did (`HUMAN_CORRECTED` / `HUMAN_CONFIRMED`), and
`threshold_for(path)` says what the auto-commit bar was — so whether we *flagged*
the field is recoverable as `confidence < threshold`.

That yields the two signals that tell you which sliders to move:

- **False auto-commit** — a field we auto-committed (didn't flag) that the human
  *corrected*. We were confidently wrong; the field class's minimum level is too
  LOW. Tighten it.
- **Over-flag** — a field we flagged that the human *confirmed* as-is. We made a
  human look at something we had right; the bar is too HIGH. Loosen it.

This is the online counterpart of the offline calibration check: the corpus eval
asks "is confidence below threshold where it should be"; this asks the same of
real review outcomes and recommends a threshold move per field class.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .schema import (
    CanonicalLead,
    Confidence,
    FieldStatus,
    iter_extracted,
    threshold_for,
)

_REVIEWED = (FieldStatus.HUMAN_CORRECTED, FieldStatus.HUMAN_CONFIRMED)


def _generic(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def _suggestion(false_auto: int, over_flag: int, confirmed: int) -> str:
    """Which way to move this field class's minimum level."""
    if false_auto > 0:
        return "tighten"    # auto-committed fields were corrected -> raise the bar
    if over_flag > 0 and over_flag >= max(1, confirmed // 2):
        return "loosen"     # flagged fields keep getting confirmed -> lower the bar
    return "ok"


def summarize(leads: list[CanonicalLead]) -> dict:
    """Aggregate review outcomes into per-field-class calibration signal."""
    classes: dict[str, dict] = defaultdict(
        lambda: {"reviewed": 0, "corrected": 0, "confirmed": 0,
                 "false_auto_commits": 0, "over_flags": 0}
    )
    reason_codes: Counter = Counter()

    for lead in leads:
        for path, field in iter_extracted(lead):
            if field.status not in _REVIEWED:
                continue
            c = classes[_generic(path)]
            c["reviewed"] += 1
            was_flagged = field.confidence < threshold_for(path)
            if field.status is FieldStatus.HUMAN_CORRECTED:
                c["corrected"] += 1
                if not was_flagged:
                    c["false_auto_commits"] += 1     # confidently wrong
            else:  # HUMAN_CONFIRMED
                c["confirmed"] += 1
                if was_flagged:
                    c["over_flags"] += 1             # flagged but fine
        for corr in lead.review.corrections:
            if corr.reason_code:
                reason_codes[corr.reason_code] += 1

    totals = {"reviewed_fields": 0, "corrections": 0, "confirmations": 0,
              "false_auto_commits": 0, "over_flags": 0}
    by_class: dict[str, dict] = {}
    for gp, c in sorted(classes.items()):
        totals["reviewed_fields"] += c["reviewed"]
        totals["corrections"] += c["corrected"]
        totals["confirmations"] += c["confirmed"]
        totals["false_auto_commits"] += c["false_auto_commits"]
        totals["over_flags"] += c["over_flags"]
        by_class[gp] = {
            **{k: c[k] for k in ("reviewed", "corrected", "confirmed",
                                 "false_auto_commits", "over_flags")},
            "current_min_level": threshold_for(gp).value,
            "suggestion": _suggestion(c["false_auto_commits"], c["over_flags"], c["confirmed"]),
        }

    return {**totals, "by_field_class": by_class, "reason_codes": dict(reason_codes)}
