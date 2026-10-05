"""Real VIN construction and validation (ISO 3779 / NHTSA check digit).

Generated VINs pass the same check-digit validation a DMS or DVLA lookup applies,
so nothing in the dataset looks synthetic to anyone who knows vehicles.
"""
from __future__ import annotations

# I, O and Q are excluded from VINs by standard - they are confusable with 1/0.
VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"

# The published NHTSA table, written out rather than derived - the derivation
# has irregular gaps and getting it subtly wrong silently breaks validation.
_TRANSLITERATE = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    **{str(d): d for d in range(10)},
}

_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]

# Model-year codes run a 30-year cycle, skipping I/O/Q/U/Z and 0.
_YEAR_CODES = {
    2010: "A", 2011: "B", 2012: "C", 2013: "D", 2014: "E", 2015: "F",
    2016: "G", 2017: "H", 2018: "J", 2019: "K", 2020: "L", 2021: "M",
    2022: "N", 2023: "P", 2024: "R", 2025: "S", 2026: "T", 2027: "V",
}


def year_code(model_year: int) -> str:
    return _YEAR_CODES[model_year]


def check_digit(vin17: str) -> str:
    """Compute position-9 check digit for a 17-char VIN (placeholder at index 8)."""
    total = sum(_TRANSLITERATE[ch] * w for ch, w in zip(vin17.upper(), _WEIGHTS))
    rem = total % 11
    return "X" if rem == 10 else str(rem)


def build_vin(wmi: str, vds: str, model_year: int, plant: str, sequence: int) -> str:
    """Assemble a structurally valid VIN with a correct check digit.

    wmi      3 chars  world manufacturer identifier  e.g. '1HG' Honda US
    vds      5 chars  vehicle descriptor (attributes)
    plant    1 char   assembly plant
    sequence 6 digits production sequence
    """
    assert len(wmi) == 3 and len(vds) == 5 and len(plant) == 1
    body = f"{wmi}{vds}0{year_code(model_year)}{plant}{sequence:06d}"
    assert len(body) == 17, f"bad VIN length {len(body)}: {body}"
    return body[:8] + check_digit(body) + body[9:]


def is_valid_vin(vin: str) -> bool:
    if len(vin) != 17 or any(c not in VIN_ALPHABET for c in vin.upper()):
        return False
    return check_digit(vin) == vin[8].upper()
