#!/usr/bin/env python3
"""Seventh pass: fix a real bug in pass 6, and verify the new dashboard UI.

Run AFTER copying the new gradio_app.py into place, from the project root:

    python3 quality_pass7.py

THE BUG
snapshot.parts is a dict - {part_no: {"availability": ...}} - not a list. The
pass-6 _ro_state_summary did `for p in parts[:6]`, which raises KeyError on a
dict. _summarise catches every exception and returns None, so the failure was
silent: every repair-order question fell back to LLM narration and the renderer
never ran. Slicing a dict is the kind of thing that only shows up against real
data, and the broad except hid it.

This pass makes the parts handling dict-aware and, while it is there, renders
availability ("Backorder", "In Stock") rather than dropping it.

It then reports whether the new dashboard UI is installed and wired.
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
                 "      Run passes 1-6 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


edit("app/agent/agent.py",
     '''    parts = d.get("parts") or []
    if parts:
        L.append("\\n**Parts**")
        for p in parts[:6]:
            if isinstance(p, dict):
                L.append("- " + ", ".join(f"{k} {v}" for k, v in p.items()
                                          if not isinstance(v, (dict, list))))
            else:
                L.append(f"- {p}")''',
     '''    parts = d.get("parts") or {}
    if parts:
        L.append("\\n**Parts**")
        # snapshot.parts is {part_no: {"availability": ...}}. Slicing a dict
        # raises, and _summarise swallows it - which silently disabled this
        # whole renderer until it was caught.
        pairs = (list(parts.items()) if isinstance(parts, dict)
                 else [(p, None) for p in parts])
        for name, info in pairs[:8]:
            avail = (info or {}).get("availability") if isinstance(info, dict) else None
            L.append(f"- {name}" + (f" - {_titlecase(avail)}" if avail else ""))''',
     "agent.py  parts rendered from the real dict shape",
     skip_if="pairs = (list(parts.items())")


# --------------------------------------- renderers for the last two tools
# detect_anomalies and diff_ro were the only routed tools still falling through
# to LLM narration. Both are pure structure, so both belong in Python.
NEW_RENDERERS = '''def _anomaly_summary(d: dict) -> str:
    """Cross-RO patterns. Every figure is read from the payload, never derived."""
    L = [f"Patterns across the last {d.get('window_days')} days."]
    if d.get("shared_part_holds"):
        L.append("\\n**One part blocking several jobs** - order once, clear several")
        for x in d["shared_part_holds"]:
            L.append(f"- `{x.get('part_no')}` is holding **{x.get('ro_count')}** repair "
                     f"orders: {', '.join(x.get('ros') or [])}")
    if d.get("authorisation_delays"):
        L.append("\\n**Waiting on customer authorisation**")
        for x in d["authorisation_delays"]:
            tail = " - customer waiting on site" if x.get("wait_type") == "WAITER" else ""
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - "
                     f"**{x.get('waiting_hours')}h** without a decision{tail}")
    if d.get("stalled_ros"):
        L.append("\\n**Stalled - nothing logged for over a day**")
        for x in d["stalled_ros"]:
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - idle "
                     f"**{x.get('idle_hours')}h** in {_titlecase(x.get('state'))}, "
                     f"last touched by {x.get('last_actor')}")
    if d.get("comebacks"):
        L.append("\\n**Comebacks and rework**")
        for x in d["comebacks"]:
            det = x.get("detail")
            det = "; ".join(det) if isinstance(det, list) else (det or "")
            L.append(f"- {x.get('ro_number')} {x.get('vehicle')} - "
                     f"**{x.get('count')}** recorded" + (f": {det}" if det else ""))
    if d.get("repeat_visits"):
        L.append("\\n**Same vehicle back again**")
        for x in d["repeat_visits"]:
            L.append(f"- VIN `{x.get('vin')}` - **{x.get('visits')}** visits: "
                     f"{', '.join(x.get('ros') or [])}")
    if len(L) == 1:
        L.append("\\nNothing unusual in this window.")
    return "\\n".join(L)


def _diff_summary(d: dict) -> str:
    """What changed on one repair order since a cutoff."""
    if not d.get("found"):
        return str(d.get("error") or "That repair order is not on file.")
    L = [f"**{d.get('ro_number')}** - {d.get('vehicle')} - changes in the last "
         f"{d.get('window_hours')} hours"]
    if d.get("state_changed") and d.get("state_before"):
        L.append(f"- Moved from {_titlecase(d.get('state_before'))} to "
                 f"**{_titlecase(d.get('state_now'))}**")
    elif d.get("state_now"):
        L.append(f"- Still in **{_titlecase(d.get('state_now'))}** - no state change")
    for x in d.get("newly_completed") or []:
        L.append(f"- Completed: {x.get('description') or x.get('op_code')}")
    for x in d.get("newly_raised") or []:
        status = f" ({_titlecase(x.get('status'))})" if x.get("status") else ""
        L.append(f"- Raised: {x.get('description') or x.get('op_code')}{status}")
    for s in d.get("new_safety") or []:
        L.append(f"- **New safety finding:** {s}")
    if d.get("technician_changed"):
        L.append(f"- Handed from {d.get('from_actor')} to **{d.get('to_actor')}**")
    risk = _RISK_WORDS.get(d.get("promise_risk"))
    if risk:
        L.append(f"- Promise status: {risk}")
    if len(L) == 1:
        L.append("- Nothing changed in this window.")
    return "\\n".join(L)


_RENDERERS = {
    "get_technician_activity": lambda res: _tech_summary(res) if res.get("found") else None,
    "list_ros":                _ros_summary,
    "get_ro_state":            _ro_state_summary,
    "generate_handover":       _handover_summary,
    "detect_anomalies":        _anomaly_summary,
    "diff_ro":                 _diff_summary,
}'''

edit("app/agent/agent.py",
     '''_RENDERERS = {
    "get_technician_activity": lambda res: _tech_summary(res) if res.get("found") else None,
    "list_ros":                _ros_summary,
    "get_ro_state":            _ro_state_summary,
    "generate_handover":       _handover_summary,
}''',
     NEW_RENDERERS,
     "agent.py  renderers for detect_anomalies and diff_ro",
     skip_if="def _anomaly_summary(")

# "Are any parts holding up more than one job at once?" is the shared-part
# question, but it matched only the `parts hold` rule and answered with a list of
# blocked ROs - never naming the part holding several at once.
edit("app/agent/agent.py",
     '''    (r"\\banomal|pattern|unusual|stalled|stuck|comeback|repeat\\b", "detect_anomalies", {}),''',
     '''    (r"\\banomal|pattern|unusual|stalled|stuck|comeback|repeat|more than one|"
     r"multiple (job|ro)|shared part|same part\\b", "detect_anomalies", {}),''',
     "agent.py  shared-part questions reach detect_anomalies",
     skip_if="shared part|same part")


print("Quality pass 7:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/agent/agent.py").read_text())
print("\nagent.py parses cleanly.")

# ---------------------------------------------------------------- UI report
ui = ROOT / "app/ui/gradio_app.py"
src = ui.read_text() if ui.exists() else ""
try:
    ast.parse(src)
    parses = True
except SyntaxError as e:
    parses = False
    print(f"\ngradio_app.py DOES NOT PARSE: {e}")

checks = [
    ("new dashboard UI installed",      "Five surfaces, not six" in src),
    ("Dashboard tab present",           'gr.Tab("Dashboard")' in src),
    ("KPI tiles",                       "def _kpi_html" in src),
    ("needs-attention table",           "def _action_df" in src),
    ("patterns folded in",              "def _insight_md" in src),
    ("technician RO context",           "def ui_tech_context" in src),
    ("context wired to RO change",      "t_ro.change(ui_tech_context" in src),
    ("context refreshed after submit",  ".then(ui_tech_context" in src),
    ("old Shop Floor tab removed",      'gr.Tab("Shop Floor")' not in src),
    ("old Insights tab removed",        'gr.Tab("Insights")' not in src),
    ("guardrail degradation kept",      "_figures(a.results)" in src),
    ("share switch kept",               'os.environ.get("SHARE"' in src),
]
print("\nDashboard UI:")
missing = 0
for label, ok in checks:
    print(f"  {'ok     ' if ok else 'MISSING'} {label}")
    missing += (not ok)
tabs = src.count("with gr.Tab(")
print(f"\n  tabs: {tabs} (was 6)")
if missing or not parses:
    print("\nCopy the new app/ui/gradio_app.py into place, then run this again.")
else:
    print("\nAll set. Next:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
