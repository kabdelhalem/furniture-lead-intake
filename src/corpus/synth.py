"""
Procedurally generate realistic *volume* leads for the demo queue.

The 15 curated leads in `specs.py` are the scored eval backbone — each one a
named failure mode. These are different: sampled, mostly-clean leads that make
the review queue and dashboard feel like a real inbox rather than a test set.
They reuse the same `LeadSpec` + renderers, so they render into *real* artifacts
(email / xlsx / pdf / transcript) and flow through the same pipeline. Truth is
authored by construction (the generator knows the values because it chose them),
but they carry `curated=False`, so the eval excludes them from the headline
accuracy number.

Deterministic: a fixed seed means the same volume corpus every run, so the demo
and any cache stay reproducible.
"""

from __future__ import annotations

import random

from ..catalog import CATALOG, as_dicts
from .specs import Artifact, LeadSpec

SEED = 20260815

_COMPANIES = [
    "Northgate Labs", "Brightpath Design Group", "Stonebridge Contracting",
    "Halcyon Hospitality", "Kirchner Millwork", "Wexler Adams", "Vantage Groupe",
    "Petrosino Office Interiors", "Vance Atelier", "Cedarline Spaces",
    "Quarry Lane", "Lantern Partners", "Meridian Fitout", "Arcterra Corp",
    "Ridgeline Ventures", "Fairhaven Commons", "Alder & Vine Studio",
    "Sandalwood Group", "Oakmont Partners", "Trellis Workplace",
    "Beacon Hill Interiors", "Cascade Contract", "Dovetail Design Co",
    "Everline Facilities", "Foxglove & Reed", "Granite Peak Advisors",
    "Harborview Group", "Ironwood Collective", "Juniper Workspace",
    "Kestrel Analytics", "Lakeshore Millworks", "Monarch Fit-Out",
    "Nightingale Health", "Overland Coworking", "Pinnacle Dealers",
    "Rosewood A&D", "Summit Contract Group", "Thornfield Interiors",
    "Umbra Studios", "Vireo Ventures",
]
_FIRST = ["Dana", "Marcus", "Priya", "Ruth", "Ted", "Gwen", "Élise", "Sal",
          "Charlotte", "Amara", "Devin", "Rochelle", "Bertrand", "Ingrid",
          "Noah", "Lena", "Omar", "Sofia", "Grant", "Maya", "Curtis", "Naomi",
          "Felix", "Regina", "Hassan", "Iris", "Jonah", "Kira", "Leon", "Petra"]
_LAST = ["Whitfield", "Oyelaran", "Raghunathan", "Beaumont", "Kirchner",
         "Adeyemi", "Tremblay", "Petrosino", "Vance", "Nkemdirim", "Marchetti",
         "Pham", "Osei", "Solheim", "Calloway", "Fairbanks", "Underwood",
         "Delacroix", "Okonkwo", "Sandoval", "Rutherford", "Bianchi", "Novak",
         "Escobar", "Lindqvist", "Ferraro", "Haddad", "Mbeki", "Sørensen", "Yoon"]
_CITY_STATE = [
    ("Cambridge", "MA"), ("Denver", "CO"), ("Austin", "TX"), ("Sarasota", "FL"),
    ("Portland", "OR"), ("Chicago", "IL"), ("Toronto", "ON"), ("Newark", "NJ"),
    ("New York", "NY"), ("Seattle", "WA"), ("Boulder", "CO"), ("Atlanta", "GA"),
    ("Dallas", "TX"), ("Nashville", "TN"), ("Phoenix", "AZ"), ("Columbus", "OH"),
    ("Raleigh", "NC"), ("Minneapolis", "MN"), ("Sacramento", "CA"), ("Tampa", "FL"),
]
_TYPES = [
    ("dealer", "Dealer Principal"), ("designer", "Senior Designer"),
    ("contractor", "Project Manager"), ("end_customer", "Facilities Manager"),
    ("end_customer", "Head of Workplace"), ("designer", "Interior Designer"),
    ("contractor", "Purchasing Lead"), ("end_customer", "Office Manager"),
]
_FINISHES_SKIP = {"-"}


def _slug(name: str) -> str:
    keep = [c.lower() for c in name if c.isalnum() or c == " "]
    return "".join(keep).replace(" ", "")[:18] or "company"


def _line(rng: random.Random) -> dict:
    row = dict(zip(("sku", "name", "category", "material", "finishes",
                    "list_price", "lead_weeks"), rng.choice(CATALOG)))
    qty = rng.choice([1, 2, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 30, 40])
    finishes = [f for f in row["finishes"] if f not in _FINISHES_SKIP]
    finish = rng.choice(finishes) if finishes else None
    return {"sku": row["sku"], "name": row["name"], "qty": qty, "finish": finish,
            "material": row["material"], "com": not finishes}


def _synth_lead(i: int) -> LeadSpec:
    rng = random.Random(SEED * 1000 + i)
    company = rng.choice(_COMPANIES)
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    name = f"{first} {last}"
    domain = _slug(company) + ".com"
    email = f"{first[0].lower()}{last.lower()}@{domain}"
    area = rng.choice(["617", "312", "512", "813", "503", "646", "206", "404",
                       "214", "615", "602", "919", "916", "973", "212"])
    phone = f"{area}-555-{rng.randint(100, 399):04d}"
    city, state = rng.choice(_CITY_STATE)
    ctype, role = rng.choice(_TYPES)

    n = rng.choice([1, 1, 1, 2, 2, 3, 4])
    items = [_line(rng) for _ in range(n)]

    truth: dict = {
        "is_lead": True,
        "customer.company_name": company,
        "customer.customer_type": ctype,
        "customer.primary_contact.full_name": name,
        "customer.primary_contact.email": email,
        "customer.primary_contact.phone": phone,
        "project.site_city": city,
        "project.site_state": state,
    }
    for j, it in enumerate(items):
        truth[f"line_items[{j}].matched_sku"] = it["sku"]
        truth[f"line_items[{j}].quantity"] = it["qty"]
        if it["finish"]:
            truth[f"line_items[{j}].finish"] = it["finish"]

    fmt = rng.random()
    lead_id = f"S{i:03d}"
    if fmt < 0.68:
        artifacts, channel = _email_only(lead_id, company, name, email, phone,
                                         role, city, state, items, rng)
    elif fmt < 0.80:
        artifacts, channel = _email_xlsx(lead_id, company, name, email, phone,
                                         role, city, state, items, rng)
    elif fmt < 0.90:
        artifacts, channel = _email_pdf(lead_id, company, name, email, phone,
                                        role, city, state, items, rng)
    else:
        artifacts, channel = _transcript(lead_id, company, name, email, city,
                                         state, items, rng)
    truth["channel"] = channel

    return LeadSpec(id=lead_id, label="synthetic_volume", tests=["volume"],
                    channel=channel, artifacts=artifacts, truth=truth,
                    notes="Procedurally generated volume lead.", curated=False)


# --------------------------------------------------------------------------
# Format renderers (build Artifact payloads the existing renderers consume)
# --------------------------------------------------------------------------

def _item_phrase(it: dict) -> str:
    bits = [it["name"]]
    if it["finish"]:
        bits.append(it["finish"])
    if it["com"]:
        bits.append("COM")
    return ", ".join(bits)


def _signature(name, role, company, phone) -> list[str]:
    return ["", "Thanks,", name, f"{role} | {company}", phone]


def _email_body(company, name, role, phone, city, state, items, rng, intro) -> str:
    lines = ["Hi there,", "", intro, ""]
    lines += [f"  - {it['qty']}x {_item_phrase(it)}" for it in items]
    lines += ["", f"Ship to {city} {state}."]
    if rng.random() < 0.5:
        lines.append("Please send pricing when you can.")
    lines += _signature(name, role, company, phone)
    return "\n".join(lines)


def _email_only(lead_id, company, name, email, phone, role, city, state, items, rng):
    intro = rng.choice([
        "We're outfitting a new space and need a quote on the following:",
        "Please quote the following for an upcoming project:",
        "Following up on our refresh — we'd like pricing on:",
    ])
    body = _email_body(company, name, role, phone, city, state, items, rng, intro)
    art = Artifact("email", f"{lead_id}.eml", {
        "subject": f"Quote request - {company}",
        "from_name": name, "from_email": email, "body": body,
    })
    return [art], "email"


def _email_xlsx(lead_id, company, name, email, phone, role, city, state, items, rng):
    xlsx_name = f"{lead_id}_takeoff.xlsx"
    rows = [[company.upper(), None, None, None],
            ["FURNITURE TAKEOFF", None, None, None],
            [None, None, None, None],
            ["Item", "Description", "Qty", "Finish"]]
    for k, it in enumerate(items, start=1):
        rows.append([k, it["name"], f"{it['qty']} ea", it["finish"] or ""])
    email_art = Artifact("email", f"{lead_id}.eml", {
        "subject": f"{company} - takeoff attached",
        "from_name": name, "from_email": email,
        "body": f"Takeoff attached. Ship to {city} {state}.\n\n"
                + "\n".join(_signature(name, role, company, phone)[1:]),
        "attachments": [xlsx_name],
    })
    xlsx_art = Artifact("xlsx", xlsx_name, {"sheet": "Takeoff", "merges": ["A1:D1", "A2:D2"], "rows": rows})
    return [email_art, xlsx_art], "email"


def _email_pdf(lead_id, company, name, email, phone, role, city, state, items, rng):
    pdf_name = f"{lead_id}_rfq.pdf"
    lines = [f"{company} / {city} {state}", "", "REQUEST FOR QUOTATION", ""]
    for k, it in enumerate(items, start=1):
        lines += [f"LINE {k}", f"  {_item_phrase(it)}", f"  Quantity: {it['qty']}", ""]
    email_art = Artifact("email", f"{lead_id}.eml", {
        "subject": f"RFQ - {company}", "from_name": name, "from_email": email,
        "body": f"Please see attached RFQ. Delivery to {city} {state}.\n\n"
                + "\n".join(_signature(name, role, company, phone)[1:]),
        "attachments": [pdf_name],
    })
    pdf_art = Artifact("pdf_text", pdf_name, {"title": f"RFQ - {company}", "lines": lines})
    return [email_art, pdf_art], "email"


def _transcript(lead_id, company, name, email, city, state, items, rng):
    lines = [
        "REP: Thanks for calling, how can I help?",
        f"CALLER: Hi, this is {name} from {company}, we're in {city}.",
        "REP: Sure, what are you looking at?",
        "CALLER: We need a quote on a few things —",
    ]
    for it in items:
        lines.append(f"CALLER: {it['qty']} of the {_item_phrase(it)}.")
    lines += [
        "REP: Got it. Can I get a good email?",
        f"CALLER: Yes, it's {email}.",
        "REP: Perfect, I'll get someone on this.",
    ]
    art = Artifact("transcript", f"{lead_id}_call.txt", {
        "meta": f"Inbound call - {city} {state}", "lines": lines,
    })
    return [art], "phone"


def synth_specs(n: int = 90) -> list[LeadSpec]:
    """`n` deterministic volume leads (ids S001..S0NN)."""
    return [_synth_lead(i) for i in range(1, n + 1)]
