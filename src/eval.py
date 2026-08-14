"""
Eval harness: score predicted leads against the ground-truth corpus.

The corpus is authored truth-first (see `src/corpus/specs.py`), so its labels
are correct by construction. This module diffs an already-predicted
`CanonicalLead` against those labels along two axes:

1. **Field accuracy** — for every labelled path, does the predicted value match?
   Floats compare with a tolerance; enums compare by value; a truth value of
   `None` means "the correct answer is null", and predicting anything non-null
   there is a *hard* failure (the hallucination guard behind L011).

2. **Calibration** — for every path the corpus marks as `expect_low_confidence`,
   is the predicted confidence actually *below* that path's review threshold? A
   model that is confidently right on a field it was supposed to be unsure about
   is getting lucky; confidently wrong there is dangerous. Either way the
   calibration is off, and that is a finding independent of raw accuracy.

The harness takes leads that are already predicted, so it runs without the
extraction pipeline: feed it `CanonicalLead` objects and a corpus directory.

    python -m src.eval --corpus ./corpus
"""

from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from .schema import (
    CanonicalLead,
    flatten_confidences,
    flatten_values,
    threshold_for,
)


# --------------------------------------------------------------------------
# Result records
# --------------------------------------------------------------------------

@dataclass
class FieldResult:
    """One labelled field: what we expected, what we got, and whether it matched."""
    path: str
    expected: Any
    got: Any
    ok: bool
    hard_fail: bool = False   # truth was None but the prediction invented a value


@dataclass
class CalibrationResult:
    """One `expect_low_confidence` path: confidence must sit below its threshold."""
    path: str
    confidence: float
    threshold: float
    ok: bool               # confidence < threshold
    present: bool = True    # False -> the path had no envelope in the prediction


@dataclass
class MetaResult:
    """A truth key under `_` (e.g. `_review.status`). Informational, not scored."""
    path: str
    expected: Any


@dataclass
class LeadScore:
    lead_id: str
    fields_total: int
    fields_correct: int
    field_results: list[FieldResult] = field(default_factory=list)
    calibration: list[CalibrationResult] = field(default_factory=list)
    meta: list[MetaResult] = field(default_factory=list)
    predicted_missing: bool = False

    @property
    def field_accuracy(self) -> float:
        return self.fields_correct / self.fields_total if self.fields_total else 1.0

    @property
    def hard_failures(self) -> list[FieldResult]:
        return [r for r in self.field_results if r.hard_fail]

    @property
    def calibration_passed(self) -> int:
        return sum(1 for c in self.calibration if c.ok)

    @property
    def calibration_pass_rate(self) -> float:
        return self.calibration_passed / len(self.calibration) if self.calibration else 1.0


@dataclass
class GateCheck:
    """A pass/fail gate a specific lead must clear regardless of field accuracy.

    `ok=None` means the check could not run because the lead was not predicted —
    reported as *skipped*, never silently dropped (an absent gate is not a pass).
    """
    name: str
    lead_id: str
    ok: bool | None
    detail: str


@dataclass
class EvalReport:
    lead_scores: dict[str, LeadScore] = field(default_factory=dict)
    gate_checks: list[GateCheck] = field(default_factory=list)
    missing_predictions: list[str] = field(default_factory=list)

    # ---- field accuracy, micro-averaged over every labelled field ----
    @property
    def fields_total(self) -> int:
        return sum(s.fields_total for s in self.lead_scores.values())

    @property
    def fields_correct(self) -> int:
        return sum(s.fields_correct for s in self.lead_scores.values())

    @property
    def field_accuracy(self) -> float:
        return self.fields_correct / self.fields_total if self.fields_total else 1.0

    # ---- calibration, micro-averaged over every expected-uncertain path ----
    @property
    def calibration_total(self) -> int:
        return sum(len(s.calibration) for s in self.lead_scores.values())

    @property
    def calibration_passed(self) -> int:
        return sum(s.calibration_passed for s in self.lead_scores.values())

    @property
    def calibration_pass_rate(self) -> float:
        return self.calibration_passed / self.calibration_total if self.calibration_total else 1.0

    @property
    def calibration_absent_paths(self) -> int:
        """Expected-uncertain paths that had no envelope in the prediction.

        These pass calibration trivially (confidence 0.0 < threshold); surfaced
        separately so an absent-path pass is not laundered into the pass rate.
        """
        return sum(1 for s in self.lead_scores.values() for c in s.calibration if not c.present)

    @property
    def gates_failed(self) -> list[GateCheck]:
        return [g for g in self.gate_checks if g.ok is False]


# --------------------------------------------------------------------------
# Value comparison
# --------------------------------------------------------------------------

_FLOAT_TOL = 0.01


def _norm(v: Any) -> Any:
    """Coerce dates and enums to their comparable primitive form.

    Truth JSON stores dates as ISO strings and enums as their `.value`; a
    predicted `CanonicalLead` carries real `date`/`Enum` objects. Normalize both
    sides to the same representation before comparing.
    """
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    return v


def values_equal(expected: Any, got: Any) -> bool:
    """True if `got` matches `expected` under the eval's comparison rules.

    - `None` expected -> only `None` matches (hallucination guard).
    - floats/ints -> equal within `_FLOAT_TOL` (bools excluded, compared exactly).
    - enums -> by value; dates -> by ISO string; everything else -> `==`.
    """
    if expected is None:
        return got is None
    if got is None:
        return False

    e, g = _norm(expected), _norm(got)

    # bool is a subclass of int — keep it out of the numeric-tolerance branch.
    if isinstance(e, bool) or isinstance(g, bool):
        return e == g

    if isinstance(e, (int, float)) and isinstance(g, (int, float)):
        return abs(e - g) <= _FLOAT_TOL

    return e == g


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def score_lead(predicted: CanonicalLead, truth: dict) -> LeadScore:
    """Score one predicted lead against its ground-truth record.

    `truth` is the full ground-truth JSON dict (with `fields`,
    `expect_low_confidence`, `channel`, ...), not just the field map.
    """
    lead_id = truth.get("lead_id", getattr(predicted, "lead_id", ""))
    fields: dict[str, Any] = truth.get("fields", {})

    values = flatten_values(predicted)
    confidences = flatten_confidences(predicted)

    field_results: list[FieldResult] = []
    meta: list[MetaResult] = []
    correct = 0

    for path, expected in fields.items():
        # Keys under `_` (e.g. _review.status, _routing.segment) label plain
        # non-Extracted state; they are informational, not field accuracy.
        if path.startswith("_"):
            meta.append(MetaResult(path=path, expected=expected))
            continue

        got = values.get(path)
        ok = values_equal(expected, got)
        hard_fail = expected is None and got is not None
        field_results.append(
            FieldResult(path=path, expected=expected, got=got, ok=ok, hard_fail=hard_fail)
        )
        if ok:
            correct += 1

    calibration: list[CalibrationResult] = []
    for path in truth.get("expect_low_confidence", []):
        present = path in confidences
        conf = confidences.get(path, 0.0)
        thr = threshold_for(path)
        calibration.append(
            CalibrationResult(
                path=path, confidence=conf, threshold=thr, ok=conf < thr, present=present
            )
        )

    return LeadScore(
        lead_id=lead_id,
        fields_total=len(field_results),
        fields_correct=correct,
        field_results=field_results,
        calibration=calibration,
        meta=meta,
    )


# --------------------------------------------------------------------------
# Corpus loading + aggregate evaluation
# --------------------------------------------------------------------------

def load_truths(corpus_dir: pathlib.Path) -> dict[str, dict]:
    """Load `corpus_dir/ground_truth/*.json` keyed by lead_id."""
    truth_dir = pathlib.Path(corpus_dir) / "ground_truth"
    if not truth_dir.is_dir():
        raise FileNotFoundError(
            f"no ground_truth/ under {corpus_dir} — run "
            f"`python -m src.corpus.generate --out {corpus_dir}` first"
        )
    truths: dict[str, dict] = {}
    for path in sorted(truth_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        truths[data.get("lead_id", path.stem)] = data
    return truths


# Per-lead gates that must hold regardless of aggregate field accuracy. These
# are the two the corpus leans on hardest: declining to answer (L011) and
# declining to treat a non-lead as a lead (L013).

def _gate_l011(pred: CanonicalLead) -> GateCheck:
    got = flatten_values(pred).get("line_items[0].quantity")
    return GateCheck(
        name="L011_quantity_null",
        lead_id="L011",
        ok=got is None,
        detail=f"line_items[0].quantity = {got!r} (must be None — no qty stated in source)",
    )


def _gate_l013(pred: CanonicalLead) -> GateCheck:
    got = flatten_values(pred).get("is_lead")
    return GateCheck(
        name="L013_not_a_lead",
        lead_id="L013",
        ok=got is False,
        detail=f"is_lead = {got!r} (must be False — AP dispute, not a lead)",
    )


_GATES = {"L011": _gate_l011, "L013": _gate_l013}


def evaluate(
    predicted: dict[str, CanonicalLead], corpus_dir: pathlib.Path
) -> EvalReport:
    """Score every predicted lead against the corpus and aggregate.

    Leads present in the corpus but absent from `predicted` are recorded in
    `missing_predictions` and skipped, so calling with `{}` yields a pure
    coverage view of the truth set.
    """
    truths = load_truths(corpus_dir)
    report = EvalReport()

    for lead_id, truth in truths.items():
        pred = predicted.get(lead_id)
        if pred is None:
            report.missing_predictions.append(lead_id)
            continue
        report.lead_scores[lead_id] = score_lead(pred, truth)

    for lead_id, gate in _GATES.items():
        pred = predicted.get(lead_id)
        if pred is None:
            report.gate_checks.append(
                GateCheck(name=f"{lead_id}_gate", lead_id=lead_id, ok=None,
                          detail="skipped — no prediction supplied")
            )
        else:
            report.gate_checks.append(gate(pred))

    return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_coverage(truths: dict[str, dict]) -> None:
    n_fields = sum(
        sum(1 for k in t.get("fields", {}) if not k.startswith("_")) for t in truths.values()
    )
    n_flags = sum(len(t.get("expect_low_confidence", [])) for t in truths.values())
    print(f"{len(truths)} leads · {n_fields} labelled fields · "
          f"{n_flags} expected-uncertain fields\n")
    for lead_id, t in truths.items():
        scored = sum(1 for k in t.get("fields", {}) if not k.startswith("_"))
        flags = len(t.get("expect_low_confidence", []))
        print(f"  {lead_id}  {t.get('label', ''):<34} "
              f"{scored:>3} fields  {flags} uncertain")


def _print_report(report: EvalReport) -> None:
    print(f"field accuracy      {report.fields_correct}/{report.fields_total} "
          f"= {report.field_accuracy:.1%}")
    print(f"calibration         {report.calibration_passed}/{report.calibration_total} "
          f"= {report.calibration_pass_rate:.1%}"
          + (f"  ({report.calibration_absent_paths} absent-path)"
             if report.calibration_absent_paths else ""))
    print("\nper lead:")
    for lead_id, s in sorted(report.lead_scores.items()):
        hard = f"  HARD-FAIL x{len(s.hard_failures)}" if s.hard_failures else ""
        print(f"  {lead_id}  {s.fields_correct}/{s.fields_total} "
              f"= {s.field_accuracy:>5.0%}  calib {s.calibration_passed}/{len(s.calibration)}{hard}")
    if report.missing_predictions:
        print(f"\nno prediction for: {', '.join(sorted(report.missing_predictions))}")
    print("\ngates:")
    for g in report.gate_checks:
        mark = "skip" if g.ok is None else ("pass" if g.ok else "FAIL")
        print(f"  [{mark}] {g.name}: {g.detail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="./corpus", type=pathlib.Path,
                    help="corpus dir containing ground_truth/ (default ./corpus)")
    args = ap.parse_args(argv)

    truths = load_truths(args.corpus)

    # No pipeline exists yet, so there are no predictions to score from the CLI.
    # Report coverage of the truth set; real scoring runs through evaluate() with
    # predicted leads (covered by the test suite).
    print("no predictions supplied — coverage only\n")
    _print_coverage(truths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
