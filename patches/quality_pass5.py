#!/usr/bin/env python3
"""Fifth pass: compose the answer in Python, for a non-technical reader.

Run AFTER quality_pass4.py, from the project root:

    python3 quality_pass5.py

WHY
Three prompt iterations failed on an 8B model. The last one copied the example's
fake ids and fictional content into a real answer, and the grounding rail could
not catch it because "RO-26-0AAAA" is not a valid id pattern. Prompting is the
wrong lever for producing structure, figures and citations on a model this size.

WHAT CHANGES
 1. queries.py - get_technician_activity is enriched from data already in the
    database: each operation gains its plain-English description, category and
    safety flag from labour_ops, and each repair order gains the vehicle, its
    registration and the customer's reported concern from ros.

 2. agent.py - a deterministic renderer composes the whole answer for the
    technician-activity shape: grouped by repair order, vehicle named, customer
    concern quoted, operations given by description rather than op code, hours
    explained against book time in plain words, and a glossary of the trade
    shorthand that appears in the notes.

 3. agent.py - when that renderer applies, the LLM narration call is skipped
    entirely. No copied template, no invented figures, and a technician question
    now costs zero LLM calls - just SQL. Narrative questions routed to
    search_updates still go through the model, so the demo still shows it
    working.

Set ASOIA_DETERMINISTIC=0 to fall back to LLM narration for comparison.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      Run passes 1-4 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# --------------------------------------------- 1. enrich the tool output
edit("app/analytics/queries.py",
     '''    cats = {}
    for c in completed:
        op = OP_BY_CODE.get(c["op_code"])
        if op: cats[op.category] = cats.get(op.category, 0) + 1''',
     '''    # Plain-English context, all of it already in the database. An op code means
    # nothing to a service manager; "30,000 mile service interval" does.
    for c in completed:
        op = OP_BY_CODE.get(c["op_code"])
        if op:
            c["description"] = op.description
            c["category"] = op.category
            c["safety_critical"] = bool(op.safety_critical)
            c["flat_rate_hrs"] = op.flat_rate_hrs
    ro_ctx: dict[str, Any] = {}
    for ron in sorted({c["ro_number"] for c in completed}
                      | {r["ro_number"] for r in recent}):
        v = con.execute(
            "SELECT make, model, model_year, registration, concern, "
            "promised_time, wait_type FROM ros WHERE ro_number=?", (ron,)).fetchone()
        if v:
            ro_ctx[ron] = {
                "vehicle": " ".join(str(x) for x in
                                    (v["model_year"], v["make"], v["model"]) if x),
                "registration": v["registration"], "concern": v["concern"],
                "promised_time": v["promised_time"], "wait_type": v["wait_type"]}
    cats = {}
    for c in completed:
        op = OP_BY_CODE.get(c["op_code"])
        if op: cats[op.category] = cats.get(op.category, 0) + 1''',
     "queries.py  ops + repair orders enriched", skip_if='ro_ctx: dict[str, Any]')

edit("app/analytics/queries.py",
     '            "recent_updates": [dict(r) for r in recent],',
     '            "recent_updates": [dict(r) for r in recent],\n'
     '            "ro_context": ro_ctx,',
     "queries.py  ro_context returned", skip_if='"ro_context": ro_ctx')


# ------------------------------------------- 2. deterministic renderer
RENDERER = '''_JARGON = {
    "R&R":  "remove and refit",
    "C/S":  "customer states",
    "NSF":  "nearside front (front left)",
    "OSF":  "offside front (front right)",
    "NSR":  "nearside rear (rear left)",
    "OSR":  "offside rear (rear right)",
    "NLA":  "no longer available from the manufacturer",
    "TSB":  "technical service bulletin (a manufacturer fix notice)",
    "DTC":  "diagnostic trouble code (a stored fault code)",
    "VHC":  "vehicle health check",
    "CCA":  "cold cranking amps (a measure of battery strength)",
    "QC":   "quality control check",
    "LF":   "left front", "RF": "right front",
    "LR":   "left rear",  "RR": "right rear",
}


def _jargon_in(text: str) -> dict:
    """Trade shorthand present in the text, so a non-technical reader can follow
    the note without it being paraphrased away."""
    found = {}
    for k, v in _JARGON.items():
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])",
                     text, re.I):
            found[k] = v
    return found


def _tech_summary(d: dict) -> str:
    """The whole answer, composed from the record. Every figure is copied, never
    derived, so it is correct by construction."""
    ctx = d.get("ro_context") or {}
    L: list[str] = []

    skill = (d.get("skill") or "").replace("_", " ").title()
    shift = (d.get("shift") or "").title()
    bits = [b for b in (skill, f"{shift} shift" if shift else "") if b]
    who = f"**{d.get('name')}** ({d.get('staff_id')})"
    if bits:
        who += " - " + ", ".join(bits)
    L.append(f"{who} - completed **{d.get('ops_completed')} jobs** across "
             f"**{d.get('ros_touched')} repair orders** in the last "
             f"{d.get('window_days')} days, and posted "
             f"**{d.get('updates_posted')} updates**.")

    hrs, flat, prof = (d.get("hours_booked"), d.get("flat_rate_earned"),
                       d.get("proficiency"))
    if hrs and flat and prof:
        verdict = ("ahead of the standard allowance" if prof > 1.02 else
                   "behind the standard allowance" if prof < 0.98 else
                   "in line with the standard allowance")
        L.append(f"\\nTime: **{hrs} hours** spent on work the manual allows "
                 f"**{flat} hours** for - a ratio of **{prof}**, {verdict}.")

    by_ro: dict = {}
    for c in d.get("completed") or []:
        by_ro.setdefault(c.get("ro_number"), []).append(c)
    if by_ro:
        L.append("\\n**The work, by repair order**")
        for ron, ops in by_ro.items():
            v = ctx.get(ron) or {}
            head = f"\\n**{ron}**"
            if v.get("vehicle"):
                head += f" - {v['vehicle']}"
                if v.get("registration"):
                    head += f", {v['registration']}"
            L.append(head)
            if v.get("concern"):
                L.append(f"- Customer reported: {v['concern']}")
            for c in ops:
                desc = c.get("description") or c.get("op_code")
                flag = "  **safety-critical**" if c.get("safety_critical") else ""
                L.append(f"- {desc} - {c.get('actual_hrs')} hours{flag}")

    notes = d.get("recent_updates") or []
    if notes:
        L.append("\\n**What was written most recently**")
        jargon: dict = {}
        for u in notes[:3]:
            t = " ".join(str(u.get("text") or "").split())
            jargon.update(_jargon_in(t))
            when = str(u.get("at") or "")[:16].replace("T", " ")
            L.append(f'\\n- **{when}**, {u.get("ro_number")} '
                     f'[{u.get("update_id")}]\\n  "{t}"')
        if jargon:
            L.append("\\n**Shorthand used in those notes**")
            for k, v in sorted(jargon.items()):
                L.append(f"- **{k}** - {v}")
    return "\\n".join(L)


def _summarise(results: list[dict]) -> str | None:
    """Compose the answer in Python for shapes we understand. None means the
    LLM should narrate instead."""
    for r in results:
        if r.get("tool") == "get_technician_activity":
            res = r.get("result") or {}
            if res.get("found"):
                return _tech_summary(res)
    return None


def ask('''

edit("app/agent/agent.py", "def ask(", RENDERER,
     "agent.py  deterministic renderer added", skip_if="def _tech_summary(")


# ------------------------------------ 3. bypass the LLM when it applies
edit("app/agent/agent.py",
     '''    payload = _render(ans.results)''',
     '''    summary = (_summarise(ans.results)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    if summary:
        # Composed from the record - no narration call, nothing to hallucinate.
        ans.text = summary
        ans.warnings = check_grounding(ans.text, ans.results)
        ans.grounded = not ans.warnings
        return ans

    payload = _render(ans.results)''',
     "agent.py  LLM skipped when renderer applies", skip_if="ASOIA_DETERMINISTIC")


print("Quality pass 5:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/analytics/queries.py"):
    ast.parse((ROOT / f).read_text())
print("\nBoth files parse cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
print("Compare against the model-written version with:  ASOIA_DETERMINISTIC=0")
