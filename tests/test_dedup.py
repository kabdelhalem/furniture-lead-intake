"""
Tests for cross-lead deduplication.

Leads are built by hand so each test states exactly the fields the fingerprint
depends on. The headline case is L012 (a resubmit of L001 from a different email
address) linking back rather than entering the queue as a fresh lead.
"""

from __future__ import annotations

from datetime import datetime

from src.dedup import fingerprint, mark_duplicates
from src.schema import CanonicalLead, E, LineItem, ReviewStatus


def _lead(lead_id, *, company, phone="", name="", email="", items=()):
    lead = CanonicalLead(lead_id=lead_id, received_at=datetime(2026, 8, 14))
    lead.is_lead = E(True, "certain")
    lead.customer.company_name = E(company, "high")
    if phone:
        lead.customer.primary_contact.phone = E(phone, "certain")
    if name:
        lead.customer.primary_contact.full_name = E(name, "high")
    if email:
        lead.customer.primary_contact.email = E(email, "certain")
    lead.line_items = []
    for sku, qty in items:
        li = LineItem(raw_description=sku or "")
        li.matched_sku = E(sku, "high")
        li.quantity = E(qty, "high")
        lead.line_items.append(li)
    return lead


def test_resubmission_links_to_original():
    # L012 is L001 resent from facilities@ instead of dwhitfield@ — same company,
    # same phone, same order.
    l001 = _lead("L001", company="Northgate Labs", phone="617-555-0182",
                 email="dwhitfield@northgatelabs.com", items=[("ASH-TSK-30H", 8)])
    l012 = _lead("L012", company="Northgate Labs", phone="617-555-0182",
                 email="facilities@northgatelabs.com", items=[("ASH-TSK-30H", 8)])
    mark_duplicates([l001, l012])
    assert l012.review.duplicate_of == "L001"
    assert l012.review.status is ReviewStatus.DUPLICATE
    assert l001.review.duplicate_of is None          # the original is untouched


def test_different_email_same_content_still_matches():
    a = _lead("A", company="Acme", email="a@acme.com", items=[("MER-CT-120", 2)])
    b = _lead("B", company="Acme", email="b@acme.com", items=[("MER-CT-120", 2)])
    # No phone -> falls back to name; here both share company + items and no name,
    # so the fingerprint still matches on company + items.
    assert fingerprint(a) == fingerprint(b)


def test_distinct_leads_do_not_link():
    a = _lead("A", company="Acme", phone="111-555-0001", items=[("MER-CT-120", 2)])
    b = _lead("B", company="Beta", phone="222-555-0002", items=[("TRV-STK", 40)])
    mark_duplicates([a, b])
    assert a.review.duplicate_of is None and b.review.duplicate_of is None


def test_quantity_change_is_not_a_duplicate():
    # Same company + SKU but a different quantity is a revised order, not a dup.
    a = _lead("A", company="Acme", phone="111-555-0001", items=[("KRN-DSK-60", 18)])
    b = _lead("B", company="Acme", phone="111-555-0001", items=[("KRN-DSK-60", 24)])
    mark_duplicates([a, b])
    assert b.review.duplicate_of is None


def test_not_a_lead_is_never_a_duplicate():
    real = _lead("A", company="Acme", phone="111-555-0001", items=[("MER-CT-120", 2)])
    not_lead = _lead("B", company="Acme", phone="111-555-0001", items=[("MER-CT-120", 2)])
    not_lead.is_lead = E(False, "certain")
    mark_duplicates([real, not_lead])
    assert not_lead.review.duplicate_of is None
