"""
Tests for the eval harness.

Run from the repo root so the `src` package resolves:

    python -m pytest tests/test_eval.py

The corpus is generated on demand into `./corpus` if it is not already present.

Tests build a *perfect predictor*: a `CanonicalLead` assembled from a
ground-truth record so that its flattened values equal the truth exactly. It is
built with `CanonicalLead.model_validate` on a nested dict — not by poking
`.value` attributes — so pydantic performs the same string->date, string->enum,
int coercions the real pipeline's output would carry. A perfect predictor must
score 100%; perturbing one field must drop below it.
"""

from __future__ import annotations

import copy
import pathlib
import re
from datetime import date

import pytest

from src.eval import (
    CalibrationResult,
    EvalReport,
    LeadScore,
    evaluate,
    load_truths,
    score_lead,
    values_equal,
)
from src.schema import (
    CanonicalLead,
    Channel,
    Confidence,
    CustomerType,
    UnitSystem,
    flatten_confidences,
    flatten_values,
    threshold_for,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory) -> pathlib.Path:
    # Curated-only corpus (the 15 scored leads). Renders byte-identically to the
    # real corpus, so it still hits the committed cache; isolated + deterministic.
    d = tmp_path_factory.mktemp("corpus")
    from src.corpus.generate import generate
    generate(d, synthetic=0)
    return d


@pytest.fixture(scope="session")
def truths(corpus_dir: pathlib.Path) -> dict[str, dict]:
    return load_truths(corpus_dir)


# --------------------------------------------------------------------------
# Perfect-predictor construction
# --------------------------------------------------------------------------

def _tokens(path: str) -> list:
    """`line_items[0].dimensions.width_in` -> ['line_items', 0, 'dimensions', 'width_in']."""
    out: list = []
    for seg in path.split("."):
        m = re.match(r"^(\w+)\[(\d+)\]$", seg)
        if m:
            out.append(m.group(1))
            out.append(int(m.group(2)))
        else:
            out.append(seg)
    return out


def _to_model_dict(node):
    """Convert the working tree into a model-validatable dict.

    A sub-dict whose keys are all ints represents list positions and becomes a
    list (gaps filled with `{}`). Leaf `Extracted` dicts (`value`/`confidence`)
    pass through untouched.
    """
    if isinstance(node, dict):
        if node and all(isinstance(k, int) for k in node):
            return [_to_model_dict(node.get(i, {})) for i in range(max(node) + 1)]
        return {k: _to_model_dict(v) for k, v in node.items()}
    return node


def build_lead(
    truth: dict,
    *,
    high: float = 0.99,
    low: float = 0.10,
    lead_id: str | None = None,
) -> CanonicalLead:
    """Assemble a `CanonicalLead` whose flattened values equal `truth['fields']`.

    Confidence is `low` for paths in `expect_low_confidence` (so calibration
    passes) and `high` elsewhere (above every threshold, so those auto-commit).
    """
    fields: dict = truth.get("fields", {})
    low_paths = set(truth.get("expect_low_confidence", []))

    tree: dict = {}
    for path, value in fields.items():
        if path.startswith("_"):
            continue
        conf = low if path in low_paths else high
        cur = tree
        toks = _tokens(path)
        for i, tok in enumerate(toks):
            if i == len(toks) - 1:
                cur[tok] = {"value": value, "confidence": conf}
            else:
                cur = cur.setdefault(tok, {})

    nested = _to_model_dict(tree)
    nested["lead_id"] = lead_id or truth.get("lead_id", "LTEST")
    nested["received_at"] = "2026-08-14T00:00:00"
    return CanonicalLead.model_validate(nested)


def _truth_with(truth: dict, overrides: dict) -> dict:
    """A copy of `truth` with `fields` updated by `overrides`."""
    t = copy.deepcopy(truth)
    t["fields"].update(overrides)
    return t


# --------------------------------------------------------------------------
# The builder must trigger real coercion (not store raw strings)
# --------------------------------------------------------------------------

def test_builder_coerces_dates_enums_and_ints(truths):
    lead = build_lead(truths["L001"])
    assert isinstance(lead.channel.value, Channel)
    assert isinstance(lead.customer.customer_type.value, CustomerType)
    assert isinstance(lead.project.requested_delivery.value, date)
    assert isinstance(lead.line_items[0].quantity.value, int)


def test_builder_coerces_metric_unit_enum(truths):
    lead = build_lead(truths["L008"])
    assert lead.line_items[0].dimensions.source_units.value is UnitSystem.METRIC


# --------------------------------------------------------------------------
# values_equal — comparison rules
# --------------------------------------------------------------------------

def test_values_equal_float_tolerance():
    # 1800mm / 25.4 = 70.8661..., truth rounds to 70.87 -> within tolerance.
    assert values_equal(70.87, 1800 / 25.4)
    # A tenth of an inch off is outside tolerance.
    assert not values_equal(70.87, 70.9)


def test_values_equal_none_semantics():
    assert values_equal(None, None)          # correct: answer is null, predicted null
    assert not values_equal(None, 5)         # hard fail: invented a value
    assert not values_equal(8, None)         # missed a real value


def test_values_equal_enum_and_date():
    assert values_equal("email", Channel.EMAIL)
    assert values_equal("metric", UnitSystem.METRIC)
    assert values_equal("2026-10-15", date(2026, 10, 15))
    assert values_equal(date(2026, 10, 15), "2026-10-15")


def test_values_equal_bool_not_treated_as_number():
    assert values_equal(True, True)
    assert not values_equal(True, False)
    # True == 1 in Python; the comparator must not launder a bool into a number.
    assert not values_equal(True, 2)


def test_values_equal_list_fallback():
    # `options` is the one Extracted[list[str]] field; lists fall through to ==.
    assert values_equal(["a", "b"], ["a", "b"])
    assert not values_equal(["a", "b"], ["b", "a"])


# --------------------------------------------------------------------------
# score_lead — perfect predictor
# --------------------------------------------------------------------------

def test_perfect_predictor_scores_100_every_lead(truths):
    for lead_id, truth in truths.items():
        score = score_lead(build_lead(truth), truth)
        assert score.fields_correct == score.fields_total, lead_id
        assert score.field_accuracy == 1.0, lead_id
        assert score.hard_failures == [], lead_id
        assert all(r.ok for r in score.field_results), lead_id


def test_perfect_predictor_calibration_passes(truths):
    for lead_id, truth in truths.items():
        if not truth.get("expect_low_confidence"):
            continue
        score = score_lead(build_lead(truth), truth)
        assert score.calibration, lead_id
        assert all(c.ok for c in score.calibration), lead_id
        assert all(c.present for c in score.calibration), lead_id


# --------------------------------------------------------------------------
# score_lead — perturbations drop below 100%
# --------------------------------------------------------------------------

def test_perturb_one_field_drops_below_100(truths):
    truth = truths["L001"]
    bad = build_lead(_truth_with(truth, {"customer.primary_contact.email": "wrong@example.com"}))
    score = score_lead(bad, truth)

    assert score.fields_correct == score.fields_total - 1
    assert score.field_accuracy < 1.0
    failed = [r for r in score.field_results if not r.ok]
    assert len(failed) == 1
    assert failed[0].path == "customer.primary_contact.email"
    assert failed[0].expected == "dwhitfield@northgatelabs.com"
    assert failed[0].got == "wrong@example.com"


def test_perturb_quantity_within_none_case_is_hard_fail(truths):
    # L011: the only correct quantity is None; predicting a number is a hard fail.
    truth = truths["L011"]
    bad = build_lead(_truth_with(truth, {"line_items[0].quantity": 10}))
    score = score_lead(bad, truth)

    qty = next(r for r in score.field_results if r.path == "line_items[0].quantity")
    assert qty.ok is False
    assert qty.hard_fail is True
    assert score.hard_failures == [qty]
    # _truth_with must deep-copy: the session-scoped `truths` fixture is shared
    # across every test, so an in-place mutation would silently corrupt labels.
    assert truths["L011"]["fields"]["line_items[0].quantity"] is None


def test_l011_predicting_none_is_correct(truths):
    truth = truths["L011"]
    score = score_lead(build_lead(truth), truth)
    qty = next(r for r in score.field_results if r.path == "line_items[0].quantity")
    assert qty.got is None
    assert qty.ok is True
    assert qty.hard_fail is False


# --------------------------------------------------------------------------
# Calibration — confidently right/wrong on an expected-uncertain field
# --------------------------------------------------------------------------

def test_confidently_right_on_uncertain_field_fails_calibration(truths):
    # L011's quantity is expected-uncertain. A prediction that is correct (None)
    # but *confident* still fails calibration — being right there is luck.
    truth = truths["L011"]
    over_confident = build_lead(truth, low=0.99)  # force high confidence everywhere
    score = score_lead(over_confident, truth)

    cal = next(c for c in score.calibration if c.path == "line_items[0].quantity")
    assert cal.confidence >= cal.threshold
    assert cal.ok is False
    # ...yet the value itself is still scored correct.
    qty = next(r for r in score.field_results if r.path == "line_items[0].quantity")
    assert qty.ok is True


def test_calibration_absent_path_is_present_false_but_passes():
    # An expected-uncertain path with no envelope in the prediction: trivially
    # below threshold (confidence 0.0), but flagged present=False.
    truth = {
        "lead_id": "LX",
        "fields": {"customer.company_name": "Acme"},
        "expect_low_confidence": ["line_items[0].quantity"],
    }
    lead = build_lead(truth)
    assert "line_items[0].quantity" not in flatten_confidences(lead)
    score = score_lead(lead, truth)
    cal = score.calibration[0]
    assert cal.present is False
    assert cal.ok is True
    assert cal.confidence is Confidence.SEVERE


def test_calibration_threshold_comes_from_schema(truths):
    # Sanity: the harness uses the schema's per-path thresholds, not a constant.
    truth = truths["L006"]
    score = score_lead(build_lead(truth), truth)
    by_path = {c.path: c for c in score.calibration}
    assert by_path["line_items[0].quantity"].threshold == threshold_for("line_items[0].quantity")
    assert by_path["project.requested_delivery"].threshold == threshold_for("project.requested_delivery")


# --------------------------------------------------------------------------
# Meta (`_`) keys — excluded from field accuracy, exposed separately
# --------------------------------------------------------------------------

def test_meta_keys_excluded_from_field_accuracy(truths):
    # L012 carries _review.status / _review.duplicate_of; L015 carries _routing.segment.
    for lead_id in ("L012", "L015"):
        truth = truths[lead_id]
        score = score_lead(build_lead(truth), truth)
        assert not any(r.path.startswith("_") for r in score.field_results), lead_id
        meta_paths = {m.path for m in score.meta}
        assert meta_paths == {k for k in truth["fields"] if k.startswith("_")}
        # Still a perfect score on the real (non-underscore) fields.
        assert score.field_accuracy == 1.0, lead_id


# --------------------------------------------------------------------------
# evaluate — aggregation, gates, missing predictions
# --------------------------------------------------------------------------

def test_evaluate_perfect_corpus(truths, corpus_dir):
    from src.dedup import mark_duplicates
    predicted = {lid: build_lead(t) for lid, t in truths.items()}
    mark_duplicates(list(predicted.values()))   # dedup, as run_corpus does
    report = evaluate(predicted, corpus_dir)

    assert isinstance(report, EvalReport)
    assert report.field_accuracy == 1.0
    # Pinned to the corpus as generated from specs.py; a change to specs.py that
    # drops leads or labels from scoring should fail here loudly, not slip under
    # a loose bound.
    assert report.fields_total == 239
    assert report.calibration_pass_rate == 1.0
    assert report.calibration_total == 11
    assert report.missing_predictions == []
    assert report.gates_failed == []
    # All three named gates ran and passed.
    gate_ok = {g.name: g.ok for g in report.gate_checks}
    assert gate_ok["L011_quantity_null"] is True
    assert gate_ok["L012_deduplicated"] is True
    assert gate_ok["L013_not_a_lead"] is True


def test_evaluate_micro_average_matches_manual(truths, corpus_dir):
    predicted = {lid: build_lead(t) for lid, t in truths.items()}
    # Break exactly one field in one lead.
    predicted["L001"] = build_lead(
        _truth_with(truths["L001"], {"line_items[0].quantity": 999})
    )
    report = evaluate(predicted, corpus_dir)
    assert report.fields_correct == report.fields_total - 1
    assert 0.0 < report.field_accuracy < 1.0


def test_evaluate_empty_predictions_is_coverage_only(truths, corpus_dir):
    report = evaluate({}, corpus_dir)
    assert set(report.missing_predictions) == set(truths)
    assert report.lead_scores == {}
    assert report.fields_total == 0
    assert report.field_accuracy == 1.0        # vacuous, nothing scored
    # Gates are skipped, not silently passed.
    assert all(g.ok is None for g in report.gate_checks)


def test_gate_l011_fails_on_hallucinated_quantity(truths, corpus_dir):
    predicted = {"L011": build_lead(_truth_with(truths["L011"], {"line_items[0].quantity": 4}))}
    report = evaluate(predicted, corpus_dir)
    gate = next(g for g in report.gate_checks if g.name == "L011_quantity_null")
    assert gate.ok is False
    assert report.gates_failed == [gate]


def test_gate_l013_fails_when_nonlead_scored_as_lead(truths, corpus_dir):
    predicted = {"L013": build_lead(_truth_with(truths["L013"], {"is_lead": True}))}
    report = evaluate(predicted, corpus_dir)
    gate = next(g for g in report.gate_checks if g.name == "L013_not_a_lead")
    assert gate.ok is False


# --------------------------------------------------------------------------
# load_truths / CLI
# --------------------------------------------------------------------------

def test_load_truths_shape(truths):
    assert set(truths) >= {f"L{n:03d}" for n in range(1, 16)}
    l011 = truths["L011"]
    assert l011["fields"]["line_items[0].quantity"] is None
    assert l011["expect_low_confidence"] == ["line_items[0].quantity"]


def test_load_truths_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_truths(tmp_path)


def test_cli_main_coverage_only(corpus_dir, capsys):
    from src.eval import main
    rc = main(["--corpus", str(corpus_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "coverage only" in out
    assert "L011" in out


def test_print_report_formats_a_scored_report(truths, corpus_dir, capsys):
    # Directly cover the report formatter (unreachable from the CLI until a
    # pipeline can supply predictions).
    from src.eval import _print_report
    predicted = {lid: build_lead(t) for lid, t in truths.items()}
    predicted["L011"] = build_lead(
        _truth_with(truths["L011"], {"line_items[0].quantity": 3})  # trip the gate
    )
    _print_report(evaluate(predicted, corpus_dir))
    out = capsys.readouterr().out
    assert "field accuracy" in out
    assert "calibration" in out
    assert "gates:" in out
    assert "FAIL" in out          # the L011 gate line
    assert "HARD-FAIL" in out     # the hallucinated quantity
