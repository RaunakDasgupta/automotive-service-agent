"""Extract the 3 C's structure from a technician's update.

Concern / Cause / Correction is the documentation standard on every repair order,
so extracting to it means the output drops straight into a DMS.

The LLM is used ONLY to read language. It never decides state, never computes
hours, never resolves an op code - all of that is deterministic downstream.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field, asdict
from typing import Any

from app.data.catalog import OP_BY_CODE, DTC_CODES
from app.pipeline.resolve import resolve_ro, resolve_op, Resolution

SCHEMA_HINT = """{
  "concern": "what the customer reported, or null",
  "cause": "what the technician found, or null",
  "verified": true/false,
  "completed": [{"work": "free text of work finished", "hours": 0.0}],
  "pending":   [{"work": "free text of work still outstanding"}],
  "recommended":[{"work": "free text of work advised, needing authorisation"}],
  "parts": [{"part_no": "string or null", "description": "string",
             "availability": "IN_STOCK|NEXT_DAY|BACKORDER|NLA|null"}],
  "dtc_codes": ["P0420"],
  "measurements": [{"type":"rotor_thickness","value":22.8,"unit":"mm","spec_min":23.0}],
  "ro_hint": "any repair order or registration mentioned, else null",
  "state_hint": "PARTS_HOLD|AWAITING_AUTHORISATION|REPAIR_IN_PROGRESS|QUALITY_CONTROL|null",
  "safety_concern": true/false
}"""

SYSTEM = (
    "You read UK automotive service technician notes and return structured JSON.\n"
    "Follow the 3 C's convention: Concern (what the customer reported), Cause "
    "(what was found), Correction (work done or advised).\n"
    "Trade shorthand: C/S = customer states, R&R = remove and replace, "
    "LF/RF/LR/RR = left/right front/rear, NLA = no longer available, "
    "TSB = technical service bulletin, VHC = vehicle health check.\n"
    "Rules: report ONLY what the text states. Never invent part numbers, hours, "
    "measurements or codes. Use null when something is not mentioned. "
    "Do not infer the repair order state unless the text clearly indicates it.\n"
    "Return a single JSON object and nothing else."
)


@dataclass
class Extraction:
    raw: dict[str, Any] = field(default_factory=dict)
    concern: str | None = None
    cause: str | None = None
    verified: bool = False
    completed: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    correction: list[dict] = field(default_factory=list)
    parts: list[dict] = field(default_factory=list)
    dtc_codes: list[str] = field(default_factory=list)
    measurements: list[dict] = field(default_factory=list)
    state_signal: str | None = None
    severity: str | None = None
    ro_resolution: Resolution | None = None
    unresolved: list[dict] = field(default_factory=list)
    confidence: float = 0.0

    def to_ground_truth(self, text: str = "") -> dict:
        """The shape reconcile() consumes."""
        return {"concern": self.concern, "cause": self.cause, "verified": self.verified,
                "completed": self.completed, "pending": self.pending,
                "correction": self.correction, "parts": self.parts,
                "dtc_codes": self.dtc_codes, "measurements": self.measurements,
                "state_signal": self.state_signal, "severity": self.severity,
                "_text": text}

    @property
    def needs_clarification(self) -> bool:
        return bool(self.unresolved) or (self.ro_resolution is not None
                                         and self.ro_resolution.needs_clarification)

    def clarifying_questions(self) -> list[str]:
        qs = []
        if self.ro_resolution and self.ro_resolution.needs_clarification:
            c = self.ro_resolution.candidates
            qs.append(f"Which repair order is this? {self.ro_resolution.reason}"
                      + (f" Candidates: {', '.join(x[0] for x in c[:4])}" if c else ""))
        for u in self.unresolved:
            cands = ", ".join(f"{c} ({OP_BY_CODE[c].description})"
                              for c, _ in u["candidates"][:3] if c in OP_BY_CODE)
            qs.append(f"Which operation is \"{u['work']}\"?" + (f" Closest: {cands}" if cands else ""))
        return qs


def parse_json(raw: str) -> dict:
    """Tolerant JSON extraction - models sometimes wrap output in prose or fences."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fence:
        raw = fence.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    if start == -1:
        raise ValueError("no JSON object in model output")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(raw[start:], start):
        if in_str:
            if esc:      esc = False
            elif ch == "\\": esc = True
            elif ch == '"':  in_str = False
            continue
        if ch == '"':   in_str = True
        elif ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:i + 1])
    raise ValueError("unbalanced JSON in model output")


def _clean_hours(v) -> float | None:
    try:
        f = float(v)
        return round(f, 2) if 0 < f <= 24 else None       # reject implausible hours
    except (TypeError, ValueError):
        return None


def validate(raw: dict, text: str, known_ros: list[str], embed_fn=None) -> Extraction:
    """Turn loose model output into validated, canonical structure.

    Everything the model said is checked against the catalog. Anything that does
    not resolve becomes a clarification rather than a guess.
    """
    e = Extraction(raw=raw)
    e.concern = (raw.get("concern") or None)
    e.cause = (raw.get("cause") or None)
    e.verified = bool(raw.get("verified"))

    for key, target in (("completed", e.completed), ("pending", e.pending),
                        ("recommended", e.correction)):
        for item in (raw.get(key) or []):
            work = (item or {}).get("work") or (item or {}).get("op_code") or ""
            if not work:
                continue
            r = resolve_op(str(work), embed_fn=embed_fn)
            if r.is_certain(Resolution.OP_THRESHOLD):
                rec = {"op_code": r.value}
                if key == "completed":
                    rec["actual_hrs"] = _clean_hours(item.get("hours"))
                if key == "recommended":
                    rec["status"] = "RECOMMENDED"
                target.append(rec)
            else:
                e.unresolved.append({"work": str(work), "kind": key,
                                     "candidates": r.candidates, "reason": r.reason})

    for p in (raw.get("parts") or []):
        if not p:
            continue
        pn = p.get("part_no") or p.get("description")
        if pn:
            av = (p.get("availability") or "NEXT_DAY")
            av = av if av in ("IN_STOCK", "NEXT_DAY", "BACKORDER", "NLA") else "NEXT_DAY"
            e.parts.append({"part_no": str(pn), "availability": av})

    # Only genuine SAE codes survive - a hallucinated code is dropped.
    for c in (raw.get("dtc_codes") or []):
        c = str(c).upper().strip()
        if c in DTC_CODES:
            e.dtc_codes.append(c)

    for m in (raw.get("measurements") or []):
        if not m or m.get("value") is None:
            continue
        try:
            val = float(m["value"])
            smin = float(m["spec_min"]) if m.get("spec_min") is not None else None
        except (TypeError, ValueError):
            continue
        oos = (smin is not None and val < smin)
        e.measurements.append({"type": str(m.get("type") or "measurement"), "value": val,
                               "unit": str(m.get("unit") or ""), "spec_min": smin,
                               "out_of_spec": oos, "safety_related": oos})
        if oos:
            e.severity = "SAFETY_RELATED"
    if raw.get("safety_concern"):
        e.severity = "SAFETY_RELATED"

    st = (raw.get("state_hint") or "").upper() or None
    e.state_signal = st if st in {"PARTS_HOLD", "AWAITING_AUTHORISATION",
                                  "REPAIR_IN_PROGRESS", "QUALITY_CONTROL"} else None

    hint = raw.get("ro_hint") or ""
    e.ro_resolution = resolve_ro(f"{hint} {text}", known_ros)

    resolved = len(e.completed) + len(e.pending) + len(e.correction)
    total = resolved + len(e.unresolved)
    e.confidence = round(
        (0.6 * (e.ro_resolution.confidence if e.ro_resolution else 0.0)
         + 0.4 * (resolved / total if total else 1.0)), 2)
    return e


def extract(text: str, known_ros: list[str], chat_fn=None, embed_fn=None) -> Extraction:
    """Full extraction. chat_fn defaults to the configured NIM."""
    if chat_fn is None:
        from app.nim.client import chat as chat_fn
    out = chat_fn([{"role": "system", "content": SYSTEM},
                   {"role": "user",
                    "content": f"Return JSON matching this schema:\n{SCHEMA_HINT}\n\n"
                               f"Technician update:\n\"\"\"{text}\"\"\""}],
                  temperature=0.0, max_tokens=900, json_mode=True)
    return validate(parse_json(out), text, known_ros, embed_fn=embed_fn)
