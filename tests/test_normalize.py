"""
Tests for src.normalize — the deterministic string-to-canonical layer.

The acceptance cases pinned in the corpus (metric conversion, spelled-out
lengths, ranged budgets, vague-date declines) are covered explicitly; the rest
exercise the boundaries where a naive parser would guess instead of decline.
"""

from datetime import date

import pytest

from src.normalize import (
    mm_to_in,
    normalize_phone,
    parse_date,
    parse_length_to_in,
    parse_money,
)

REF = date(2026, 8, 14)


# --------------------------------------------------------------------------
# mm_to_in
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mm, inches",
    [
        (1800, 70.87),   # L008 conference table — must not snap to a 72" SKU
        (750, 29.53),
        (1200, 47.24),
        (0, 0.0),
        (25.4, 1.0),
    ],
)
def test_mm_to_in(mm, inches):
    assert mm_to_in(mm) == inches


def test_mm_to_in_is_two_dp():
    # 1801 / 25.4 = 70.9055... rounds to 2 dp
    assert mm_to_in(1801) == 70.91


# --------------------------------------------------------------------------
# parse_length_to_in
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, inches",
    [
        ("1800mm", 70.87),
        ("1800 mm", 70.87),
        ("750 mm", 29.53),
        ("10'", 120.0),
        ("10 foot", 120.0),
        ("ten foot", 120.0),      # L006 phone transcript
        ("10 feet", 120.0),
        ("6 ft", 72.0),
        ('120"', 120.0),
        ("120in", 120.0),
        ("48 inch", 48.0),
        ("48 inches", 48.0),
        ("twenty inch", 20.0),
        ("one foot", 12.0),
    ],
)
def test_parse_length_to_in(text, inches):
    assert parse_length_to_in(text) == inches


@pytest.mark.parametrize("text", ["", "no dimensions here", "walnut finish", None])
def test_parse_length_to_in_none(text):
    assert parse_length_to_in(text) is None


def test_parse_length_embedded_in_sentence():
    assert parse_length_to_in("needs to be about 1800mm across") == 70.87


def test_parse_length_number_word_does_not_false_match_substring():
    # "someone" contains "one" but not as a standalone word before a unit
    assert parse_length_to_in("someone measured it") is None


# --------------------------------------------------------------------------
# parse_money
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("180-220k", (180000.0, 220000.0)),
        ("CAD 95,000 - 115,000", (95000.0, 115000.0)),
        ("6.5M USD", (6500000.0, None)),
        ("$4,200", (4200.0, None)),
        ("$180k-$220k", (180000.0, 220000.0)),
        ("2M to 3M", (2000000.0, 3000000.0)),
        ("USD 95000 to 115000", (95000.0, 115000.0)),
        ("around 500", (500.0, None)),
        ("1.2b", (1200000000.0, None)),
    ],
)
def test_parse_money(text, expected):
    assert parse_money(text) == expected


def test_parse_money_range_types_are_float():
    low, high = parse_money("180-220k")
    assert isinstance(low, float) and isinstance(high, float)


@pytest.mark.parametrize("text", ["", "no budget stated", "TBD", None])
def test_parse_money_none(text):
    assert parse_money(text) == (None, None)


# --------------------------------------------------------------------------
# parse_date
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("October 15", "2026-10-15"),
        ("Sept 30", "2026-09-30"),
        ("September 30", "2026-09-30"),
        ("11/20/2026", "2026-11-20"),
        ("2026-08-25", "2026-08-25"),
        ("Oct 15", "2026-10-15"),
        ("October 15th", "2026-10-15"),
        ("15 October", "2026-10-15"),
        ("30th of Sept", "2026-09-30"),
        ("3/5", "2026-03-05"),
        ("12/1/26", "2026-12-01"),
        ("Jan 1", "2026-01-01"),
        ("dec 25", "2026-12-25"),
    ],
)
def test_parse_date(text, expected):
    assert parse_date(text, REF) == expected


@pytest.mark.parametrize(
    "text",
    [
        "December sometime",
        "end of September",
        "end of year",
        "sometime next quarter",
        "ASAP",
        "",
        None,
    ],
)
def test_parse_date_vague_returns_none(text):
    # A month with no day must NOT be resolved to an invented day.
    assert parse_date(text, REF) is None


def test_parse_date_invalid_day_declines():
    # A day out of range is not a real date; decline rather than roll over.
    assert parse_date("February 30", REF) is None


# --------------------------------------------------------------------------
# normalize_phone
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("617-555-0182", "617-555-0182"),
        ("(617) 555.0182", "617-555-0182"),
        ("617.555.0182", "617-555-0182"),
        ("6175550182", "617-555-0182"),
        ("+1 (617) 555-0182", "617-555-0182"),
        ("1-617-555-0182", "617-555-0182"),
        ("call me at 617 555 0182 anytime", "617-555-0182"),
    ],
)
def test_normalize_phone(text, expected):
    assert normalize_phone(text) == expected


@pytest.mark.parametrize("text", ["555-0182", "12345", "", "no number", None])
def test_normalize_phone_too_few_digits(text):
    assert normalize_phone(text) is None
