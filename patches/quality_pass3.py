#!/usr/bin/env python3
"""Third pass: latency + reliability. Run AFTER quality_pass2.py, from project root.

    python3 quality_pass3.py

Three changes:

 1. ROUTER ORDER (latency). ask() called plan_llm() first on EVERY question -
    a full extra LLM round trip - and only fell back to the deterministic
    keyword router if that failed. Inverted: the keyword router runs first, and
    the LLM router is consulted only when keyword routing produces nothing but
    the generic search fallback. Every RO question, staff-id question, handover,
    safety/blocked/at-risk query now costs ONE LLM call instead of two.

 2. COMPUTED FIGURES (quality). The figures are all computed in Python already,
    so they no longer depend on the model choosing to mention them. A
    deterministic figures block is appended to every answer. This is the
    project's own principle - compute deterministically, narrate with the LLM -
    carried one step further. Disable with ASOIA_FIGURES=0.

 3. max_tokens 700 -> 400 (latency). The model no longer needs to enumerate
    figures, so it generates far less. Fewer output tokens is directly less
    time-to-answer.
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
                 "      Run quality_pass.py and quality_pass2.py first. "
                 "Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ------------------------------------------------------------- os import
edit("app/agent/agent.py",
     "import json, re",
     "import json, os, re",
     "agent.py  import os", skip_if="import json, os, re")


# --------------------------------------------------- 1. router order swap
edit("app/agent/agent.py",
     '''    plan = plan_llm(question, chat_fn) if use_llm_router else None
    ans.route = "llm" if plan else "keyword"
    plan = plan or plan_keyword(question)''',
     '''    # Keyword routing first: it is deterministic, instant, and handles every
    # RO / staff-id / handover / filter question. The LLM router costs a whole
    # extra round trip, so only consult it when keyword routing found nothing
    # more specific than the catch-all search.
    kw = plan_keyword(question)
    generic = len(kw) == 1 and kw[0]["name"] == "search_updates"
    plan = plan_llm(question, chat_fn) if (use_llm_router and generic) else None
    ans.route = "llm" if plan else "keyword"
    plan = plan or kw''',
     "agent.py  keyword router runs first", skip_if="Keyword routing first")


# ----------------------------------------------- 2. computed figures block
FIGURES_FN = '''_FIG_LABELS = {
    "ops_completed":    "Operations completed",
    "ros_touched":      "Repair orders touched",
    "hours_booked":     "Hours booked",
    "flat_rate_earned": "Flat-rate hours earned",
    "proficiency":      "Proficiency (flat-rate / actual)",
    "updates_posted":   "Updates posted",
    "window_days":      "Window (days)",
    "state":            "State",
    "days_open":        "Days open",
    "promised_at":      "Promised",
    "count":            "Matches",
}


def _figures(results: list[dict]) -> str:
    """Render the figures deterministically from the tool output.

    Every value here is computed in Python, so it is correct and complete
    whether or not the model chose to mention it. Bounded on purpose - this
    appends a short block, not a data dump.
    """
    out: list[str] = []
    for r in results:
        res = r.get("result")
        if not isinstance(res, dict):
            continue
        if res.get("found") is False:
            continue
        for k, label in _FIG_LABELS.items():
            v = res.get(k)
            if v is None or isinstance(v, (dict, list)):
                continue
            out.append(f"- {label}: **{v}**")
        for c in (res.get("completed") or [])[:8]:
            if isinstance(c, dict) and c.get("ro_number"):
                out.append(f"- {c.get('op_code')} on [{c['ro_number']}]"
                           f" - {c.get('actual_hrs')} h")
        cats = res.get("top_categories")
        if isinstance(cats, list) and cats:
            pretty = ", ".join(f"{c[0]} ({c[1]})" for c in cats
                               if isinstance(c, (list, tuple)) and len(c) >= 2)
            if pretty:
                out.append(f"- Categories: {pretty}")
        for u in (res.get("recent_updates") or [])[:3]:
            if isinstance(u, dict) and u.get("text"):
                t = " ".join(str(u["text"]).split())
                if len(t) > 180:
                    t = t[:180] + "..."
                out.append(f'- [{u.get("update_id")}] "{t}"')
    return "\\n".join(dict.fromkeys(out))


def ask('''

edit("app/agent/agent.py", "def ask(", FIGURES_FN,
     "agent.py  _figures() added", skip_if="def _figures(")


# ------------------------------------- 3. wire it in + trim max_tokens
edit("app/agent/agent.py",
     '''                       temperature=0.0, max_tokens=700)
    ans.warnings = check_grounding(ans.text, ans.results)''',
     '''                       temperature=0.0, max_tokens=400)
    if os.environ.get("ASOIA_FIGURES", "1") == "1":
        fig = _figures(ans.results)
        if fig:
            ans.text = (ans.text.rstrip() +
                        "\\n\\n**Figures** (computed from the record, not generated):\\n" +
                        fig)
    ans.warnings = check_grounding(ans.text, ans.results)''',
     "agent.py  figures appended + max_tokens 400", skip_if="ASOIA_FIGURES")


print("Quality pass 3:")
for c in CHANGES:
    print(c)
ast.parse((ROOT / "app/agent/agent.py").read_text())
print("\nagent.py parses cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q     then RESTART Gradio")
print("Disable the figures block at any time with:  ASOIA_FIGURES=0")
