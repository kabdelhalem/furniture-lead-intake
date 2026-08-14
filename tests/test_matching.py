"""
Tests for the fuzzy SKU matcher.

Two properties matter and they pull in opposite directions:

  1. Unambiguous descriptions must resolve to the *exact* SKU at HIGH
     confidence, even across the deliberate near-collisions in the catalog
     (MER-CT-*, the ASH-TSK-* family, KRN-BNC-4/6, STO-LAT-2/4, ...).
  2. A genuinely ambiguous description ("the big walnut conference table")
     must NOT pick one confidently — it must score LOW and hand the reviewer
     the tied alternatives.

The second property is the whole reason the module exists, so it gets an
explicit, load-bearing assertion.
"""

import os
import sys

import pytest

# Make the repo root importable so `from src...` works under a bare
# `pytest tests/test_matching.py` invocation as well as `python -m pytest`
# (the latter already puts CWD on sys.path). The repo intentionally ships no
# pytest config, so this keeps the tests runnable either way.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.matching import (
    AMBIGUOUS_CEILING,
    HIGH_CONFIDENCE,
    match_sku,
    nominal_inches,
)


# (description, expected_sku, kwargs) for the unambiguous acceptance cases.
EXACT_CASES = [
    ("Ashfield task chair, high-back, graphite", "ASH-TSK-30H", {}),
    ("Ashfield task chair (standard back), fog", "ASH-TSK-30", {}),
    ("Ashfield executive chair, leather", "ASH-TSK-40", {}),
    ("Kirion bench system, 6-pack, maple", "KRN-BNC-6", {}),
    ("Verano meeting pod, 4 person, slate", "VER-POD-4", {}),
    ("Verano focus pod single, oat", "VER-POD-1", {}),
    ("Trevose cafe table, 42in round", "TRV-CAF-42", {}),
    ("Trevose cafe table, 36 inch round", "TRV-CAF-36", {}),
    ("Trevose stacking chair", "TRV-STK", {}),
    ("Storwell lateral file, 4 high", "STO-LAT-4", {}),
    ('Verano acoustic panel 72"', "VER-PNL-72", {}),
    ("Havenwood lounge chair, COM", "HAV-LNG-1", {}),
    ("Havenwood ottoman", "HAV-OTT", {}),
    ("Orbit reception desk, double, concrete", "ORB-RCP-2", {}),
    ("Mobile pedestal, 3 drawer, white", "STO-PED-3", {}),
    # width pins a textually-weak desk description to a size
    ("Height-adjustable desk, laminate, white", "KRN-DSK-72", {"width_in": 70.87}),
]


@pytest.mark.parametrize("desc,expected,kwargs", EXACT_CASES)
def test_exact_cases_resolve_to_sku(desc, expected, kwargs):
    result = match_sku(desc, **kwargs)
    assert result.sku == expected, f"{desc!r} -> {result.sku} (expected {expected}); note={result.note}"


@pytest.mark.parametrize("desc,expected,kwargs", EXACT_CASES)
def test_exact_cases_are_high_confidence(desc, expected, kwargs):
    result = match_sku(desc, **kwargs)
    assert result.score >= HIGH_CONFIDENCE, (
        f"{desc!r} scored {result.score} < {HIGH_CONFIDENCE} — an unambiguous "
        f"match should be trusted, not sent to review"
    )


# --- the near-collision pairs, checked in both directions -------------------

def test_high_back_vs_standard_back():
    """The single distinguishing word must flip the winner."""
    assert match_sku("Ashfield task chair, high-back, graphite").sku == "ASH-TSK-30H"
    assert match_sku("Ashfield task chair (standard back), fog").sku == "ASH-TSK-30"
    # ...and a bare "task chair" should prefer the base model over the variant.
    assert match_sku("Ashfield task chair").sku == "ASH-TSK-30"


def test_bench_pack_size_disambiguated():
    assert match_sku("Kirion bench system, 4-pack, white").sku == "KRN-BNC-4"
    assert match_sku("Kirion bench system, 6-pack, maple").sku == "KRN-BNC-6"


def test_lateral_file_height_disambiguated():
    assert match_sku("Storwell lateral file, 2 high").sku == "STO-LAT-2"
    assert match_sku("Storwell lateral file, 4 high").sku == "STO-LAT-4"


def test_cafe_table_size_disambiguated():
    assert match_sku("Trevose cafe table, 36 inch round").sku == "TRV-CAF-36"
    assert match_sku("Trevose cafe table, 42in round").sku == "TRV-CAF-42"


def test_pod_variant_disambiguated():
    assert match_sku("Verano focus pod single, oat").sku == "VER-POD-1"
    assert match_sku("Verano meeting pod, 4 person, slate").sku == "VER-POD-4"


def test_acoustic_panel_size_disambiguated():
    assert match_sku('Verano acoustic panel 48"').sku == "VER-PNL-48"
    assert match_sku('Verano acoustic panel 72"').sku == "VER-PNL-72"


def test_reception_desk_single_vs_double():
    assert match_sku("Orbit reception desk, single, white").sku == "ORB-RCP-1"
    assert match_sku("Orbit reception desk, double, concrete").sku == "ORB-RCP-2"


def test_lounge_chair_vs_multiseat():
    """'lounge chair' is the 1-seat SKU, not the 2/3-seat sofas."""
    assert match_sku("Havenwood lounge chair, COM").sku == "HAV-LNG-1"
    assert match_sku("Havenwood lounge, 3 seat").sku == "HAV-LNG-3"
    assert match_sku("Havenwood lounge, 2-seat sofa").sku == "HAV-LNG-2"


# --- width as a tie-breaker -------------------------------------------------

def test_width_breaks_desk_tie():
    """
    A bare "height-adjustable desk" matches all three Kirion desks equally on
    text; only the width pins it to a size. 1800mm == 70.87in must land on the
    72" SKU (its nominal is 72), not the 60" one.
    """
    result = match_sku(
        "Height-adjustable desk, laminate, white", width_in=70.87
    )
    assert result.sku == "KRN-DSK-72"


def test_width_resolution_surfaces_the_size_siblings():
    """
    Resolving by width must not be *silent* (the L008 spirit): even when it picks
    a size confidently, the neighbouring desk sizes are offered as alternatives
    so a reviewer can see what the width decided between.
    """
    result = match_sku(
        "Height-adjustable desk, laminate, white", width_in=70.87
    )
    assert result.sku == "KRN-DSK-72"
    # the other two desks are offered as alternatives to a reviewer
    assert "KRN-DSK-60" in result.alternatives
    assert "KRN-DSK-48" in result.alternatives


# --- the load-bearing ambiguity case ---------------------------------------

def test_ambiguous_walnut_table_flags_not_guesses():
    """
    "the big walnut conference table" matches all four MER-CT-* rows equally
    (they differ only by a size the description never states). The correct
    behaviour is to FLAG: a low score plus the tied SKUs as alternatives — not
    a confident pick of one.
    """
    result = match_sku("the big walnut conference table")

    # Low confidence — this belongs in the review queue.
    assert result.score < AMBIGUOUS_CEILING, (
        f"ambiguous input scored {result.score}; it must be flagged, not trusted"
    )

    # Whatever the top pick is, it is a MER-CT row and the collisions are
    # surfaced as alternatives.
    assert result.sku is not None and result.sku.startswith("MER-CT-")
    mer_alts = [s for s in result.alternatives if s.startswith("MER-CT-")]
    assert len(mer_alts) >= 2, (
        f"expected several MER-CT alternatives, got {result.alternatives}"
    )

    # The reviewer is told why it hesitated.
    assert result.note is not None

    # Every walnut conference table should appear as pick-or-alternative.
    surfaced = set(result.alternatives) | {result.sku}
    for sku in ("MER-CT-72", "MER-CT-96", "MER-CT-120", "MER-CT-144"):
        assert sku in surfaced


def test_no_match_returns_none():
    result = match_sku("purple hovercraft full of eels")
    assert result.sku is None
    assert result.score < AMBIGUOUS_CEILING
    assert result.note is not None


def test_category_argument_breaks_a_tie():
    """The structured category hint should nudge an otherwise-even match."""
    # "stool" alone is weak; the category confirms the task_chair family stool.
    result = match_sku("stool", category="task_chair")
    assert result.sku == "ASH-TSK-30S"


# --- nominal_inches ---------------------------------------------------------

def test_nominal_inches_size_families():
    assert nominal_inches("MER-CT-120") == 120.0
    assert nominal_inches("MER-CT-72") == 72.0
    assert nominal_inches("KRN-DSK-60") == 60.0
    assert nominal_inches("VER-PNL-72") == 72.0
    assert nominal_inches("TRV-CAF-42") == 42.0
    assert nominal_inches("TRV-CAF-36") == 36.0


def test_nominal_inches_rejects_count_suffixes():
    # counts / spec suffixes are NOT linear dimensions
    assert nominal_inches("STO-LAT-4") is None      # "4-high"
    assert nominal_inches("KRN-BNC-6") is None       # "6-pack"
    assert nominal_inches("VER-POD-4") is None        # "4-person"
    assert nominal_inches("ASH-TSK-30") is None       # model number
    assert nominal_inches("ASH-TSK-30H") is None
    assert nominal_inches("STO-PED-3") is None        # "3-drawer"
    assert nominal_inches("ORB-RCP-2") is None
    assert nominal_inches("HAV-OTT") is None


def test_nominal_inches_returns_float():
    val = nominal_inches("MER-CT-120")
    assert isinstance(val, float)


# --- result-shape invariants ------------------------------------------------

def test_result_shape_and_types():
    result = match_sku("Havenwood ottoman")
    assert isinstance(result.score, float)
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.alternatives, list)
    assert all(isinstance(s, str) for s in result.alternatives)
    # the top pick is never duplicated inside its own alternatives
    assert result.sku not in result.alternatives


def test_top_k_bounds_alternatives_for_clear_matches():
    """For an unambiguous match, alternatives stay within top_k-1."""
    result = match_sku("Havenwood ottoman", top_k=3)
    assert len(result.alternatives) <= 2
