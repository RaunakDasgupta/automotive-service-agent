"""Render technician prose FROM structured ground truth (reverse generation).

The structured record is authored first; this module renders the natural language
a technician would actually type or dictate. That yields paired ground truth for
every update at zero LLM cost, and keeps the free NIM credit pool intact.

Language follows real workshop convention: the 3 C's (Concern/Cause/Correction),
trade shorthand (C/S, R&R, LF/RF/LR/RR, NLA, TSB), and terse, clipped phrasing.
"""
from __future__ import annotations
import random
from app.data.catalog import OP_BY_CODE, DTC_CODES

CONCERN_LEAD = [
    "C/S {c}.", "Customer states {c}.", "C/S - {c}.", "Cust reports {c}.",
    "Write-up says {c}.", "{c} per customer.",
]
VERIFY = [
    "Road tested, confirmed concern.", "Verified on road test.",
    "Duplicated the fault.", "Confirmed customer concern.",
    "Road test - fault present.", "Verified concern, repeatable.",
    "Could not duplicate initially, reproduced after warm-up.",
]
CAUSE_LEAD = [
    "Found {x}.", "Inspection shows {x}.", "Traced to {x}.",
    "Cause - {x}.", "On inspection, {x}.", "Determined {x}.",
]
COMPLETE_LEAD = [
    "Completed {x}.", "Carried out {x}.", "Performed {x}.", "{x} done.",
    "Finished {x}.", "{x} complete.", "Went ahead with {x}.",
]
PENDING_LEAD = [
    "Still to do {x}.", "{x} outstanding.", "{x} still pending.",
    "Yet to carry out {x}.", "{x} not started.", "Left {x} for next shift.",
]
RECOMMEND_LEAD = [
    "Recommend {x}.", "Advise {x}.", "Quoted for {x}.", "Rec {x}.",
    "Put {x} on the estimate.", "Suggest {x} while it's in.",
]
PARTS_WAIT = [
    "Parts checked - {p} is {avail}, RO on parts hold.",
    "{p} not in stock, {avail}. Held pending parts.",
    "Ordered {p}, {avail}. Can't proceed till it lands.",
    "{p} showing {avail} - parked on parts hold.",
]
PARTS_OK = [
    "Parts in stock, {p} pulled.", "{p} available, picked from stores.",
    "Got {p} on the shelf.",
]
AUTH_WAIT = [
    "Estimate to advisor, awaiting customer authorisation.",
    "Sent for authorisation - not proceeding till approved.",
    "Needs customer auth before I go further.",
    "Priced up, with the advisor for approval.",
]
DTC_PHRASE = [
    "Pulled codes - {codes}.", "Scan returned {codes}.",
    "Stored codes: {codes}.", "Full system scan, {codes} present.",
    "Codes on board - {codes}.",
]
MEAS_PHRASE = [
    "{t} measured {v}{u} against {mn}{u} minimum.",
    "{t} at {v}{u}, spec min {mn}{u}.",
    "Measured {t} {v}{u} - below the {mn}{u} limit.",
    "{t} down to {v}{u} ({mn}{u} min).",
]
MEAS_OK = ["{t} measured {v}{u}, within spec.", "{t} at {v}{u} - serviceable."]
SAFETY_TAIL = [
    "Flagging as safety related.", "Not safe to release in this condition.",
    "Advised advisor - safety item.", "Marking safety critical.",
]
FILLER = ["", "", "", "Bay 4. ", "On the ramp now. ", "Quick one - ", "FYI ", ""]
SIGNOFF = ["", "", "", " Will pick up next shift.", " Handing over to afternoon.",
           " Back on it after lunch.", " Notes on the RO."]

SIDE = {"LF": "left front", "RF": "right front", "LR": "left rear", "RR": "right rear"}


def _op_text(code: str, rnd: random.Random, shorthand: bool = True) -> str:
    op = OP_BY_CODE.get(code)
    if not op:
        return code
    d = op.description
    if shorthand and rnd.random() < 0.45:
        d = (d.replace("Replace", "R&R").replace("remove and replace", "R&R")
              .replace(" - conventional", "").replace(" - full synthetic", " (syn)"))
    return d[0].lower() + d[1:] if rnd.random() < 0.6 else d


def render_update(gt: dict, rnd: random.Random) -> str:
    """Render one technician update from its ground-truth structure."""
    parts: list[str] = []
    r = rnd.random

    if gt.get("concern") and r() < 0.85:
        parts.append(rnd.choice(CONCERN_LEAD).format(c=gt["concern"]))
    if gt.get("verified") and r() < 0.8:
        parts.append(rnd.choice(VERIFY))
    if gt.get("dtc_codes"):
        codes = gt["dtc_codes"]
        txt = ", ".join(
            f"{c} {DTC_CODES.get(c,'').lower()}" if r() < 0.55 else c for c in codes)
        parts.append(rnd.choice(DTC_PHRASE).format(codes=txt))

    for m in gt.get("measurements", []):
        tmpl = MEAS_PHRASE if m.get("out_of_spec") else MEAS_OK
        parts.append(rnd.choice(tmpl).format(
            t=m["type"].replace("_", " "), v=m["value"], u=m.get("unit", ""),
            mn=m.get("spec_min", "")))

    if gt.get("cause") and r() < 0.9:
        parts.append(rnd.choice(CAUSE_LEAD).format(x=gt["cause"]))

    completed = [c["op_code"] for c in gt.get("completed", [])]
    if completed:
        txt = ", ".join(_op_text(c, rnd) for c in completed)
        parts.append(rnd.choice(COMPLETE_LEAD).format(x=txt))

    rec = [c["op_code"] for c in gt.get("correction", []) if c.get("status") == "RECOMMENDED"]
    if rec:
        parts.append(rnd.choice(RECOMMEND_LEAD).format(
            x=", ".join(_op_text(c, rnd) for c in rec)))

    for p in gt.get("parts", []):
        avail = p.get("availability", "IN_STOCK")
        if avail == "IN_STOCK":
            if r() < 0.4:
                parts.append(rnd.choice(PARTS_OK).format(p=p["part_no"]))
        else:
            human = {"NEXT_DAY": "next-day order", "BACKORDER": "on backorder",
                     "NLA": "NLA"}.get(avail, avail.lower())
            parts.append(rnd.choice(PARTS_WAIT).format(p=p["part_no"], avail=human))

    pend = [c["op_code"] for c in gt.get("pending", [])]
    if pend:
        parts.append(rnd.choice(PENDING_LEAD).format(
            x=", ".join(_op_text(c, rnd) for c in pend)))

    if gt.get("state_signal") == "AWAITING_AUTHORISATION":
        parts.append(rnd.choice(AUTH_WAIT))
    if gt.get("severity") == "SAFETY_RELATED" and r() < 0.75:
        parts.append(rnd.choice(SAFETY_TAIL))

    body = " ".join(x for x in parts if x)
    return (rnd.choice(FILLER) + body + rnd.choice(SIGNOFF)).strip()


# --- lexical noise: what dictation and hurried typing actually produce --------
TYPOS = {"brake": "brak", "rotor": "rota", "replaced": "replaecd", "inspection": "inspeciton",
         "coolant": "coolent", "bearing": "bearig", "suspension": "supension",
         "customer": "custmer", "vehicle": "vehcile", "pressure": "presure"}


def add_noise(text: str, rnd: random.Random, level: float = 0.25) -> str:
    """Apply realistic degradation - dropped caps, typos, spoken-number forms."""
    if rnd.random() > level:
        return text
    out = text
    if rnd.random() < 0.35:
        for good, bad in TYPOS.items():
            if good in out.lower() and rnd.random() < 0.3:
                out = out.replace(good, bad, 1)
                break
    if rnd.random() < 0.25:
        out = out.lower()
    if rnd.random() < 0.2:
        out = out.replace(".", "", 1)
    return out
