"""
Fuzzy SKU matching for raw line-item descriptions.

A rep types (or an extractor emits) something like "Ashfield task chair,
high-back, graphite" and we need the catalog SKU it refers to — together with an
honest confidence and, when we hesitate, the runner-up SKUs a reviewer should
choose between.

The catalog (`src/catalog.py`) is seeded with deliberate near-collisions:
`MER-CT-72/96/120/144` differ only by a size number, and the `ASH-TSK-*` family
differs by a single qualifier ("High-Back", "Executive", "Stool"). The whole
point of this module is that an *ambiguous* input must produce a genuinely LOW
score with the collisions listed as alternatives — never a confident wrong
guess. Picking one of four identical walnut conference tables at high confidence
would be worse than declining, because it hides the ambiguity from the reviewer.

How the score is built
----------------------
For each catalog row we score the description against the row's *name* tokens
(recall + precision) and give small additive bonuses for category/material
agreement and, when supplied, a width that lands on the row's nominal size. The
dominant term is **name recall**: "how completely does the description account
for this product's defining words". Recall is what cleanly separates the
`ASH-TSK-30` / `ASH-TSK-30H` collision — "standard back" covers the base chair's
tokens fully but leaves the High-Back's "high" unaccounted for, so the base
chair wins; "high-back" covers both equally and precision then breaks the tie
toward the more specific model.

The reported confidence folds in the **separation** from the runner-up: a match
that is clearly ahead of the field scores near its raw quality, while a nest of
near-ties (the `MER-CT-*` case) is damped down into the review band.

    HIGH_CONFIDENCE (>= 0.55)  every listed exact textual match lands here
    AMBIGUOUS       (<  0.45)  genuine near-ties (walnut conference table)
    NO MATCH        (raw < RAW_FLOOR)  sku is None

Width-resolved matches (e.g. a bare "height-adjustable desk" pinned to a size
only by `width_in`) score in the low-to-mid 0.6s — above this module's own
HIGH_CONFIDENCE line, but deliberately well under the schema's `matched_sku`
review threshold (0.90), so they still land in the review queue rather than
auto-committing. The width nudge disambiguates *which* size without asserting
certainty: L008 exists precisely to punish silently snapping 1800mm to the 72"
SKU as if it were sure.

Stdlib only — `difflib` powers the fuzzy token-equality fallback, so no
dependency is added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .catalog import as_dicts

# --- tuning constants -------------------------------------------------------
#
# These thresholds are chosen so the acceptance corpus separates cleanly:
# every listed exact-match description scores >= HIGH_CONFIDENCE, and the
# "the big walnut conference table" ambiguity lands below AMBIGUOUS_CEILING.
HIGH_CONFIDENCE = 0.55       # at/above this we treat the top match as trusted
AMBIGUOUS_CEILING = 0.45     # below this the reviewer should disambiguate
RAW_FLOOR = 0.30             # below this nothing is close enough -> sku=None
AMBIG_MARGIN = 0.05          # raw scores within this of the top are "near ties"
FUZZY_CUTOFF = 0.90          # difflib ratio to accept two tokens as equal

# Weights of the raw-score terms. Name recall dominates; precision only breaks
# recall ties; category/material/width are additive nudges, never required.
_W_RECALL = 0.80
_W_PRECISION = 0.20
_AUX_BONUS = 0.10            # category/material agreement (capped, additive)
_WIDTH_BONUS = 0.25         # a width landing on the row's nominal size (a hard,
                            # deterministic signal — worth more than a text token)
_CATEGORY_BONUS = 0.08      # explicit `category=` argument agreeing with the row
_WIDTH_TOLERANCE_IN = 8.0   # inches of slack before a width stops helping

# Families whose SKU suffix is a *linear dimension* in inches. Everything else
# (counts like "4-high", "6-pack", "4-person", the ASH-TSK-* model numbers) is
# NOT a size and returns None from nominal_inches().
_SIZE_FAMILIES = ("MER-CT-", "KRN-DSK-", "VER-PNL-", "TRV-CAF-")

# Unit words that carry no identity once the number is captured.
_UNIT_WORDS = {"in", "inch", "inches", "ft", "foot", "feet", "mm", "cm", "cms"}


@dataclass
class MatchResult:
    sku: str | None                       # best candidate, or None if nothing is close
    score: float                          # 0..1 confidence in the top match
    alternatives: list[str] = field(default_factory=list)  # runner-up SKUs
    note: str | None = None               # why it hesitated, when score is low


# --- tokenisation -----------------------------------------------------------

def _tokens(text: str) -> list[str]:
    """Normalise free text into comparable tokens.

    Lowercase; split ``72x30`` into ``72 30``; hyphens/punctuation become
    breaks so ``high-back`` -> ``high back`` and ``3-drawer`` -> ``3 drawer``;
    strip unit suffixes so ``42in`` / ``42"`` -> ``42``; and light-stem a
    trailing plural ``s`` (applied to *both* sides, so it only ever helps).
    """
    text = text.lower()
    # "72x30" -> "72 30" (dimension pairs)
    text = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " ", text)
    # everything that isn't a letter or digit is a separator
    text = re.sub(r"[^a-z0-9]+", " ", text)

    out: list[str] = []
    for tok in text.split():
        if tok in _UNIT_WORDS:
            continue
        # "42in", "36inch" -> "42", "36"
        m = re.match(r"^(\d+)(in|inch|inches|ft|mm|cm)$", tok)
        if m:
            tok = m.group(1)
        # light plural stem, but never strip "-ss" (glass, moss) and only for
        # tokens long enough that the trailing s is really a plural marker.
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


def _token_set(text: str) -> set[str]:
    return set(_tokens(text))


def _fuzzy_contains(token: str, pool: set[str]) -> bool:
    """True if ``token`` equals a pool token exactly or within FUZZY_CUTOFF.

    Exact hits are the common path; the difflib fallback catches typos and
    spelling drift ("stacking" vs "staking") without being loose enough to
    collapse real distinctions — e.g. ratio("back","black") == 0.889 < 0.90, so
    a "black" finish never masquerades as the "High-Back" model.
    """
    if token in pool:
        return True
    # Abbreviation-prefix: a short catalog token that opens a longer description
    # word, e.g. catalog "adj" -> desc "adjustable". Alphabetic and len >= 3
    # only, and never numerals, so "3" (STO-PED-3) can't swallow a "36" cafe
    # table size.
    if token.isalpha() and len(token) >= 3:
        for candidate in pool:
            if len(candidate) > len(token) and candidate.startswith(token):
                return True
    for candidate in pool:
        # cheap length guard before the O(n*m) ratio
        if abs(len(candidate) - len(token)) > 2:
            continue
        if SequenceMatcher(None, token, candidate).ratio() >= FUZZY_CUTOFF:
            return True
    return False


def _matched(query: set[str], target: set[str]) -> set[str]:
    """Subset of ``query`` explained by ``target`` (exact or fuzzy)."""
    return {q for q in query if _fuzzy_contains(q, target)}


# --- nominal size -----------------------------------------------------------

def nominal_inches(sku: str) -> float | None:
    """Nominal size in inches for SIZE-suffixed families only.

    MER-CT-120 -> 120.0, KRN-DSK-60 -> 60.0, VER-PNL-72 -> 72.0,
    TRV-CAF-42 -> 42.0. Count/spec suffixes that are not linear dimensions
    (STO-LAT-4 "4-high", KRN-BNC-6 "6-pack", VER-POD-4 "4-person", the
    ASH-TSK-* model numbers) return None.
    """
    for fam in _SIZE_FAMILIES:
        if sku.startswith(fam):
            m = re.match(r"(\d+)", sku[len(fam):])
            return float(m.group(1)) if m else None
    return None


# --- per-row scoring --------------------------------------------------------

@dataclass
class _Scored:
    sku: str
    raw: float
    category: str


def _row_token_sets(row: dict) -> tuple[set[str], set[str]]:
    """Return (name_tokens, aux_tokens) for a catalog row.

    Name tokens carry identity and drive recall/precision. Aux tokens
    (category + material) are only worth a small bonus — a reviewer cares far
    more that "conference table" matched than that "walnut veneer" did.
    """
    name_tokens = _token_set(row["name"])
    aux_tokens = _token_set(row["category"]) | _token_set(row["material"])
    return name_tokens, aux_tokens


def _score_row(
    row: dict,
    desc_tokens: set[str],
    category: str | None,
    width_in: float | None,
) -> float:
    name_tokens, aux_tokens = _row_token_sets(row)
    if not name_tokens:
        return 0.0

    matched_name = _matched(name_tokens, desc_tokens)
    recall = len(matched_name) / len(name_tokens)
    precision = len(matched_name) / len(desc_tokens) if desc_tokens else 0.0

    raw = _W_RECALL * recall + _W_PRECISION * precision

    # category / material agreement in the free text (any hit -> full bonus)
    matched_aux = _matched(aux_tokens, desc_tokens)
    if matched_aux:
        raw += _AUX_BONUS

    # explicit category argument (a structured signal, stronger than free text)
    if category is not None and row["category"] == category:
        raw += _CATEGORY_BONUS

    # a supplied width that lands on this row's nominal size
    if width_in is not None:
        nominal = nominal_inches(row["sku"])
        if nominal is not None:
            closeness = 1.0 - min(1.0, abs(nominal - width_in) / _WIDTH_TOLERANCE_IN)
            raw += _WIDTH_BONUS * closeness

    # NB: intentionally *not* clamped to 1.0 here. Additive bonuses can push a
    # strong match past 1.0, and clamping would flatten the precision tie-break
    # that separates ASH-TSK-30 from ASH-TSK-30H (both would peg at 1.0). Only
    # the reported confidence is clamped; ranking uses the raw magnitude.
    return raw


# --- public entry point -----------------------------------------------------

def match_sku(
    description: str,
    *,
    category: str | None = None,
    width_in: float | None = None,
    top_k: int = 3,
) -> MatchResult:
    """Fuzzy-match a raw line-item ``description`` to a catalog SKU.

    Combines token recall/precision against each row's searchable text
    (name + category + material). ``category`` and ``width_in``, when given,
    break ties. When several rows tie closely the input is ambiguous: the score
    is pushed into the review band and the tied SKUs are returned as
    ``alternatives`` rather than one being picked confidently.

    ``top_k`` bounds the alternatives for a clear match (at most ``top_k - 1``),
    but genuine near-ties are *never* dropped to honour it — an ambiguous input
    surfaces every collision even if that exceeds ``top_k - 1`` (the walnut
    conference table returns three alternatives at the default ``top_k=3``).
    """
    desc_tokens = _token_set(description)
    rows = as_dicts()

    scored = [
        _Scored(
            sku=row["sku"],
            raw=_score_row(row, desc_tokens, category, width_in),
            category=row["category"],
        )
        for row in rows
    ]
    # Deterministic order: raw desc, then catalog order (stable) for ties.
    order = {row["sku"]: i for i, row in enumerate(rows)}
    scored.sort(key=lambda s: (-s.raw, order[s.sku]))

    top = scored[0]
    runner = scored[1] if len(scored) > 1 else None

    # Nothing is close enough to name a SKU at all.
    if top.raw < RAW_FLOOR:
        return MatchResult(
            sku=None,
            score=round(top.raw, 3),
            alternatives=[],
            note="no catalog SKU is a plausible match for this description",
        )

    # Separation from the runner-up: a clear winner keeps most of its raw score;
    # a field of near-ties gets damped toward the review band.
    runner_raw = runner.raw if runner else 0.0
    separation = (top.raw - runner_raw) / top.raw if top.raw > 0 else 1.0
    score = top.raw * (0.7 + 0.3 * separation)

    # Near-ties within AMBIG_MARGIN of the top are genuine alternatives; always
    # surface all of them (that's the MER-CT-* collision), then fill up to
    # top_k with the next-best distinct candidates that clear the floor.
    near_ties = [s for s in scored[1:] if top.raw - s.raw <= AMBIG_MARGIN and s.raw >= RAW_FLOOR]
    n_alt = max(top_k - 1, len(near_ties))
    alternatives: list[str] = []
    for s in scored[1:]:
        if len(alternatives) >= n_alt:
            break
        # keep alternatives that are either near-ties or at least half as strong
        # as the top match; drop obviously irrelevant rows from the list.
        if s.raw >= RAW_FLOOR and (s.raw >= top.raw - AMBIG_MARGIN or s.raw >= 0.5 * top.raw):
            alternatives.append(s.sku)

    note: str | None = None
    if score < HIGH_CONFIDENCE:
        if len(near_ties) >= 1:
            tied = ", ".join([top.sku] + [s.sku for s in near_ties])
            note = (
                f"ambiguous: {len(near_ties) + 1} candidates score within "
                f"{AMBIG_MARGIN:.2f} ({tied}); needs size/model to disambiguate"
            )
        else:
            note = (
                "weak textual match; confidence limited by sparse description"
                + (" (resolved by width)" if width_in is not None else "")
            )

    return MatchResult(
        sku=top.sku,
        score=round(min(1.0, score), 3),
        alternatives=alternatives,
        note=note,
    )
