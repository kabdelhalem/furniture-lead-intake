"""
The corpus is authored ground-truth-first: each LeadSpec declares what the
correct answer is, then declares the messy artifact(s) that encode it. Artifacts
are DERIVED from truth, never the reverse.

This matters. The usual way synthetic eval sets die is someone generates
plausible-looking documents and then hand-labels them, which quietly bakes in
the same misreadings the extractor will make. Going truth-first means the labels
are correct by construction.

Every spec carries `tests`: the specific failure mode it exists to catch. If a
spec doesn't test something no other spec tests, delete it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Artifact:
    kind: str          # email | pdf_text | pdf_scanned | xlsx | dxf | transcript
    name: str
    payload: dict[str, Any]


@dataclass
class LeadSpec:
    id: str
    label: str
    tests: list[str]
    channel: str
    artifacts: list[Artifact]
    truth: dict[str, Any]
    notes: str = ""
    # Fields we expect the system to be UNSURE about. The calibration check
    # asserts these actually land below threshold — a model that is confidently
    # right here is getting lucky, and a model confidently wrong is dangerous.
    expect_low_confidence: list[str] = field(default_factory=list)


SPECS: list[LeadSpec] = [

    # ---------------------------------------------------------------- L001
    LeadSpec(
        id="L001",
        label="clean_email_single_line",
        tests=["baseline_happy_path"],
        channel="email",
        artifacts=[Artifact("email", "L001.eml", {
            "subject": "Quote request - 8 task chairs",
            "from_name": "Dana Whitfield",
            "from_email": "dwhitfield@northgatelabs.com",
            "body": """Hi there,

We're outfitting a new lab annex and need a quote on 8 of the Ashfield task
chairs, high-back version, in graphite. Delivery to our Cambridge MA site.

We'd need them by October 15 if possible. Please send pricing when you can.

Thanks,
Dana Whitfield
Facilities Manager | Northgate Labs
617-555-0182
""",
        })],
        truth={
            "is_lead": True,
            "channel": "email",
            "customer.company_name": "Northgate Labs",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Dana Whitfield",
            "customer.primary_contact.email": "dwhitfield@northgatelabs.com",
            "customer.primary_contact.phone": "617-555-0182",
            "customer.primary_contact.title": "Facilities Manager",
            "project.site_city": "Cambridge",
            "project.site_state": "MA",
            "project.requested_delivery": "2026-10-15",
            "line_items[0].matched_sku": "ASH-TSK-30H",
            "line_items[0].quantity": 8,
            "line_items[0].finish": "graphite",
        },
    ),

    # ---------------------------------------------------------------- L002
    LeadSpec(
        id="L002",
        label="forwarded_thread_three_quotes",
        tests=["thread_recency", "stale_requirement_rejection"],
        channel="email",
        notes="Two superseded requests above the real one. Naive extraction "
              "grabs qty 12 from the oldest message.",
        artifacts=[Artifact("email", "L002.eml", {
            "subject": "FW: FW: Re: Ridgeline HQ - furniture pkg",
            "from_name": "Marcus Oyelaran",
            "from_email": "m.oyelaran@brightpathdesign.com",
            "body": """Forwarding to you all - latest below. Please quote off the
BOTTOM of this chain, the earlier numbers are dead.

Marcus Oyelaran
Senior Designer, Brightpath Design Group
d: 312-555-0447

---------- Forwarded message ----------
From: Marcus Oyelaran
Sent: Tuesday

Scratch the last one. Client cut scope again. Final is:

  - 6x Kirion bench system, 6-pack, maple
  - 24x Ashfield task chair (standard back), fog
  - 2x Verano meeting pod, 4 person, slate

Site is Denver CO. They want install included. Budget they've floated is
180-220k all in. Need the quote back by Sept 30.

---------- Forwarded message ----------
From: Marcus Oyelaran
Sent: Monday

Revised - client wants 8 bench systems not 12, and add the pods.

---------- Forwarded message ----------
From: Marcus Oyelaran
Sent: Last Friday

Initial scope for Ridgeline HQ:
  - 12x Kirion bench system 6-pack
  - 40x Ashfield task chair
  - lounge TBD
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Brightpath Design Group",
            "customer.customer_type": "designer",
            "customer.primary_contact.full_name": "Marcus Oyelaran",
            "customer.primary_contact.email": "m.oyelaran@brightpathdesign.com",
            "customer.primary_contact.title": "Senior Designer",
            "project.project_name": "Ridgeline HQ",
            "project.site_city": "Denver",
            "project.site_state": "CO",
            "project.install_required": True,
            "project.budget_low": 180000.0,
            "project.budget_high": 220000.0,
            "project.quote_deadline": "2026-09-30",
            "line_items[0].matched_sku": "KRN-BNC-6",
            "line_items[0].quantity": 6,
            "line_items[0].finish": "maple",
            "line_items[1].matched_sku": "ASH-TSK-30",
            "line_items[1].quantity": 24,
            "line_items[1].finish": "fog",
            "line_items[2].matched_sku": "VER-POD-4",
            "line_items[2].quantity": 2,
            "line_items[2].finish": "slate",
        },
    ),

    # ---------------------------------------------------------------- L003
    LeadSpec(
        id="L003",
        label="xlsx_header_row_7_merged_cells",
        tests=["table_header_detection", "merged_cells", "unit_suffix_in_qty"],
        channel="email",
        notes="Header sits on row 7 under a merged title block. Quantities are "
              "strings with unit suffixes. One row is a subtotal, not a line item.",
        artifacts=[Artifact("email", "L003.eml", {
            "subject": "Fairhaven Commons - see attached takeoff",
            "from_name": "Priya Raghunathan",
            "from_email": "praghunathan@stonebridgecontracting.com",
            "body": "Takeoff attached. Ship to Austin TX. Need budgetary numbers "
                    "this week.\n\nPriya Raghunathan\nStonebridge Contracting\n"
                    "512-555-0298",
            "attachments": ["L003_takeoff.xlsx"],
        }),
        Artifact("xlsx", "L003_takeoff.xlsx", {
            "sheet": "Takeoff",
            "merges": ["A1:F1", "A2:F2", "A4:C4"],
            "rows": [
                ["STONEBRIDGE CONTRACTING", None, None, None, None, None],
                ["FURNITURE TAKEOFF - FAIRHAVEN COMMONS PH 2", None, None, None, None, None],
                [None, None, None, None, None, None],
                ["Prepared 08/03/2026 by P. Raghunathan", None, None, None, None, None],
                [None, None, None, None, None, None],
                [None, None, None, None, None, None],
                ["Item", "Description", "Qty", "Finish", "Notes", "Unit $"],
                [1, "Trevose cafe table, 42in round", "14 ea", "walnut stain", "", ""],
                [2, "Trevose stacking chair", "56 ea", "clay", "stack 8 high", ""],
                [3, "Storwell lateral file, 4 high", "6 ea", "putty", "lock req", ""],
                [4, "Verano acoustic panel 72\"", "22 ea", "moss", "ceiling susp", ""],
                [None, "SUBTOTAL", "98", "", "", ""],
                [None, None, None, None, None, None],
                ["*Pricing to be confirmed. Delivery to Austin TX 78704.", None, None, None, None, None],
            ],
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Stonebridge Contracting",
            "customer.customer_type": "contractor",
            "customer.primary_contact.full_name": "Priya Raghunathan",
            "customer.primary_contact.email": "praghunathan@stonebridgecontracting.com",
            "customer.primary_contact.phone": "512-555-0298",
            "project.project_name": "Fairhaven Commons Ph 2",
            "project.site_city": "Austin",
            "project.site_state": "TX",
            "line_items[0].matched_sku": "TRV-CAF-42",
            "line_items[0].quantity": 14,
            "line_items[1].matched_sku": "TRV-STK",
            "line_items[1].quantity": 56,
            "line_items[2].matched_sku": "STO-LAT-4",
            "line_items[2].quantity": 6,
            "line_items[3].matched_sku": "VER-PNL-72",
            "line_items[3].quantity": 22,
        },
    ),

    # ---------------------------------------------------------------- L004
    LeadSpec(
        id="L004",
        label="scanned_fax_no_text_layer",
        tests=["ocr_required", "degraded_input"],
        channel="fax",
        notes="Rendered as an image inside the PDF with noise and a slight skew. "
              "pdfplumber returns empty string; forces the OCR branch.",
        artifacts=[Artifact("pdf_scanned", "L004_fax.pdf", {
            "title": "PURCHASE INQUIRY",
            "skew_deg": 1.4,
            "noise": 0.06,
            "lines": [
                "HALCYON HOSPITALITY GROUP",
                "1180 Bayfront Ave, Tampa FL 33602",
                "",
                "ATTN: SALES",
                "",
                "Please quote the following for our Sarasota property:",
                "",
                "  QTY 18 - Havenwood lounge chair, COM",
                "  QTY 6  - Havenwood ottoman, COM",
                "",
                "COM fabric is Maharam Mode 'Pumice' - we will supply.",
                "",
                "Delivery needed by 11/20/2026. Install NOT required.",
                "",
                "Contact: Ruth Beaumont, Procurement",
                "rbeaumont@halcyonhg.com  /  813-555-0311",
            ],
        })],
        truth={
            "is_lead": True,
            "channel": "fax",
            "customer.company_name": "Halcyon Hospitality Group",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Ruth Beaumont",
            "customer.primary_contact.email": "rbeaumont@halcyonhg.com",
            "customer.primary_contact.phone": "813-555-0311",
            "customer.primary_contact.title": "Procurement",
            "project.site_city": "Sarasota",
            "project.site_state": "FL",
            "project.requested_delivery": "2026-11-20",
            "project.install_required": False,
            "line_items[0].matched_sku": "HAV-LNG-1",
            "line_items[0].quantity": 18,
            "line_items[0].com_fabric": "Maharam Mode Pumice",
            "line_items[1].matched_sku": "HAV-OTT",
            "line_items[1].quantity": 6,
            "line_items[1].com_fabric": "Maharam Mode Pumice",
        },
        expect_low_confidence=["line_items[1].com_fabric"],
    ),

    # ---------------------------------------------------------------- L005
    LeadSpec(
        id="L005",
        label="dxf_dimensions_and_callouts",
        tests=["cad_text_layer", "dimension_from_drawing", "no_geometry_parsing"],
        channel="email",
        notes="Dimensions live in MTEXT callouts and a DIMENSION entity, not in "
              "the email body. Deliberately does NOT require geometry math.",
        artifacts=[Artifact("email", "L005.eml", {
            "subject": "Custom conference table - dwg attached",
            "from_name": "Ted Kirchner",
            "from_email": "tkirchner@kirchner-millwork.com",
            "body": "See attached. Need one of these, dims are on the drawing. "
                    "Natural walnut. Ship Portland OR.\n\n-Ted\nKirchner Millwork\n"
                    "503-555-0166",
            "attachments": ["L005_table.dxf"],
        }),
        Artifact("dxf", "L005_table.dxf", {
            "texts": [
                (10, 190, "PROJECT: ALDER & VINE - MAIN CONF"),
                (10, 180, "CONF TABLE - PLAN VIEW"),
                (10, 170, "MATL: WALNUT VENEER, NATURAL FIN"),
                (10, 160, "QTY: 1"),
                (10, 20,  "NOTE: GROMMETS 2X, POWER/DATA BY OTHERS"),
                (10, 10,  "SCALE 1:20   REV C   08/05/2026"),
            ],
            "dims": [
                {"p1": (0, 0), "p2": (120, 0), "text_pos": (60, -12), "label": "120\""},
                {"p1": (0, 0), "p2": (0, 48), "text_pos": (-14, 24), "label": "48\""},
            ],
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Kirchner Millwork",
            "customer.customer_type": "dealer",
            "customer.primary_contact.full_name": "Ted Kirchner",
            "customer.primary_contact.email": "tkirchner@kirchner-millwork.com",
            "customer.primary_contact.phone": "503-555-0166",
            "project.project_name": "Alder & Vine - Main Conf",
            "project.site_city": "Portland",
            "project.site_state": "OR",
            "line_items[0].matched_sku": "MER-CT-120",
            "line_items[0].quantity": 1,
            "line_items[0].material": "walnut veneer",
            "line_items[0].finish": "natural",
            "line_items[0].dimensions.width_in": 120.0,
            "line_items[0].dimensions.depth_in": 48.0,
        },
    ),

    # ---------------------------------------------------------------- L006
    LeadSpec(
        id="L006",
        label="phone_transcript_feet_inches",
        tests=["speech_disfluency", "feet_inches_parsing", "hedged_quantity"],
        channel="phone",
        notes="Rambling, self-corrects mid-sentence, gives 'ten foot' for a table "
              "that must normalize to 120in. Quantity is hedged ('four, maybe five').",
        artifacts=[Artifact("transcript", "L006_call.txt", {
            "meta": "Inbound call - 08/06/2026 10:42 ET - duration 4m12s - rep: unassigned",
            "lines": [
                "REP: Thanks for calling, this is the sales line, how can I help?",
                "CALLER: Yeah hi, uh, I'm calling from Wexler Adams, we're a law firm "
                "downtown. Chicago. We're doing a refresh on our, uh, our thirty-first floor.",
                "REP: Sure, what are you looking at?",
                "CALLER: So we need conference tables. The big ones. I think we need "
                "four, maybe five, I have to check with the partners, but let's say four "
                "for now. Ten foot tables.",
                "REP: Ten foot, got it.",
                "CALLER: And then chairs around them, the executive ones, the leather. "
                "Uh, ten per table.",
                "REP: Okay. Any finish preference on the tables?",
                "CALLER: Espresso. Definitely espresso, we did natural last time and "
                "the partners hated it.",
                "REP: And timing?",
                "CALLER: We're hoping end of year. December sometime. Oh and we need "
                "you guys to install, we don't have anyone here who can do that.",
                "REP: Can I get your name and a good email?",
                "CALLER: Sure, it's Gwen Adeyemi, that's A-D-E-Y-E-M-I, and it's "
                "gadeyemi at wexleradams dot com. Office manager.",
                "REP: Perfect, I'll get someone on this today.",
            ],
        })],
        truth={
            "is_lead": True,
            "channel": "phone",
            "customer.company_name": "Wexler Adams",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Gwen Adeyemi",
            "customer.primary_contact.email": "gadeyemi@wexleradams.com",
            "customer.primary_contact.title": "Office Manager",
            "project.site_city": "Chicago",
            "project.site_state": "IL",
            "project.install_required": True,
            "line_items[0].matched_sku": "MER-CT-120",
            "line_items[0].quantity": 4,
            "line_items[0].finish": "espresso",
            "line_items[0].dimensions.width_in": 120.0,
            "line_items[1].matched_sku": "ASH-TSK-40",
            "line_items[1].quantity": 40,
        },
        expect_low_confidence=[
            "line_items[0].quantity",       # "four, maybe five"
            "line_items[1].quantity",       # requires 10 x 4 inference
            "project.requested_delivery",   # "December sometime"
        ],
    ),

    # ---------------------------------------------------------------- L007
    LeadSpec(
        id="L007",
        label="ambiguous_sku_reference",
        tests=["sku_disambiguation", "must_flag_not_guess"],
        channel="email",
        notes="'the big walnut one' maps to three plausible SKUs. Correct behavior "
              "is a low-confidence match with alternatives populated, NOT a guess.",
        artifacts=[Artifact("email", "L007.eml", {
            "subject": "reorder",
            "from_name": "Sal Petrosino",
            "from_email": "sal@petrosinooffice.net",
            "body": """hey - need 3 more of the big walnut conference table, same as
what we did for the Brennan job last year. and 30 of the mesh chairs, black.

ship to our warehouse in Newark NJ.

sal
Petrosino Office Interiors
973-555-0125
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Petrosino Office Interiors",
            "customer.customer_type": "dealer",
            "customer.primary_contact.full_name": "Sal Petrosino",
            "customer.primary_contact.email": "sal@petrosinooffice.net",
            "customer.primary_contact.phone": "973-555-0125",
            "project.site_city": "Newark",
            "project.site_state": "NJ",
            "line_items[0].matched_sku": None,   # genuinely unresolvable from source
            "line_items[0].quantity": 3,
            "line_items[0].material": "walnut veneer",
            "line_items[1].matched_sku": "ASH-TSK-30",
            "line_items[1].quantity": 30,
            "line_items[1].finish": "black",
        },
        expect_low_confidence=["line_items[0].matched_sku"],
    ),

    # ---------------------------------------------------------------- L008
    LeadSpec(
        id="L008",
        label="metric_units_pdf",
        tests=["unit_normalization", "metric_to_imperial"],
        channel="email",
        notes="All dims in mm. 1800mm -> 70.87in, which must NOT snap to the 72in "
              "SKU without flagging the 1.1in discrepancy.",
        artifacts=[Artifact("email", "L008.eml", {
            "subject": "RFQ - Meridian Toronto office",
            "from_name": "Élise Tremblay",
            "from_email": "e.tremblay@vantagegroupe.ca",
            "body": "Bonjour, please see attached RFQ. Delivery to Toronto ON.\n\n"
                    "Élise Tremblay\nVantage Groupe\n416-555-0173",
            "attachments": ["L008_rfq.pdf"],
        }),
        Artifact("pdf_text", "L008_rfq.pdf", {
            "title": "REQUEST FOR QUOTATION - VG-2026-114",
            "lines": [
                "Vantage Groupe / Bureau Toronto",
                "Date: 2026-08-04    Response due: 2026-08-25",
                "",
                "LINE 1",
                "  Height-adjustable desk, laminate, white",
                "  Dimensions: 1800mm W x 750mm D",
                "  Quantity: 32",
                "",
                "LINE 2",
                "  Mobile pedestal, 3 drawer, white",
                "  Quantity: 32",
                "",
                "LINE 3",
                "  Acoustic panel, 1200mm, felt, slate",
                "  Quantity: 18",
                "",
                "Budget envelope: CAD 95,000 - 115,000",
                "Installation: required",
            ],
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Vantage Groupe",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Élise Tremblay",
            "customer.primary_contact.email": "e.tremblay@vantagegroupe.ca",
            "customer.primary_contact.phone": "416-555-0173",
            "project.site_city": "Toronto",
            "project.site_state": "ON",
            "project.quote_deadline": "2026-08-25",
            "project.install_required": True,
            "project.budget_low": 95000.0,
            "project.budget_high": 115000.0,
            "line_items[0].matched_sku": "KRN-DSK-72",
            "line_items[0].quantity": 32,
            "line_items[0].finish": "white",
            "line_items[0].dimensions.width_in": 70.87,
            "line_items[0].dimensions.depth_in": 29.53,
            "line_items[0].dimensions.source_units": "metric",
            "line_items[1].matched_sku": "STO-PED-3",
            "line_items[1].quantity": 32,
            "line_items[1].finish": "white",
            "line_items[2].matched_sku": "VER-PNL-48",
            "line_items[2].quantity": 18,
            "line_items[2].finish": "slate",
        },
        expect_low_confidence=[
            "line_items[0].matched_sku",   # 70.87in vs 72in nominal
            "line_items[2].matched_sku",   # 1200mm = 47.2in vs 48in nominal
        ],
    ),

    # ---------------------------------------------------------------- L009
    LeadSpec(
        id="L009",
        label="two_contacts_assistant_cc",
        tests=["decision_maker_resolution", "sender_is_not_buyer"],
        channel="email",
        notes="Sender is an EA writing on behalf of the principal. Naive extraction "
              "makes the EA the primary contact.",
        artifacts=[Artifact("email", "L009.eml", {
            "subject": "On behalf of Charlotte Vance - showroom order",
            "from_name": "Jonah Reyes",
            "from_email": "jreyes@vanceatelier.com",
            "body": """Hello,

I'm writing on behalf of Charlotte Vance, principal at Vance Atelier. She has
asked me to request pricing on:

  - 4x Orbit reception desk, double, concrete finish
  - 2x Havenwood lounge 3-seat, COM (fabric TBD)

Please direct all pricing and contract questions to Charlotte directly at
cvance@vanceatelier.com or 646-555-0209. I'm only coordinating the request.

Site is New York NY. She'd like this before the end of September.

Best,
Jonah Reyes
Executive Assistant to Charlotte Vance
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Vance Atelier",
            "customer.customer_type": "designer",
            "customer.primary_contact.full_name": "Charlotte Vance",
            "customer.primary_contact.email": "cvance@vanceatelier.com",
            "customer.primary_contact.phone": "646-555-0209",
            "customer.primary_contact.title": "Principal",
            "customer.primary_contact.is_decision_maker": True,
            "project.site_city": "New York",
            "project.site_state": "NY",
            "line_items[0].matched_sku": "ORB-RCP-2",
            "line_items[0].quantity": 4,
            "line_items[0].finish": "concrete",
            "line_items[1].matched_sku": "HAV-LNG-3",
            "line_items[1].quantity": 2,
        },
        expect_low_confidence=["project.requested_delivery"],
    ),

    # ---------------------------------------------------------------- L010
    LeadSpec(
        id="L010",
        label="mid_thread_revision",
        tests=["in_place_correction", "last_write_wins"],
        channel="email",
        notes="A one-line correction at the bottom overrides a number stated above.",
        artifacts=[Artifact("email", "L010.eml", {
            "subject": "Re: Cedarline coworking - revised counts",
            "from_name": "Amara Nkemdirim",
            "from_email": "amara@cedarlinespaces.com",
            "body": """Following up on my note from this morning:

  18x Kirion height adjustable desk 60x30, graphite
  18x Storwell pedestal 3 drawer, black
  4x Verano focus pod single, oat

Ship to Seattle WA. Install required. Need by 2026-10-01.

--- 

Actually hold on, make the desks 24 not 18. Pedestals stay at 18. Sorry.

Amara Nkemdirim
Head of Workplace, Cedarline Spaces
206-555-0144
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Cedarline Spaces",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Amara Nkemdirim",
            "customer.primary_contact.email": "amara@cedarlinespaces.com",
            "customer.primary_contact.phone": "206-555-0144",
            "customer.primary_contact.title": "Head of Workplace",
            "project.project_name": "Cedarline Coworking",
            "project.site_city": "Seattle",
            "project.site_state": "WA",
            "project.install_required": True,
            "project.requested_delivery": "2026-10-01",
            "line_items[0].matched_sku": "KRN-DSK-60",
            "line_items[0].quantity": 24,
            "line_items[0].finish": "graphite",
            "line_items[1].matched_sku": "STO-PED-3",
            "line_items[1].quantity": 18,
            "line_items[1].finish": "black",
            "line_items[2].matched_sku": "VER-POD-1",
            "line_items[2].quantity": 4,
            "line_items[2].finish": "oat",
        },
    ),

    # ---------------------------------------------------------------- L011
    LeadSpec(
        id="L011",
        label="missing_quantity_entirely",
        tests=["null_handling", "hallucination_resistance"],
        channel="email",
        notes="No quantity is stated anywhere. The ONLY correct output is null + "
              "flag. Any invented number is a hard failure in the eval.",
        artifacts=[Artifact("email", "L011.eml", {
            "subject": "pricing on the pods",
            "from_name": "Devin Marchetti",
            "from_email": "dmarchetti@quarrylane.io",
            "body": """What do the four-person meeting pods run? Slate finish.
We're early on this, just budgeting for now. Site would be Boulder CO.

Devin Marchetti
Quarry Lane
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Quarry Lane",
            "customer.primary_contact.full_name": "Devin Marchetti",
            "customer.primary_contact.email": "dmarchetti@quarrylane.io",
            "project.site_city": "Boulder",
            "project.site_state": "CO",
            "line_items[0].matched_sku": "VER-POD-4",
            "line_items[0].quantity": None,
            "line_items[0].finish": "slate",
        },
        expect_low_confidence=["line_items[0].quantity"],
    ),

    # ---------------------------------------------------------------- L012
    LeadSpec(
        id="L012",
        label="duplicate_resubmission",
        tests=["deduplication"],
        channel="email",
        notes="Same request as L001, resent 3 days later from a different address "
              "at the same domain. Should link to L001, not create a fresh lead.",
        artifacts=[Artifact("email", "L012.eml", {
            "subject": "Following up - chair quote for Northgate",
            "from_name": "Dana Whitfield",
            "from_email": "facilities@northgatelabs.com",
            "body": """Hi, following up on my request from last week - we still need
the quote on 8 Ashfield high-back task chairs in graphite for the Cambridge
annex. Same October 15 date.

Dana Whitfield
Northgate Labs
617-555-0182
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Northgate Labs",
            "customer.primary_contact.full_name": "Dana Whitfield",
            "customer.primary_contact.email": "facilities@northgatelabs.com",
            "customer.primary_contact.phone": "617-555-0182",
            "line_items[0].matched_sku": "ASH-TSK-30H",
            "line_items[0].quantity": 8,
            "line_items[0].finish": "graphite",
            "_review.status": "duplicate",
            "_review.duplicate_of": "L001",
        },
    ),

    # ---------------------------------------------------------------- L013
    LeadSpec(
        id="L013",
        label="not_a_lead_invoice_question",
        tests=["negative_case", "classifier_gate"],
        channel="email",
        notes="Looks lead-shaped (company, SKUs, quantities) but is an AP question. "
              "If this reaches the review queue, the classifier gate is broken.",
        artifacts=[Artifact("email", "L013.eml", {
            "subject": "Invoice 88214 - short shipment",
            "from_name": "Rochelle Pham",
            "from_email": "ap@lantern-partners.com",
            "body": """Hi, we received invoice 88214 for 12x MER-CT-72 but only 10
arrived on the 7/29 delivery. We're holding payment on the difference until
this is resolved. Please advise on the two missing units.

Rochelle Pham
Accounts Payable, Lantern Partners
415-555-0187
""",
        })],
        truth={
            "is_lead": False,
        },
    ),

    # ---------------------------------------------------------------- L014
    LeadSpec(
        id="L014",
        label="multi_artifact_email_pdf_xlsx",
        tests=["cross_artifact_merge", "conflicting_values"],
        channel="email",
        notes="The spec PDF says oat, the pricing sheet says slate. Neither source "
              "is authoritative — the conflict must surface, not get silently resolved.",
        artifacts=[Artifact("email", "L014.eml", {
            "subject": "Sandalwood Tower amenity floor - full package",
            "from_name": "Bertrand Osei",
            "from_email": "b.osei@meridianfitout.com",
            "body": "Two attachments - spec narrative and the quantity sheet. "
                    "Note they may not agree on finishes, go with whatever's cheaper "
                    "and flag it.\n\nBertrand Osei\nMeridian Fitout\n404-555-0192",
            "attachments": ["L014_spec.pdf", "L014_qty.xlsx"],
        }),
        Artifact("pdf_text", "L014_spec.pdf", {
            "title": "SANDALWOOD TOWER - AMENITY LEVEL - FF&E NARRATIVE",
            "lines": [
                "Project: Sandalwood Tower, Atlanta GA",
                "Issued: 2026-08-01   Rev: 2",
                "",
                "2.1 ACOUSTIC TREATMENT",
                "    Verano acoustic panel, 48 inch, PET felt.",
                "    Finish: OAT",
                "",
                "2.2 CAFE SEATING",
                "    Trevose cafe table, 36 inch round, solid oak, natural.",
                "    Trevose stacking chair, beech, natural.",
                "",
                "2.3 LOUNGE",
                "    Havenwood lounge 2-seat, COM by owner.",
                "",
                "Installation by vendor. Substantial completion 2026-12-15.",
            ],
        }),
        Artifact("xlsx", "L014_qty.xlsx", {
            "sheet": "QTY",
            "merges": [],
            "rows": [
                ["Sandalwood Tower - Amenity Level", None, None, None],
                [None, None, None, None],
                ["Ref", "Item", "Qty", "Finish"],
                ["2.1", "Verano acoustic panel 48\"", 34, "slate"],
                ["2.2a", "Trevose cafe table 36\" rd", 12, "natural"],
                ["2.2b", "Trevose stacking chair", 48, "natural"],
                ["2.3", "Havenwood lounge 2-seat", 7, "COM"],
            ],
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Meridian Fitout",
            "customer.customer_type": "contractor",
            "customer.primary_contact.full_name": "Bertrand Osei",
            "customer.primary_contact.email": "b.osei@meridianfitout.com",
            "customer.primary_contact.phone": "404-555-0192",
            "project.project_name": "Sandalwood Tower",
            "project.site_city": "Atlanta",
            "project.site_state": "GA",
            "project.install_required": True,
            "project.requested_delivery": "2026-12-15",
            "line_items[0].matched_sku": "VER-PNL-48",
            "line_items[0].quantity": 34,
            "line_items[1].matched_sku": "TRV-CAF-36",
            "line_items[1].quantity": 12,
            "line_items[1].finish": "natural",
            "line_items[2].matched_sku": "TRV-STK",
            "line_items[2].quantity": 48,
            "line_items[2].finish": "natural",
            "line_items[3].matched_sku": "HAV-LNG-2",
            "line_items[3].quantity": 7,
        },
        expect_low_confidence=["line_items[0].finish"],
    ),

    # ---------------------------------------------------------------- L015
    LeadSpec(
        id="L015",
        label="enterprise_high_value_routing",
        tests=["routing_priority", "segment_classification"],
        channel="email",
        notes="Exists mainly to exercise the routing rules: >$500k + enterprise + "
              "named account should fire three rules and land on the top of the queue.",
        artifacts=[Artifact("email", "L015.eml", {
            "subject": "Global workplace standards - North America rollout, 14 sites",
            "from_name": "Ingrid Solheim",
            "from_email": "i.solheim@arcterracorp.com",
            "body": """We're standardizing workplace furniture across 14 North American
sites and would like to discuss a master agreement.

Indicative volumes per site (14 sites):
  - 120x Kirion height-adjustable desk 60x30, white
  - 120x Ashfield task chair, graphite
  - 30x Storwell lateral file 2-high, white
  - 8x Verano meeting pod 4-person, oat

Total program budget is approximately 6.5M USD. First site (Dallas TX) needs to
be complete by 2027-03-01; remaining sites roll out through 2027.

Please have someone senior contact me.

Ingrid Solheim
VP Global Real Estate & Workplace, Arcterra Corp
212-555-0100
""",
        })],
        truth={
            "is_lead": True,
            "customer.company_name": "Arcterra Corp",
            "customer.customer_type": "end_customer",
            "customer.primary_contact.full_name": "Ingrid Solheim",
            "customer.primary_contact.email": "i.solheim@arcterracorp.com",
            "customer.primary_contact.phone": "212-555-0100",
            "customer.primary_contact.title": "VP Global Real Estate & Workplace",
            "customer.primary_contact.is_decision_maker": True,
            "project.site_city": "Dallas",
            "project.site_state": "TX",
            "project.budget_low": 6500000.0,
            "project.requested_delivery": "2027-03-01",
            "line_items[0].matched_sku": "KRN-DSK-60",
            "line_items[0].quantity": 120,
            "line_items[0].finish": "white",
            "line_items[1].matched_sku": "ASH-TSK-30",
            "line_items[1].quantity": 120,
            "line_items[1].finish": "graphite",
            "line_items[2].matched_sku": "STO-LAT-2",
            "line_items[2].quantity": 30,
            "line_items[2].finish": "white",
            "line_items[3].matched_sku": "VER-POD-4",
            "line_items[3].quantity": 8,
            "line_items[3].finish": "oat",
            "_routing.segment": "enterprise",
        },
        expect_low_confidence=["line_items[0].quantity"],  # per-site vs total
    ),
]


def by_id(lead_id: str) -> LeadSpec:
    return next(s for s in SPECS if s.id == lead_id)


def coverage_report() -> dict[str, list[str]]:
    """Which specs cover which failure mode. Print this in the README."""
    cov: dict[str, list[str]] = {}
    for s in SPECS:
        for t in s.tests:
            cov.setdefault(t, []).append(s.id)
    return dict(sorted(cov.items()))
