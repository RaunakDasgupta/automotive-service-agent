"""Reference data modelled on real service-department practice.

Labour operations use dealer-style op codes with flat-rate hours (the billing
basis every shop works to). DTCs are genuine SAE J2012 codes. Fleet entries
carry real World Manufacturer Identifiers so generated VINs decode correctly.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal

SkillLevel = Literal["APPRENTICE", "TECH_C", "TECH_B", "TECH_A", "MASTER", "DIAG_SPEC"]


@dataclass(frozen=True)
class LabourOp:
    op_code: str
    description: str
    flat_rate_hrs: float
    category: str
    min_skill: SkillLevel
    safety_critical: bool = False


def _op(c, d, h, cat, skill="TECH_B", safety=False) -> LabourOp:
    return LabourOp(c, d, h, cat, skill, safety)


LABOUR_OPS: list[LabourOp] = [
    # --- Maintenance -------------------------------------------------------
    _op("LOF",            "Lube, oil & filter - conventional",        0.5, "Maintenance", "APPRENTICE"),
    _op("LOF-SYN",        "Lube, oil & filter - full synthetic",      0.6, "Maintenance", "APPRENTICE"),
    _op("MAINT-15K",      "15,000 mile service interval",             1.8, "Maintenance", "TECH_C"),
    _op("MAINT-30K",      "30,000 mile service interval",             2.6, "Maintenance", "TECH_C"),
    _op("MAINT-60K",      "60,000 mile major service",                4.2, "Maintenance", "TECH_B"),
    _op("FILT-CABIN",     "Cabin air filter replacement",             0.3, "Maintenance", "APPRENTICE"),
    _op("FILT-ENG-AIR",   "Engine air filter replacement",            0.3, "Maintenance", "APPRENTICE"),
    _op("FLUID-BRK-FLUSH","Brake fluid flush & bleed",                1.0, "Maintenance", "TECH_C", True),
    _op("FLUID-COOL",     "Cooling system drain & refill",            1.2, "Maintenance", "TECH_C"),
    _op("FLUID-PS",       "Power steering fluid service",             0.8, "Maintenance", "TECH_C"),
    _op("WIPER-RR",       "Wiper blade replacement",                  0.2, "Maintenance", "APPRENTICE"),
    _op("SPARK-PLUG-4",   "Spark plugs R&R - 4 cylinder",             1.1, "Maintenance", "TECH_B"),
    _op("SPARK-PLUG-6",   "Spark plugs R&R - V6",                     2.3, "Maintenance", "TECH_B"),
    # --- Brakes ------------------------------------------------------------
    _op("BRK-INSP",       "Brake system inspection - 4 wheel",        0.4, "Brakes", "TECH_C", True),
    _op("BRK-FR-PAD",     "Front brake pads & rotors R&R",            1.8, "Brakes", "TECH_C", True),
    _op("BRK-RR-PAD",     "Rear brake pads & rotors R&R",             1.9, "Brakes", "TECH_C", True),
    _op("BRK-FR-INSP",    "Front brake inspection & measure",         0.3, "Brakes", "TECH_C", True),
    _op("BRK-RR-INSP",    "Rear brake inspection & measure",          0.3, "Brakes", "TECH_C", True),
    _op("BRK-CALIPER",    "Brake caliper R&R - single",               1.4, "Brakes", "TECH_B", True),
    _op("BRK-MASTER",     "Master cylinder R&R",                      2.2, "Brakes", "TECH_A", True),
    _op("BRK-LINE",       "Brake line fabrication & replace",         2.0, "Brakes", "TECH_A", True),
    _op("BRK-PARK-ADJ",   "Parking brake adjustment",                 0.6, "Brakes", "TECH_C", True),
    _op("BRK-ABS-DIAG",   "ABS system diagnosis",                     1.2, "Brakes", "DIAG_SPEC", True),
    # --- Suspension / Steering ---------------------------------------------
    _op("SUS-FR-STRUT",   "Front strut assembly R&R - pair",          2.4, "Suspension", "TECH_B", True),
    _op("SUS-RR-SHOCK",   "Rear shock absorber R&R - pair",           1.6, "Suspension", "TECH_C"),
    _op("SUS-CTRL-ARM",   "Control arm R&R - lower",                  2.1, "Suspension", "TECH_B", True),
    _op("SUS-BALL-JOINT", "Ball joint R&R",                           1.8, "Suspension", "TECH_B", True),
    _op("SUS-SWAY-LINK",  "Sway bar link R&R - pair",                 0.8, "Suspension", "TECH_C"),
    _op("STR-TIE-ROD",    "Tie rod end R&R",                          1.2, "Suspension", "TECH_B", True),
    _op("STR-RACK",       "Steering rack R&R",                        4.5, "Suspension", "TECH_A", True),
    _op("STR-PUMP",       "Power steering pump R&R",                  2.0, "Suspension", "TECH_B"),
    _op("SUS-INSP",       "Suspension & steering inspection",         0.5, "Suspension", "TECH_C", True),
    _op("SUS-WHEEL-BRG",  "Wheel bearing/hub assembly R&R",           1.9, "Suspension", "TECH_B", True),
    # --- Engine / Driveability ---------------------------------------------
    _op("ENG-MISFIRE",    "Misfire diagnosis",                        1.5, "Engine", "DIAG_SPEC"),
    _op("ENG-COMP-TEST",  "Compression test - all cylinders",         1.2, "Engine", "TECH_A"),
    _op("ENG-TIMING-BELT","Timing belt & tensioner R&R",              5.5, "Engine", "TECH_A"),
    _op("ENG-VALVE-ADJ",  "Valve clearance adjustment",               3.2, "Engine", "TECH_A"),
    _op("ENG-OIL-LEAK",   "Oil leak diagnosis & dye test",            1.0, "Engine", "TECH_B"),
    _op("ENG-VC-GASKET",  "Valve cover gasket R&R",                   1.8, "Engine", "TECH_B"),
    _op("ENG-WATER-PUMP", "Water pump R&R",                           3.0, "Engine", "TECH_B"),
    _op("ENG-THERMOSTAT", "Thermostat R&R",                           1.4, "Engine", "TECH_C"),
    _op("ENG-SERP-BELT",  "Serpentine belt R&R",                      0.7, "Engine", "TECH_C"),
    _op("ENG-MOUNT",      "Engine mount R&R",                         2.2, "Engine", "TECH_B"),
    _op("ENG-INTAKE-CLEAN","Intake & throttle body decarbon",         1.5, "Engine", "TECH_B"),
    _op("ENG-COOL-PRESS", "Cooling system pressure test",             0.6, "Engine", "TECH_C"),
    # --- Electrical / Battery ----------------------------------------------
    _op("ELE-BATT-TEST",  "Battery & charging system test",           0.3, "Electrical", "APPRENTICE"),
    _op("ELE-BATT-RR",    "Battery R&R & register",                   0.5, "Electrical", "TECH_C"),
    _op("ELE-ALT",        "Alternator R&R",                           1.8, "Electrical", "TECH_B"),
    _op("ELE-STARTER",    "Starter motor R&R",                        1.6, "Electrical", "TECH_B"),
    _op("ELE-PARASITIC",  "Parasitic draw diagnosis",                 2.0, "Electrical", "DIAG_SPEC"),
    _op("ELE-WIRE-REP",   "Wiring harness repair",                    2.5, "Electrical", "TECH_A"),
    _op("ELE-HEADLAMP",   "Headlamp assembly R&R",                    0.9, "Electrical", "TECH_C", True),
    _op("ELE-MODULE-PROG","Control module programming",               1.5, "Electrical", "DIAG_SPEC"),
    _op("ELE-SENSOR-O2",  "Oxygen sensor R&R",                        0.9, "Electrical", "TECH_C"),
    _op("ELE-NO-START",   "No-start condition diagnosis",             1.5, "Electrical", "DIAG_SPEC"),
    # --- HVAC ---------------------------------------------------------------
    _op("HVAC-EVAC",      "A/C evacuate & recharge",                  1.2, "HVAC", "TECH_C"),
    _op("HVAC-PERF",      "A/C performance test",                     0.6, "HVAC", "TECH_C"),
    _op("HVAC-LEAK",      "A/C leak detection - dye/sniffer",         1.0, "HVAC", "TECH_B"),
    _op("HVAC-COMP",      "A/C compressor R&R",                       3.2, "HVAC", "TECH_B"),
    _op("HVAC-COND",      "A/C condenser R&R",                        2.4, "HVAC", "TECH_B"),
    _op("HVAC-BLOWER",    "Blower motor R&R",                         1.1, "HVAC", "TECH_C"),
    _op("HVAC-HEATER-CORE","Heater core R&R",                         6.5, "HVAC", "TECH_A"),
    _op("HVAC-ACTUATOR",  "Blend door actuator R&R",                  1.4, "HVAC", "TECH_B"),
    # --- Transmission / Driveline -------------------------------------------
    _op("TRN-FLUID",      "Transmission fluid & filter service",      1.5, "Transmission", "TECH_C"),
    _op("TRN-DIAG",       "Transmission diagnosis & scan",            1.5, "Transmission", "DIAG_SPEC"),
    _op("TRN-MOUNT",      "Transmission mount R&R",                   1.4, "Transmission", "TECH_B"),
    _op("TRN-CLUTCH",     "Clutch assembly R&R",                      6.0, "Transmission", "TECH_A"),
    _op("DRV-CV-AXLE",    "CV axle shaft R&R",                        1.7, "Transmission", "TECH_B"),
    _op("DRV-CV-BOOT",    "CV boot R&R",                              1.5, "Transmission", "TECH_B"),
    _op("DRV-DIFF-FLUID", "Differential fluid service",               0.8, "Transmission", "TECH_C"),
    _op("DRV-DRIVESHAFT", "Driveshaft U-joint R&R",                   2.0, "Transmission", "TECH_B"),
    # --- Exhaust / Emissions -------------------------------------------------
    _op("EXH-CAT",        "Catalytic converter R&R",                  2.5, "Exhaust", "TECH_B"),
    _op("EXH-MUFFLER",    "Muffler & tailpipe R&R",                   1.3, "Exhaust", "TECH_C"),
    _op("EXH-SMOKE-TEST", "EVAP smoke test",                          1.0, "Exhaust", "DIAG_SPEC"),
    _op("EXH-EGR",        "EGR valve R&R & clean",                    1.6, "Exhaust", "TECH_B"),
    _op("EXH-DPF-REGEN",  "DPF forced regeneration",                  1.4, "Exhaust", "DIAG_SPEC"),
    _op("EMIS-TEST",      "Emissions test & certificate",             0.7, "Exhaust", "TECH_C"),
    _op("EXH-FLEX",       "Exhaust flex pipe section repair",         1.2, "Exhaust", "TECH_C"),
    # --- Diagnostics ---------------------------------------------------------
    _op("DIAG-SCAN",      "Full system scan & code retrieval",        0.5, "Diagnostics", "TECH_C"),
    _op("DIAG-DRIVE",     "Driveability diagnosis",                   1.0, "Diagnostics", "DIAG_SPEC"),
    _op("DIAG-BRAKE",     "Brake concern diagnosis",                  0.5, "Diagnostics", "TECH_B", True),
    _op("DIAG-NOISE",     "Noise/vibration diagnosis & road test",    1.2, "Diagnostics", "TECH_A"),
    _op("DIAG-ELEC",      "Electrical fault diagnosis",               1.5, "Diagnostics", "DIAG_SPEC"),
    _op("DIAG-HVAC",      "HVAC system diagnosis",                    1.0, "Diagnostics", "TECH_B"),
    _op("DIAG-ROAD-TEST", "Road test - verify concern",               0.4, "Diagnostics", "TECH_C"),
    _op("DIAG-INTERMIT",  "Intermittent fault investigation",         2.0, "Diagnostics", "DIAG_SPEC"),
    # --- Tyres / Alignment ----------------------------------------------------
    _op("TYR-ROTATE",     "Tyre rotation & pressure set",             0.4, "Tyres", "APPRENTICE"),
    _op("TYR-MOUNT-BAL",  "Mount & balance - per tyre",               0.4, "Tyres", "APPRENTICE", True),
    _op("TYR-REPAIR",     "Puncture repair - plug/patch",             0.5, "Tyres", "TECH_C", True),
    _op("TYR-TPMS",       "TPMS sensor R&R & relearn",                0.7, "Tyres", "TECH_C"),
    _op("ALN-4WHEEL",     "Four wheel alignment",                     1.2, "Tyres", "TECH_B", True),
    _op("ALN-CHECK",      "Alignment check & printout",               0.4, "Tyres", "TECH_C"),
    _op("TYR-INSP-TREAD", "Tyre inspection & tread depth",            0.2, "Tyres", "APPRENTICE", True),
    # --- Recall / Campaign -----------------------------------------------------
    _op("RCL-CAMPAIGN",   "Manufacturer recall campaign",             1.0, "Recall", "TECH_B", True),
    _op("RCL-TAKATA",     "Airbag inflator recall remedy",            1.5, "Recall", "TECH_B", True),
    _op("RCL-SOFTWARE",   "Software update campaign",                 0.8, "Recall", "DIAG_SPEC"),
    _op("TSB-APPLY",      "Technical service bulletin remedy",        1.2, "Recall", "TECH_B"),
    # --- Bodywork / Trim --------------------------------------------------------
    _op("BDY-WSHLD",      "Windscreen R&R",                           2.0, "Bodywork", "TECH_C", True),
    _op("BDY-MIRROR",     "Door mirror R&R",                          0.8, "Bodywork", "TECH_C"),
    _op("BDY-DOOR-HANDLE","Door handle R&R",                          1.1, "Bodywork", "TECH_C"),
    _op("BDY-WINDOW-REG", "Window regulator R&R",                     1.6, "Bodywork", "TECH_C"),
    _op("BDY-TRIM",       "Interior trim panel R&R",                  0.9, "Bodywork", "APPRENTICE"),
    _op("BDY-SEAT-BELT",  "Seat belt assembly R&R",                   1.3, "Bodywork", "TECH_B", True),
    _op("BDY-WIPER-MOTOR","Wiper motor R&R",                          1.2, "Bodywork", "TECH_C", True),
]

OP_BY_CODE = {o.op_code: o for o in LABOUR_OPS}
CATEGORIES = sorted({o.category for o in LABOUR_OPS})

# --- Genuine SAE J2012 diagnostic trouble codes -------------------------------
# Prefix semantics: P powertrain, B body, C chassis, U network.
DTC_CODES: dict[str, str] = {
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0304": "Cylinder 4 misfire detected",
    "P0171": "System too lean (bank 1)",
    "P0174": "System too lean (bank 2)",
    "P0420": "Catalyst system efficiency below threshold (bank 1)",
    "P0430": "Catalyst system efficiency below threshold (bank 2)",
    "P0442": "EVAP system small leak detected",
    "P0455": "EVAP system gross leak detected",
    "P0128": "Coolant thermostat below regulating temperature",
    "P0131": "O2 sensor circuit low voltage (bank 1 sensor 1)",
    "P0401": "EGR flow insufficient detected",
    "P0507": "Idle air control system RPM higher than expected",
    "P0011": "Camshaft position timing over-advanced (bank 1)",
    "P0335": "Crankshaft position sensor A circuit malfunction",
    "P0700": "Transmission control system malfunction",
    "P0741": "Torque converter clutch circuit performance",
    "C1201": "ABS engine control system malfunction",
    "C0035": "Left front wheel speed sensor circuit",
    "C0040": "Right front wheel speed sensor circuit",
    "B1318": "Battery voltage low",
    "B0081": "Passenger presence sensing system",
    "U0100": "Lost communication with ECM/PCM 'A'",
    "U0121": "Lost communication with ABS control module",
    "U0155": "Lost communication with instrument panel cluster",
}

# --- Fleet: real makes/models with genuine World Manufacturer Identifiers -----
FLEET = [
    ("Honda",      "Civic",      "1HG", "2.0L i-VTEC",       ["CV1F5", "CV2F6", "FC2F5"]),
    ("Honda",      "CR-V",       "2HK", "1.5L VTEC Turbo",   ["RW1H5", "RW2H6"]),
    ("Toyota",     "Corolla",    "2T1", "1.8L Dynamic Force",["BURHE", "BPRAE"]),
    ("Toyota",     "RAV4",       "JTM", "2.5L Dynamic Force",["RWRFV", "WRFVD"]),
    ("Ford",       "Focus",      "1FA", "1.0L EcoBoost",     ["DP3K1", "DP3F2"]),
    ("Ford",       "Transit",    "1FT", "2.0L EcoBlue",      ["YE2Z5", "BW3G7"]),
    ("Volkswagen", "Golf",       "WVW", "1.5L TSI",          ["ZZZAU", "ZZZCD"]),
    ("Volkswagen", "Passat",     "1VW", "2.0L TDI",          ["AA7A3", "BP7A9"]),
    ("BMW",        "3 Series",   "WBA", "2.0L TwinPower",    ["5R1C0", "8E9G5"]),
    ("Mercedes",   "C-Class",    "WDD", "2.0L Turbo",        ["GF4HB", "WF4KB"]),
    ("Nissan",     "Qashqai",    "SJN", "1.3L DIG-T",        ["FAAJ1", "FBAJ1"]),
    ("Vauxhall",   "Astra",      "W0L", "1.2L Turbo",        ["PD6DB", "BD6DA"]),
    ("Hyundai",    "Tucson",     "KMH", "1.6L T-GDi",        ["J3CAF", "J281F"]),
    ("Kia",        "Sportage",   "KNA", "1.6L CRDi",         ["P81CA", "PU81C"]),
    ("Audi",       "A4",         "WAU", "2.0L TFSI",         ["ZZZF4", "ENAF4"]),
]

PAY_TYPES = ["CUSTOMER_PAY", "WARRANTY", "INTERNAL", "GOODWILL"]
WAIT_TYPES = ["DROP_OFF", "WAITER", "LOANER", "RENTAL"]

PART_AVAILABILITY = ["IN_STOCK", "NEXT_DAY", "BACKORDER", "NLA"]


def catalog_as_dicts() -> list[dict]:
    return [asdict(o) for o in LABOUR_OPS]
