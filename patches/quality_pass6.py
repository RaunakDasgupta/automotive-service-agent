#!/usr/bin/env python3
"""Sixth pass: deterministic answers across every main tool, not just one.

Run AFTER quality_pass5.py, from the project root:

    python3 quality_pass6.py

THE FAULT PATTERN, AGAIN
Asked which vehicles cannot be released on safety grounds, the model said
"11 matches" and listed 7, and gave the customer's concern ("oil spots on the
driveway") as the safety reason. Both faults have the same cause as before:
list_ros records carry `safety: true` but NOT the reason - that lives in
snap.safety_flags, which only get_ro_state exposed - and `count` is the total
while `ros` is capped at `limit`. Missing data, so the model improvised.

LAYER BY LAYER

 1. TOOLS - list_ros records now carry the actual safety findings
    ("front pad thickness 1.8mm below minimum 3.0mm"), the registration, the
    pending work, and a `shown` count so truncation can be stated honestly.

 2. COMPOSITION - deterministic renderers for list_ros, get_ro_state and
    generate_handover, alongside the technician one from pass 5. These are the
    paths behind every demo question. generate_handover already computed
    next_action and per-RO safety details; the model was discarding them.

 3. DISPATCH - if every tool in the plan has a renderer, the answer is composed
    in Python and the LLM is skipped. If any tool does not, the LLM narrates
    everything so nothing is lost.

 4. GUARDRAIL - when the rail does block a model-written answer, the computed
    figures and citations are now shown alongside the refusal instead of the
    user getting a dead end. The rail still visibly fires; the verified data
    survives.

NOTE ON A CONSTRAINT: renderers must never compute a number. check_grounding
flags any 2+ digit integer or decimal absent from the payload, so a derived
count like len(items) would trip it. Every figure printed here is read from the
payload, which is why `shown` is added to list_ros rather than computed.
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
                 "      Run passes 1-5 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ------------------------------------------- 1. list_ros carries the reason
edit("app/analytics/queries.py",
     '''               "safety": snap.has_open_safety, "concern": ro["concern"],
               "pending_count": len(snap.pending_ops), "last_actor": snap.last_actor}''',
     '''               "safety": snap.has_open_safety, "concern": ro["concern"],
               # The REASON, not just the flag. Without this an answer can only
               # say "has a safety concern" or, worse, borrow the concern text.
               "safety_detail": [f["detail"] for f in snap.safety_flags
                                 if not f.get("resolved")],
               "registration": ro["registration"],
               "pending": [o.description for o in snap.pending_ops],
               "pending_count": len(snap.pending_ops), "last_actor": snap.last_actor}''',
     "queries.py  list_ros carries safety findings", skip_if='"safety_detail"')

edit("app/analytics/queries.py",
     '    return {"filter": filter, "count": len(out), "ros": out[:limit]}',
     '    # `shown` lets an answer state truncation honestly instead of implying\n'
     '    # that `count` rows follow.\n'
     '    return {"filter": filter, "count": len(out), "shown": len(out[:limit]),\n'
     '            "ros": out[:limit]}',
     "queries.py  list_ros reports shown count", skip_if='"shown": len(out[:limit])')


# --------------------------------------------- 2. renderers for every path
RENDERERS = '''_RISK_WORDS = {
    "BREACHED": "promised time already missed",
    "AT_RISK":  "at risk of missing the promised time",
    "OK":       "on track",
}

_FILTER_TITLES = {
    "safety":  "cannot be released on safety grounds",
    "blocked": "are blocked and cannot progress",
    "at_risk": "are at risk of missing their promised time",
    "waiter":  "have a customer waiting on site",
    "active":  "are currently open",
    "all":     "are on file",
}

_SHOW_MAX = 12          # display cap; never printed, so it cannot be flagged


def _when(v) -> str:
    return str(v or "")[:16].replace("T", " ")


def _titlecase(v) -> str:
    return str(v or "").replace("_", " ").title()


def _ros_summary(d: dict) -> str:
    """The shop list - safety, blocked, at-risk, waiters."""
    ros = d.get("ros") or []
    filt = str(d.get("filter") or "").lower()
    title = _FILTER_TITLES.get(filt, f"match {filt}")
    if not ros:
        return f"No repair orders {title} at the moment."

    count, shown = d.get("count"), d.get("shown")
    head = f"**{count} repair orders {title}.**"
    if isinstance(count, int) and isinstance(shown, int) and shown < count:
        head += f" Showing {shown}, most urgent first."
    else:
        head += " Most urgent first."
    L = [head]

    for r in ros[:_SHOW_MAX]:
        line = f"\\n**{r.get('ro_number')}**"
        if r.get("vehicle"):
            line += f" - {r['vehicle']}"
        if r.get("registration"):
            line += f", {r['registration']}"
        L.append(line)

        status = f"- Status: {_titlecase(r.get('state'))}"
        risk = _RISK_WORDS.get(r.get("promise_risk"))
        if risk:
            status += f", {risk}"
        if r.get("promised_time"):
            status += f" (promised {_when(r['promised_time'])})"
        L.append(status)

        for s in (r.get("safety_detail") or []):
            L.append(f"- **Safety finding:** {s}")
        if r.get("concern"):
            L.append(f"- Customer reported: {r['concern']}")
        if r.get("blocked") and r.get("blocked_on"):
            L.append(f"- Waiting on: {r['blocked_on']}")
        pend = [p for p in (r.get("pending") or []) if p]
        if pend:
            L.append(f"- Still to do: {'; '.join(pend[:4])}")
        if r.get("wait_type") == "WAITER":
            L.append("- Customer is waiting on site")
    if len(ros) > _SHOW_MAX:
        L.append("\\nThe remainder are listed on the Shop Floor tab.")
    return "\\n".join(L)


def _ro_state_summary(d: dict) -> str:
    """One repair order, in full."""
    if not d.get("found"):
        return str(d.get("error") or "That repair order is not on file.")
    L = []
    head = f"**{d.get('ro_number')}** - {d.get('vehicle')}"
    if d.get("registration"):
        head += f", {d['registration']}"
    if d.get("odometer_miles"):
        head += f" - {d['odometer_miles']} miles"
    L.append(head)

    status = f"Status: **{_titlecase(d.get('state'))}**"
    risk = _RISK_WORDS.get(d.get("promise_risk"))
    if risk:
        status += f" - {risk}"
    if d.get("promised_time"):
        status += f" (promised {_when(d['promised_time'])})"
    L.append(status)
    if d.get("concern"):
        L.append(f"Customer reported: {d['concern']}")
    if d.get("wait_type") == "WAITER":
        L.append("The customer is waiting on site.")

    sf = d.get("safety_flags") or []
    if sf:
        L.append("\\n**Safety - do not release**")
        for f in sf:
            L.append(f"- {f.get('detail')}")
    if d.get("blocked") and d.get("blocked_on"):
        L.append(f"\\n**Blocked** - waiting on {d['blocked_on']}")

    comp = d.get("completed") or []
    if comp:
        h = "\\n**Work completed**"
        hb, fr = d.get("hours_booked"), d.get("flat_rate_total")
        if hb and fr:
            h += f" - {hb} hours booked against {fr} allowed"
        L.append(h)
        for c in comp:
            who = f" ({c['by']})" if c.get("by") else ""
            L.append(f"- {c.get('description') or c.get('op_code')}"
                     f" - {c.get('actual_hrs')} hours{who}")
    for key, label in (("pending", "Still to do"),
                       ("recommended", "Recommended - needs customer authorisation")):
        items = d.get(key) or []
        if items:
            L.append(f"\\n**{label}**")
            for o in items:
                L.append(f"- {o.get('description') or o.get('op_code')}")

    parts = d.get("parts") or []
    if parts:
        L.append("\\n**Parts**")
        for p in parts[:6]:
            if isinstance(p, dict):
                L.append("- " + ", ".join(f"{k} {v}" for k, v in p.items()
                                          if not isinstance(v, (dict, list))))
            else:
                L.append(f"- {p}")
    if d.get("dtc_codes"):
        L.append("\\n**Fault codes recorded:** " + ", ".join(str(c) for c in d["dtc_codes"]))
    conf = d.get("conflicts") or []
    if conf:
        L.append("\\n**Contradictions found in the updates**")
        for c in conf:
            L.append(f"- {_titlecase(c.get('kind'))}: {c.get('detail')}")
    return "\\n".join(L)


def _handover_summary(d: dict) -> str:
    """The prioritised shift handover."""
    t = d.get("totals") or {}
    L = [f"**Shift handover - {_titlecase(d.get('shift'))}**",
         f"\\n{t.get('open')} open repair orders: **{t.get('safety')} with safety "
         f"findings**, {t.get('at_risk')} at risk of missing their promise, "
         f"{t.get('blocked')} blocked, {t.get('pending_ops')} operations still to do."]
    for bucket, items in (d.get("groups") or {}).items():
        items = items or []
        if not items:
            continue
        L.append(f"\\n**{_titlecase(bucket)}**")
        for r in items[:_SHOW_MAX]:
            line = f"\\n- **{r.get('ro_number')}**"
            if r.get("vehicle"):
                line += f" - {r['vehicle']}"
            risk = _RISK_WORDS.get(r.get("promise_risk"))
            if risk:
                line += f", {risk}"
            L.append(line)
            for s in (r.get("safety") or []):
                L.append(f"  - **Safety finding:** {s}")
            if r.get("concern"):
                L.append(f"  - Customer reported: {r['concern']}")
            if r.get("blocked_on"):
                L.append(f"  - Waiting on: {r['blocked_on']}")
            pend = [p for p in (r.get("pending") or []) if p]
            if pend:
                L.append(f"  - Still to do: {'; '.join(pend[:3])}")
            if r.get("next_action"):
                L.append(f"  - **Next action:** {r['next_action']}")
        if len(items) > _SHOW_MAX:
            L.append("\\n  The remainder are on the Shift Handover tab.")
    return "\\n".join(L)


_RENDERERS = {
    "get_technician_activity": lambda res: _tech_summary(res) if res.get("found") else None,
    "list_ros":                _ros_summary,
    "get_ro_state":            _ro_state_summary,
    "generate_handover":       _handover_summary,
}


def _summarise(results: list[dict]) -> str | None:
    """Compose the answer in Python when every tool in the plan has a renderer.

    If any tool does not, return None so the LLM narrates the whole payload
    rather than the answer silently losing part of it.
    """
    blocks = []
    for r in results:
        fn = _RENDERERS.get(r.get("tool"))
        if fn is None:
            return None
        res = r.get("result")
        if not isinstance(res, dict):
            return None
        try:
            out = fn(res)
        except Exception:
            return None
        if not out:
            return None
        blocks.append(out)
    return "\\n\\n".join(blocks) if blocks else None


def ask('''

# Replace the pass-5 dispatcher with the multi-tool one.
edit("app/agent/agent.py",
     '''def _summarise(results: list[dict]) -> str | None:
    """Compose the answer in Python for shapes we understand. None means the
    LLM should narrate instead."""
    for r in results:
        if r.get("tool") == "get_technician_activity":
            res = r.get("result") or {}
            if res.get("found"):
                return _tech_summary(res)
    return None


def ask(''',
     RENDERERS,
     "agent.py  renderers for list_ros / ro_state / handover",
     skip_if="_FILTER_TITLES")


# ------------------------------------------ 4. guardrail degrades gracefully
edit("app/ui/gradio_app.py",
     '''        if not out_gate.allowed:
            body = f"{out_gate.text}\\n\\n_(blocked by {out_gate.rail})_"''',
     '''        if not out_gate.allowed:
            # The narrative is withheld, but the computed figures were never in
            # doubt - show them rather than handing back a dead end.
            from app.agent.agent import _figures
            body = f"{out_gate.text}\\n\\n_(blocked by {out_gate.rail})_"
            fig = _figures(a.results)
            if fig:
                body += ("\\n\\nThese figures come straight from the record and "
                         "are unaffected:\\n" + fig)
            if a.citations:
                body += "\\n\\nSources: " + ", ".join(a.citations[:6])''',
     "gradio_app.py  rail degrades to computed figures",
     skip_if="were never in\\n            # doubt")


print("Quality pass 6:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/analytics/queries.py", "app/ui/gradio_app.py"):
    ast.parse((ROOT / f).read_text())
print("\nAll three files parse cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
