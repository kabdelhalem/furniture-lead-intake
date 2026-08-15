"""
Tests for the calibration report (`src/calibration.py`).

`reliability()` answers "is the pipeline's confidence honest?" — of the fields it
marked `certain`, how many were actually right? These tests build predicted
`CanonicalLead` objects by hand (no model, no cache, no corpus on disk) so every
level of the ladder can be populated deliberately and the monotonicity signal
exercised in both directions.

Predictions are built with `CanonicalLead.model_validate` on a nested dict so
pydantic runs the same string->date / string->enum / int coercions the real
pipeline's output carries. Confidence is set per path with an explicit level
string (`"certain"`, `"medium"`, ...), which `Extracted._coerce_confidence`
accepts — the 0..1 score trick some fixtures use only ever yields CERTAIN or
SEVERE and could never populate the mid-ladder buckets these tests need.
"""

from __future__ import annotations

import re
from datetime import date

from src.calibration import reliability
from src.schema import CanonicalLead


# --------------------------------------------------------------------------
# Hand-built predictor construction
# --------------------------------------------------------------------------

def _tokens(path: str) -> list:
    """`line_items[0].quantity` -> ['line_items', 0, 'quantity']."""
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
    """Turn the working tree into a model-validatable dict: an all-int-keyed
    sub-dict is a list of positions (gaps filled with `{}`)."""
    if isinstance(node, dict):
        if node and all(isinstance(k, int) for k in node):
            return [_to_model_dict(node.get(i, {})) for i in range(max(node) + 1)]
        return {k: _to_model_dict(v) for k, v in node.items()}
    return node


def make_lead(pred: dict[str, tuple], *, lead_id: str = "LTEST") -> CanonicalLead:
    """Build a `CanonicalLead` from `{path: (value, level)}`.

    `value` is the *predicted* value (may differ from the truth to model a
    mistake); `level` is the predicted confidence level string.
    """
    tree: dict = {}
    for path, (value, level) in pred.items():
        toks = _tokens(path)
        cur = tree
        for i, tok in enumerate(toks):
            if i == len(toks) - 1:
                cur[tok] = {"value": value, "confidence": level}
            else:
                cur = cur.setdefault(tok, {})
    nested = _to_model_dict(tree)
    nested["lead_id"] = lead_id
    nested["received_at"] = "2026-08-14T00:00:00"
    return CanonicalLead.model_validate(nested)


def _truth(fields: dict, *, lead_id: str = "LTEST", curated: bool = True) -> dict:
    return {"lead_id": lead_id, "fields": fields, "curated": curated}


def _by_level(out: dict) -> dict[str, dict]:
    return {row["level"]: row for row in out["levels"]}


# --------------------------------------------------------------------------
# Structural guarantees
# --------------------------------------------------------------------------

def test_levels_always_five_rows_in_ladder_order():
    out = reliability({}, {})
    assert [row["level"] for row in out["levels"]] == [
        "certain", "high", "medium", "low", "severe",
    ]


def test_empty_input_reports_none_accuracy_and_vacuous_monotonic():
    out = reliability({}, {})
    for row in out["levels"]:
        assert row["n"] == 0
        assert row["correct"] == 0
        assert row["accuracy"] is None
    assert out["overall"] == {"n": 0, "correct": 0, "accuracy": None}
    # No measured level can violate a non-increasing sequence.
    assert out["monotonic"] is True


# --------------------------------------------------------------------------
# A perfect predictor across mixed levels
# --------------------------------------------------------------------------

# One field at each ladder level, all predicted correctly. Includes a `date`
# field so `values_equal`'s date-normalization branch is actually exercised
# (truth holds an ISO string; the prediction carries a real `date` object).
_MIXED_FIELDS = {
    "customer.company_name":          "Northgate Labs",   # certain
    "customer.primary_contact.email": "d@northgate.com",  # high
    "project.requested_delivery":     "2026-10-15",       # medium
    "line_items[0].quantity":         12,                 # low
    "line_items[0].finish":           "walnut",           # severe
}
_MIXED_LEVELS = {
    "customer.company_name":          "certain",
    "customer.primary_contact.email": "high",
    "project.requested_delivery":     "medium",
    "line_items[0].quantity":         "low",
    "line_items[0].finish":           "severe",
}


def _perfect_pred(**level_overrides: str) -> dict:
    levels = {**_MIXED_LEVELS, **level_overrides}
    return {p: (v, levels[p]) for p, v in _MIXED_FIELDS.items()}


def test_perfect_predictor_every_nonempty_level_is_100pct_and_monotonic():
    lead = make_lead(_perfect_pred())
    out = reliability({"LTEST": lead}, {"LTEST": _truth(_MIXED_FIELDS)})

    rows = _by_level(out)
    for name in ("certain", "high", "medium", "low", "severe"):
        assert rows[name]["n"] == 1, name
        assert rows[name]["correct"] == 1, name
        assert rows[name]["accuracy"] == 1.0, name
    assert out["overall"] == {"n": 5, "correct": 5, "accuracy": 1.0}
    assert out["monotonic"] is True


def test_date_field_uses_eval_comparison():
    # The prediction is a real date; truth is an ISO string. Only values_equal's
    # _norm branch makes these compare equal — confirm calibration reuses it.
    lead = make_lead(_perfect_pred())
    assert isinstance(lead.project.requested_delivery.value, date)
    out = reliability({"LTEST": lead}, {"LTEST": _truth(_MIXED_FIELDS)})
    assert _by_level(out)["medium"]["accuracy"] == 1.0


# --------------------------------------------------------------------------
# Miscalibration: wrong at a high level, right at a lower one -> non-monotonic
# --------------------------------------------------------------------------

def test_wrong_at_certain_drops_accuracy_and_trips_monotonic():
    # Two `certain` fields, one of them wrong -> certain accuracy 0.5.
    # One `medium` field, correct -> medium accuracy 1.0.
    # 0.5 then 1.0 is an *increase* down the ladder: miscalibration detected.
    fields = {
        "customer.company_name":          "Northgate Labs",
        "customer.primary_contact.email": "d@northgate.com",
        "line_items[0].finish":           "walnut",
    }
    pred = {
        "customer.company_name":          ("Northgate Labs", "certain"),   # right
        "customer.primary_contact.email": ("WRONG@x.com", "certain"),      # wrong
        "line_items[0].finish":           ("walnut", "medium"),            # right
    }
    out = reliability({"LTEST": make_lead(pred)}, {"LTEST": _truth(fields)})

    rows = _by_level(out)
    assert rows["certain"] == {"level": "certain", "n": 2, "correct": 1, "accuracy": 0.5}
    assert rows["medium"] == {"level": "medium", "n": 1, "correct": 1, "accuracy": 1.0}
    assert out["monotonic"] is False
    assert out["overall"] == {"n": 3, "correct": 2, "accuracy": 2 / 3}


def test_well_ordered_accuracy_stays_monotonic():
    # certain 1.0, low 0.5 -> non-increasing -> monotonic holds even with a miss.
    fields = {
        "customer.company_name":  "Northgate Labs",
        "line_items[0].quantity": 12,
        "line_items[0].finish":   "walnut",
    }
    pred = {
        "customer.company_name":  ("Northgate Labs", "certain"),  # right
        "line_items[0].quantity": (12, "low"),                    # right
        "line_items[0].finish":   ("oak", "low"),                 # wrong
    }
    out = reliability({"LTEST": make_lead(pred)}, {"LTEST": _truth(fields)})

    rows = _by_level(out)
    assert rows["certain"]["accuracy"] == 1.0
    assert rows["low"] == {"level": "low", "n": 2, "correct": 1, "accuracy": 0.5}
    assert out["monotonic"] is True


# --------------------------------------------------------------------------
# Empty levels never break monotonicity
# --------------------------------------------------------------------------

def test_empty_levels_are_skipped_when_checking_monotonicity():
    # Only certain (1.0) and severe (0.0) are populated; the three middle rungs
    # are empty. A gap must not read as an increase.
    fields = {
        "customer.company_name":  "Northgate Labs",
        "line_items[0].finish":   "walnut",
    }
    pred = {
        "customer.company_name":  ("Northgate Labs", "certain"),  # right
        "line_items[0].finish":   ("oak", "severe"),              # wrong
    }
    out = reliability({"LTEST": make_lead(pred)}, {"LTEST": _truth(fields)})

    rows = _by_level(out)
    assert rows["certain"]["accuracy"] == 1.0
    for name in ("high", "medium", "low"):
        assert rows[name]["n"] == 0
        assert rows[name]["accuracy"] is None
    assert rows["severe"]["accuracy"] == 0.0
    assert out["monotonic"] is True


def test_empty_bucket_accuracy_is_none_not_zero():
    fields = {"customer.company_name": "Northgate Labs"}
    pred = {"customer.company_name": ("Northgate Labs", "certain")}
    out = reliability({"LTEST": make_lead(pred)}, {"LTEST": _truth(fields)})

    rows = _by_level(out)
    # Distinguish "unmeasured" (None) from "measured, all wrong" (0.0): an
    # `assert not accuracy` would pass for both, which is the exact bug the
    # contract calls out, so assert identity to None explicitly.
    assert rows["high"]["accuracy"] is None
    assert rows["high"]["accuracy"] is not False  # None, never a falsy 0.0


# --------------------------------------------------------------------------
# Curated filter and missing-prediction handling
# --------------------------------------------------------------------------

def test_curated_false_lead_is_ignored_sibling_still_counted():
    curated = _truth(
        {"customer.company_name": "Northgate Labs"}, lead_id="L001", curated=True
    )
    volume = _truth(
        {"customer.company_name": "Volume Co"}, lead_id="V001", curated=False
    )
    predicted = {
        "L001": make_lead(
            {"customer.company_name": ("Northgate Labs", "certain")}, lead_id="L001"
        ),
        # A perfectly-predicted volume lead — if it counted, `certain.n` would
        # be 2. It must stay out of the report entirely.
        "V001": make_lead(
            {"customer.company_name": ("Volume Co", "certain")}, lead_id="V001"
        ),
    }
    out = reliability(predicted, {"L001": curated, "V001": volume})

    rows = _by_level(out)
    # Two-sided: the curated sibling IS counted, the volume lead is NOT.
    assert rows["certain"]["n"] == 1
    assert out["overall"]["n"] == 1


def test_curated_defaults_to_true_when_key_absent():
    # Real ground-truth records omit the `curated` key; those must be scored.
    truth = {"lead_id": "L001", "fields": {"customer.company_name": "Northgate Labs"}}
    pred = {"L001": make_lead(
        {"customer.company_name": ("Northgate Labs", "certain")}, lead_id="L001"
    )}
    out = reliability(pred, {"L001": truth})
    assert out["overall"]["n"] == 1


def test_missing_predicted_lead_is_skipped():
    truth = _truth({"customer.company_name": "Northgate Labs"}, lead_id="L001")
    # Nothing predicted for L001 -> skipped, like eval.evaluate.
    out = reliability({}, {"L001": truth})
    assert out["overall"]["n"] == 0
    assert out["monotonic"] is True


def test_meta_keys_are_never_bucketed():
    truth = _truth(
        {
            "customer.company_name": "Northgate Labs",
            "_review.status": "approved",
            "_routing.segment": "enterprise",
        },
        lead_id="L001",
    )
    pred = {"L001": make_lead(
        {"customer.company_name": ("Northgate Labs", "certain")}, lead_id="L001"
    )}
    out = reliability(pred, {"L001": truth})
    # Only the one real field is bucketed; the two `_` keys are ignored.
    assert out["overall"]["n"] == 1


def test_absent_envelope_falls_back_to_severe():
    # Truth labels a path the prediction has no envelope for. It must still be
    # bucketed (as severe), not dropped from the denominator, and counts as a
    # miss because the value is absent.
    truth = _truth({"line_items[0].matched_sku": "OAK-72-DESK"}, lead_id="L001")
    # A lead with no line items at all -> no matched_sku envelope.
    pred = {"L001": make_lead(
        {"customer.company_name": ("Northgate Labs", "certain")}, lead_id="L001"
    )}
    out = reliability(pred, {"L001": truth})

    rows = _by_level(out)
    assert rows["severe"]["n"] == 1
    assert rows["severe"]["correct"] == 0
    assert rows["severe"]["accuracy"] == 0.0
