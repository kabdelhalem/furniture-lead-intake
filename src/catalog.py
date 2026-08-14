"""
Stub product catalog. 30 SKUs is enough to make fuzzy matching non-trivial —
note the deliberate near-collisions (MER-CT-96 vs MER-CT-120, ASH-TSK-* family)
which are what generate genuinely low-confidence matches in the demo.
"""

CATALOG = [
    # sku, name, category, material, default finishes, list price, lead weeks
    ("MER-CT-72",   "Meridian Conference Table 72\"",   "conference_table", "walnut veneer", ["natural", "espresso"],           2450.0, 8),
    ("MER-CT-96",   "Meridian Conference Table 96\"",   "conference_table", "walnut veneer", ["natural", "espresso"],           3180.0, 8),
    ("MER-CT-120",  "Meridian Conference Table 120\"",  "conference_table", "walnut veneer", ["natural", "espresso"],           3890.0, 10),
    ("MER-CT-144",  "Meridian Conference Table 144\"",  "conference_table", "walnut veneer", ["natural", "espresso"],           4620.0, 10),
    ("ASH-TSK-30",  "Ashfield Task Chair",              "task_chair",       "mesh/poly",     ["black", "graphite", "fog"],       540.0,  4),
    ("ASH-TSK-30H", "Ashfield Task Chair High-Back",    "task_chair",       "mesh/poly",     ["black", "graphite", "fog"],       625.0,  4),
    ("ASH-TSK-30S", "Ashfield Stool",                   "task_chair",       "mesh/poly",     ["black", "graphite"],              598.0,  4),
    ("ASH-TSK-40",  "Ashfield Executive Chair",         "task_chair",       "leather",       ["black", "cognac"],                1180.0, 6),
    ("HAV-LNG-2",   "Havenwood Lounge 2-Seat",          "lounge",           "COM",           ["-"],                              2240.0, 12),
    ("HAV-LNG-3",   "Havenwood Lounge 3-Seat",          "lounge",           "COM",           ["-"],                              2880.0, 12),
    ("HAV-LNG-1",   "Havenwood Lounge Chair",           "lounge",           "COM",           ["-"],                              1420.0, 12),
    ("HAV-OTT",     "Havenwood Ottoman",                "lounge",           "COM",           ["-"],                              680.0,  12),
    ("KRN-DSK-60",  "Kirion Height-Adj Desk 60x30",     "desk",             "laminate",      ["white", "maple", "graphite"],     1120.0, 5),
    ("KRN-DSK-72",  "Kirion Height-Adj Desk 72x30",     "desk",             "laminate",      ["white", "maple", "graphite"],     1290.0, 5),
    ("KRN-DSK-48",  "Kirion Height-Adj Desk 48x24",     "desk",             "laminate",      ["white", "maple", "graphite"],     960.0,  5),
    ("KRN-BNC-4",   "Kirion Bench System 4-Pack",       "desk",             "laminate",      ["white", "maple"],                 4180.0, 7),
    ("KRN-BNC-6",   "Kirion Bench System 6-Pack",       "desk",             "laminate",      ["white", "maple"],                 6050.0, 7),
    ("STO-PED-3",   "Storwell Pedestal 3-Drawer",       "storage",          "steel",         ["white", "black", "putty"],        410.0,  3),
    ("STO-LAT-2",   "Storwell Lateral File 2-High",     "storage",          "steel",         ["white", "black", "putty"],        890.0,  3),
    ("STO-LAT-4",   "Storwell Lateral File 4-High",     "storage",          "steel",         ["white", "black", "putty"],        1340.0, 3),
    ("STO-LKR-6",   "Storwell Locker Bank 6-Unit",      "storage",          "steel",         ["white", "black"],                 1880.0, 6),
    ("VER-PNL-48",  "Verano Acoustic Panel 48\"",       "acoustic",         "PET felt",      ["oat", "slate", "moss"],           240.0,  4),
    ("VER-PNL-72",  "Verano Acoustic Panel 72\"",       "acoustic",         "PET felt",      ["oat", "slate", "moss"],           330.0,  4),
    ("VER-POD-1",   "Verano Focus Pod Single",          "acoustic",         "PET felt/glass", ["oat", "slate"],                  8900.0, 14),
    ("VER-POD-4",   "Verano Meeting Pod 4-Person",      "acoustic",         "PET felt/glass", ["oat", "slate"],                 16400.0, 16),
    ("TRV-CAF-36",  "Trevose Cafe Table 36\" Round",    "cafe",             "solid oak",     ["natural", "walnut stain"],        740.0,  6),
    ("TRV-CAF-42",  "Trevose Cafe Table 42\" Round",    "cafe",             "solid oak",     ["natural", "walnut stain"],        820.0,  6),
    ("TRV-STK",     "Trevose Stacking Chair",           "cafe",             "beech/poly",    ["natural", "black", "clay"],       310.0,  4),
    ("ORB-RCP-1",   "Orbit Reception Desk Single",      "reception",        "solid surface", ["white", "concrete"],              4200.0, 10),
    ("ORB-RCP-2",   "Orbit Reception Desk Double",      "reception",        "solid surface", ["white", "concrete"],              6350.0, 10),
]

FIELDS = ("sku", "name", "category", "material", "finishes", "list_price", "lead_weeks")


def as_dicts() -> list[dict]:
    return [dict(zip(FIELDS, row)) for row in CATALOG]


def by_sku(sku: str) -> dict | None:
    return next((d for d in as_dicts() if d["sku"] == sku), None)
