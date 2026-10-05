"""Resolve what a technician said into things that exist in the system.

Two jobs: work out which repair order they mean, and map free-text descriptions
of work onto canonical labour op codes. Both return confidence, because the
pipeline must ask rather than guess when it is unsure.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from rapidfuzz import fuzz, process

from app.data.catalog import LABOUR_OPS, OP_BY_CODE

# "RO eight-eight-seven-one" and friends - dictation produces spoken digits.
_WORDS = {"zero":"0","oh":"0","one":"1","two":"2","three":"3","four":"4","five":"5",
          "six":"6","seven":"7","eight":"8","nine":"9","ten":"10","eleven":"11",
          "twelve":"12","thirteen":"13","fourteen":"14","fifteen":"15","sixteen":"16",
          "seventeen":"17","eighteen":"18","nineteen":"19","twenty":"20","thirty":"30",
          "forty":"40","fifty":"50","sixty":"60","seventy":"70","eighty":"80","ninety":"90"}


@dataclass
class Resolution:
    value: str | None
    confidence: float
    candidates: list[tuple[str, float]]
    reason: str = ""

    RO_THRESHOLD = 0.90      # wrong repair order is catastrophic - be strict
    OP_THRESHOLD = 0.62      # wrong op code is a correctable clarification

    def is_certain(self, threshold: float = RO_THRESHOLD) -> bool:
        return self.value is not None and self.confidence >= threshold

    @property
    def certain(self) -> bool:
        return self.is_certain(self.RO_THRESHOLD)

    @property
    def needs_clarification(self) -> bool:
        return not self.certain


def spoken_digits_to_number(text: str) -> str:
    """'eight eight seven one' -> '8871'. Leaves ordinary text alone."""
    out = []
    for tok in re.split(r"[\s\-]+", text.lower()):
        out.append(_WORDS.get(tok, tok))
    return "".join(out)


def resolve_ro(text: str, known_ros: list[str]) -> Resolution:
    """Find the repair order in a transcript. Handles partials and spoken digits."""
    t = text.upper()
    # 1. Exact RO number.
    for ro in known_ros:
        if ro.upper() in t:
            return Resolution(ro, 1.0, [(ro, 1.0)], "exact RO number")
    # 2. Bare digit run matching an RO suffix, e.g. "08871" or "8871".
    def _runs(sv: str) -> list[str]:
        """Every 4-6 digit substring of each digit run, longest first."""
        out = []
        for run in re.findall(r"\d{4,}", sv):
            for ln in (6, 5, 4):
                for i in range(len(run) - ln + 1):
                    out.append(run[i:i + ln])
            out.append(run)
        return list(dict.fromkeys(out))

    digits = re.findall(r"\b\d{4,6}\b", t) + _runs(t)
    spoken = _runs(spoken_digits_to_number(text))
    for d in dict.fromkeys(digits + spoken):
        hits = [ro for ro in known_ros if ro.replace("-", "").endswith(d.lstrip("0") or "0")
                or ro.endswith(d)]
        if len(hits) == 1:
            return Resolution(hits[0], 0.95, [(hits[0], 0.95)], f"matched suffix {d}")
        if len(hits) > 1:
            return Resolution(None, 0.5, [(h, 0.5) for h in hits[:5]],
                              f"'{d}' matches {len(hits)} repair orders")
    # 3. Fuzzy last resort.
    best = process.extract(t, known_ros, scorer=fuzz.partial_ratio, limit=3)
    if best and best[0][1] >= 88:
        return Resolution(best[0][0], best[0][1] / 100,
                          [(b[0], b[1] / 100) for b in best], "fuzzy match")
    return Resolution(None, 0.0, [(b[0], b[1] / 100) for b in best],
                      "no repair order identified")



# Workshop vocabulary that the catalog descriptions do not literally contain.
# UK/US split (discs vs rotors, tyre vs tire) plus everyday trade shorthand.
ALIASES: dict[str, str] = {
    "disc": "rotor", "discs": "rotors", "tyre": "tyre", "tire": "tyre",
    "regas": "evacuate recharge", "re-gas": "evacuate recharge",
    "aircon": "air conditioning a/c", "air con": "air conditioning a/c",
    "ac": "a/c air conditioning", "a/c": "a/c air conditioning",
    "service": "service interval lube oil filter",
    "oil change": "lube oil filter", "oil and filter": "lube oil filter",
    "plugs": "spark plugs", "cambelt": "timing belt", "cam belt": "timing belt",
    "alternator": "alternator", "starter": "starter motor",
    "battery": "battery", "misfire": "misfire diagnosis",
    "tracking": "alignment", "geometry": "alignment", "aligning": "alignment",
    "bearing": "wheel bearing hub", "wishbone": "control arm",
    "drop link": "sway bar link", "droplink": "sway bar link",
    "track rod": "tie rod", "shocks": "shock absorber", "struts": "strut assembly",
    "exhaust": "exhaust muffler tailpipe", "cat": "catalytic converter",
    "cat converter": "catalytic converter", "dpf": "dpf regeneration",
    "egr": "egr valve", "lambda": "oxygen sensor", "o2 sensor": "oxygen sensor",
    "coil pack": "spark plugs ignition", "brake fluid": "brake fluid flush bleed",
    "pads": "brake pads", "calliper": "caliper", "windscreen": "windscreen",
    "health check": "inspection", "vhc": "inspection", "road test": "road test",
    "scan": "system scan code retrieval", "codes": "system scan code retrieval",
}


def expand_aliases(text: str) -> str:
    """Append canonical vocabulary for any trade shorthand present."""
    low = f" {text.lower()} "
    extra = [v for k, v in ALIASES.items() if f" {k} " in low or f" {k}s " in low]
    return f"{text} {' '.join(extra)}".strip() if extra else text


_OP_TEXTS = {o.op_code: f"{o.description} {o.category}" for o in LABOUR_OPS}



# Axle/corner position. Confusing front with rear on a brake job is a real error,
# so position is matched explicitly rather than left to fuzzy scoring.
_FRONT = {"front", "fr", "nsf", "osf", "forward"}
_REAR  = {"rear", "rr", "back", "nsr", "osr"}


# Words that appear all over the catalogue. Sharing one of these with a candidate
# says nothing about WHICH operation is meant, so an overlap consisting only of
# these is no evidence at all.
_GENERIC = {
    "r", "rr", "and", "the", "a", "of", "per", "single", "both", "two", "four",
    "replacement", "replace", "repair", "remove", "refit", "renew", "fit",
    "fitted", "check", "checked", "inspection", "inspect", "measure", "service",
    "adjust", "adjustment", "clean", "set", "test", "tested", "assembly", "kit",
    "new", "done", "complete", "completed", "out", "full", "system",
    "front", "rear", "left", "right", "fr", "nsf", "osf", "nsr", "osr",
    "maintenance", "diagnostics", "diagnosis", "mile", "interval",
}


def _specific(text: str) -> set[str]:
    """The words in `text` that could identify one operation rather than another."""
    return {t for t in re.split(r"[^a-z0-9/]+", text.lower())
            if len(t) > 1 and t not in _GENERIC}


def _position(text: str) -> str | None:
    toks = set(re.split(r"[^a-z]+", text.lower()))
    f, r = bool(toks & _FRONT), bool(toks & _REAR)
    return "FRONT" if f and not r else "REAR" if r and not f else None


def _op_position(code: str) -> str | None:
    c = code.upper()
    if "-FR-" in c or c.endswith("-FR"): return "FRONT"
    if "-RR-" in c or c.endswith("-RR"): return "REAR"
    d = _OP_TEXTS.get(code, "").lower()
    return _position(d)


def resolve_op(text: str, embed_fn=None, threshold: int = 55) -> Resolution:
    """Map free text onto a labour op code. Lexical first; embeddings if provided."""
    if not text:
        return Resolution(None, 0.0, [], "empty")
    if text.upper() in OP_BY_CODE:
        return Resolution(text.upper(), 1.0, [(text.upper(), 1.0)], "already an op code")
    query = expand_aliases(text).lower()
    blended: dict[str, float] = {}
    for scorer, weight in ((fuzz.token_set_ratio, 0.45), (fuzz.WRatio, 0.30),
                           (fuzz.partial_token_set_ratio, 0.25)):
        for _, sc, code in process.extract(query, _OP_TEXTS, scorer=scorer, limit=8):
            blended[code] = blended.get(code, 0.0) + weight * sc
    want = _position(text)
    if want:
        # Demote operations that name the opposite end of the car.
        for code in list(blended):
            got = _op_position(code)
            if got and got != want:
                blended[code] *= 0.55
    # Demote a candidate whose only overlap with the query is catalogue-wide
    # vocabulary. "tyre replacement front" scored "Engine air filter replacement"
    # highest on the strength of the word "replacement" alone, and the fuzzy
    # scorers cannot tell that apart from a real match.
    q_specific = _specific(query)
    if q_specific:
        for code in list(blended):
            if not (q_specific & _specific(_OP_TEXTS.get(code, ""))):
                blended[code] *= 0.45
    cands = sorted(((c, v / 100) for c, v in blended.items()), key=lambda x: -x[1])[:4]
    if cands and cands[0][1] * 100 >= threshold:
        margin = cands[0][1] - (cands[1][1] if len(cands) > 1 else 0.0)
        if margin < 0.04:
            # A tie in the fuzzy score is often an artefact. "front brake pads and
            # discs" scored BRK-FR-PAD 0.764 and BRK-PARK-ADJ 0.725 - a 0.039
            # margin - but the first shares brake, pads AND rotors with the query
            # while Parking brake adjustment shares only "brake". Break the tie on
            # how much of the query's distinctive vocabulary each one actually
            # covers, and only call it ambiguous when that is level too.
            near = [c for c in cands if cands[0][1] - c[1] < 0.04]
            def _overlap(code):
                return len(q_specific & _specific(_OP_TEXTS.get(code, "")))
            near.sort(key=lambda c: (-_overlap(c[0]), -c[1]))
            best = _overlap(near[0][0])
            rest = max((_overlap(c[0]) for c in near[1:]), default=-1)
            if best > rest:
                return Resolution(near[0][0], min(near[0][1], 0.99), cands,
                                  "lexical match, tie broken on shared vocabulary")
            # Genuinely level. Below the acceptance threshold on purpose, so
            # validate() asks instead of picking. Expressed against OP_THRESHOLD so
            # the two cannot drift apart again: at a flat 0.70 this branch was dead
            # code against a threshold of 0.62, and a dead heat between a 15,000 and
            # a 30,000 mile service was booked without anyone being asked.
            return Resolution(near[0][0], round(Resolution.OP_THRESHOLD - 0.05, 2),
                              cands, "ambiguous between similar operations")
        return Resolution(cands[0][0], min(cands[0][1], 0.99), cands, "lexical match")
    if embed_fn is not None:
        try:
            codes = list(_OP_TEXTS)
            vecs = embed_fn([text] + [_OP_TEXTS[c] for c in codes])
            q, rest = vecs[0], vecs[1:]
            def cos(a, b):
                d = sum(x * y for x, y in zip(a, b))
                na = sum(x * x for x in a) ** 0.5
                nb = sum(y * y for y in b) ** 0.5
                return d / (na * nb + 1e-9)
            sims = sorted(((c, cos(q, v)) for c, v in zip(codes, rest)),
                          key=lambda x: -x[1])[:4]
            if sims[0][1] >= 0.55:
                return Resolution(sims[0][0], sims[0][1], sims, "semantic match")
            return Resolution(None, sims[0][1], sims, "no confident operation match")
        except Exception as e:
            return Resolution(None, 0.0, cands, f"embedding lookup failed: {type(e).__name__}")
    return Resolution(None, cands[0][1] if cands else 0.0, cands, "no confident operation match")
