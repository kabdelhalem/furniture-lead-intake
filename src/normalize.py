"""
Normalizers: messy source strings -> canonical values.

Extraction pulls raw spans out of emails, spreadsheets, transcripts, and CAD
annotations; this module turns those spans into the typed values the schema
expects. Every function here is pure and deterministic — no model calls, no I/O
— so the same input always yields the same canonical output, and the eval
harness can lean on them without a cache.

Two rules the corpus forces on us:

- **Metric never silently snaps to an imperial SKU.** 1800mm converts to
  70.87in, not "close enough to the 72in table" (see lead L008). Conversion is
  exact; SKU matching happens later and downstream, where it can flag the gap.
- **A vague date is not a date.** "end of September" and "December sometime"
  carry no day, so they return None. Inventing the 30th would be a
  hallucinated value, and declining is the correct answer (mirrors the L011
  stance on quantities).
"""

from __future__ import annotations

import datetime
import re

MM_PER_INCH = 25.4

# Small number-words that show up spelled out in phone transcripts
# ("ten foot", "four, maybe five"). One..twenty covers the corpus.
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}

# Three-letter prefix -> month number. Abbreviations, full names, and the
# stray "sept" all collapse to the same prefix.
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_MONTH_RE = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)"
)

_MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def mm_to_in(mm: float) -> float:
    """Millimetres to inches, rounded to 2 decimal places."""
    return round(mm / MM_PER_INCH, 2)


def _words_to_digits(text: str) -> str:
    """Replace whole-word number-words with their digits, in place."""
    def sub(match: re.Match[str]) -> str:
        return str(_NUMBER_WORDS[match.group(0).lower()])

    pattern = r"\b(" + "|".join(_NUMBER_WORDS) + r")\b"
    return re.sub(pattern, sub, text, flags=re.IGNORECASE)


def parse_length_to_in(text: str) -> float | None:
    """
    Parse a single length to inches (2 dp), or None if none is present.

    Accepts millimetres ("1800mm", "1800 mm"), feet ("10'", "10 foot",
    "ten foot"), and inches ('120"', "120in", "48 inch"). Spelled-out small
    numbers count. The first length found wins.
    """
    if not text:
        return None

    normalized = _words_to_digits(text)
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(mm|millimeters?|feet|foot|ft|inches|inch|in|'|\")",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()

    if unit in ("mm", "millimeter", "millimeters"):
        return mm_to_in(value)
    if unit in ("feet", "foot", "ft", "'"):
        return round(value * 12.0, 2)
    # inches: in, inch, inches, "
    return round(value, 2)


def parse_money(text: str) -> tuple[float | None, float | None]:
    """
    Parse a budget span into (low, high). High is None when there is no range.

    Currency codes and symbols are ignored; a trailing k/M/B multiplier on a
    range applies to both ends ("180-220k" -> 180000, 220000).
    """
    if not text:
        return (None, None)

    # Drop thousands separators and currency symbols so "95,000" reads as one
    # number and "$180k-$220k" reads as a clean range.
    cleaned = text.replace(",", "")
    cleaned = re.sub(r"[$€£¥]", " ", cleaned)

    number = r"(\d+(?:\.\d+)?)\s*([kmb])?"
    separator = r"\s*(?:-|–|—|to)\s*"

    range_match = re.search(number + separator + number, cleaned, flags=re.IGNORECASE)
    if range_match:
        low_num, low_suf, high_num, high_suf = range_match.groups()
        # A multiplier stated once governs the whole range.
        low_mult = _mult(low_suf or high_suf)
        high_mult = _mult(high_suf or low_suf)
        return (float(low_num) * low_mult, float(high_num) * high_mult)

    single = re.search(number, cleaned, flags=re.IGNORECASE)
    if single:
        num, suf = single.groups()
        return (float(num) * _mult(suf), None)

    return (None, None)


def _mult(suffix: str | None) -> int:
    return _MULTIPLIERS.get(suffix.lower(), 1) if suffix else 1


def parse_date(text: str, reference: datetime.date) -> str | None:
    """
    Parse a date to ISO "YYYY-MM-DD", or None.

    Resolves the year (and undated month/day forms) against `reference`.
    Vague inputs with no explicit day ("end of September", "December
    sometime", "end of year") return None — declining beats guessing a day.
    """
    if not text:
        return None

    # 1. ISO passthrough.
    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        return _iso(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    # 2. Numeric M/D/Y or M/D.
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if slash:
        month, day = int(slash.group(1)), int(slash.group(2))
        year = _resolve_year(slash.group(3), reference)
        return _iso(year, month, day)

    # 3. Month name + day, e.g. "October 15", "Sept 30", "15th of Oct".
    month_day = re.search(
        _MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_day:
        month = _MONTHS[month_day.group(1)[:3].lower()]
        return _iso(reference.year, month, int(month_day.group(2)))

    # 4. Day + month name, e.g. "15 October", "30th Sept".
    day_month = re.search(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE,
        text,
        flags=re.IGNORECASE,
    )
    if day_month:
        month = _MONTHS[day_month.group(2)[:3].lower()]
        return _iso(reference.year, month, int(day_month.group(1)))

    # A month with no day, or no date at all — vague, decline.
    return None


def _resolve_year(raw: str | None, reference: datetime.date) -> int:
    if raw is None:
        return reference.year
    year = int(raw)
    return year + 2000 if year < 100 else year


def _iso(year: int, month: int, day: int) -> str | None:
    """Format as ISO, or None if the (y, m, d) triple is not a real date."""
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_phone(text: str) -> str | None:
    """
    Canonicalize a phone number to "XXX-XXX-XXXX", or None if it has fewer
    than 10 digits. A leading US country code (1) on an 11-digit number is
    dropped.
    """
    if not text:
        return None

    digits = re.sub(r"\D", "", text)
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    digits = digits[:10]
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
