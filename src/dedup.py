"""
Cross-lead deduplication.

A customer resubmits the same request a few days later from a different email
address (L012 is a resubmit of L001). Naively that creates a second lead and a
duplicate quote. Dedup catches it with a content fingerprint — company + the
best contact identifier + the set of (SKU, quantity) line items — so a
resubmission links back to the original instead of entering the queue fresh.

This is deliberately a post-extraction, cross-lead step (not a pipeline node):
the LangGraph pipeline is per-lead, and dedup needs to see the other leads.
"""

from __future__ import annotations

import hashlib

from .schema import CanonicalLead, ReviewStatus, flatten_values


def fingerprint(lead: CanonicalLead) -> str:
    """A stable content key. Robust to the sender's email changing (L012): keys
    on company + phone-or-name + the sorted (sku|description, qty) line items."""
    v = flatten_values(lead)
    company = (v.get("customer.company_name") or "").strip().lower()
    phone = (v.get("customer.primary_contact.phone") or "").strip()
    name = (v.get("customer.primary_contact.full_name") or "").strip().lower()
    contact = phone or name

    items = sorted(
        (str(v.get(f"line_items[{i}].matched_sku") or li.raw_description).strip().lower(),
         v.get(f"line_items[{i}].quantity"))
        for i, li in enumerate(lead.line_items)
    )
    key = "|".join([company, contact, repr(items)])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def find_duplicate(lead: CanonicalLead, seen: dict[str, str]) -> str | None:
    """Return the lead_id this lead duplicates, or None. `seen` maps
    fingerprint -> lead_id for the leads already processed."""
    if lead.is_lead.value is not True:
        return None
    return seen.get(fingerprint(lead))


def mark_duplicate(lead: CanonicalLead, original_id: str) -> None:
    lead.review.duplicate_of = original_id
    lead.review.status = ReviewStatus.DUPLICATE


def mark_duplicates(leads: list[CanonicalLead]) -> None:
    """Link duplicates across a batch, in order (first occurrence wins)."""
    seen: dict[str, str] = {}
    for lead in leads:
        if lead.is_lead.value is not True:
            continue
        dup_of = find_duplicate(lead, seen)
        if dup_of is not None:
            mark_duplicate(lead, dup_of)
        else:
            seen[fingerprint(lead)] = lead.lead_id
