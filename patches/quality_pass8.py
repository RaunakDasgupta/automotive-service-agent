#!/usr/bin/env python3
"""Eighth pass: close the accuracy holes and make the compose path observable.

Run AFTER quality_pass7.py, from the project root:

    python3 quality_pass8.py

THREE PROBLEMS, ALL FOUND BY AUDIT RATHER THAN BY A VISIBLE FAILURE

 1. MISSING CITATIONS BLOCK CORRECT ANSWERS.
    _collect_citations harvests ids from keys named citations, event_ids,
    update_id, event_id and ro_number. detect_anomalies puts its repair order
    numbers in lists named `ros` - so an answer about shared parts or repeat
    visits produces ZERO citations, and check_output blocks it, even though it
    was composed deterministically and is correct. Verified: shared_part_holds
    and repeat_visits both yield [] today. `ros` and `ro_numbers` are now
    harvested too.

 2. THE FALLBACK WAS SILENT.
    _summarise catches every exception and returns None, so a renderer crash
    degrades to LLM narration with nobody told. That is exactly how the parts
    dict bug survived a whole pass. It now records why it fell back, warns on
    stderr, and the reason is carried on the Answer and shown in the UI.

 3. THE ANSWER DID NOT SAY HOW IT WAS BUILT.
    Answer now carries `composed` ("python" or "llm") and `compose_notes`, and
    the assistant footer states which path produced the text. A degradation is
    now visible in the demo instead of looking like a normal answer.
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
                 "      Run passes 1-7 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ------------------------------------------------- 1. harvest `ros` lists
edit("app/agent/agent.py",
     '                if k in ("citations", "event_ids") and isinstance(v, list):',
     '                # `ros` matters: detect_anomalies puts its repair order\n'
     '                # numbers there, and without it a correct shared-part or\n'
     '                # repeat-visit answer cites nothing and the rail blocks it.\n'
     '                if k in ("citations", "event_ids", "ros", "ro_numbers") \\\n'
     '                        and isinstance(v, list):',
     "agent.py  citations harvested from ros lists",
     skip_if='"ros", "ro_numbers"')


# ------------------------------------------- 2/3. observable compose path
edit("app/agent/agent.py",
     '''    warnings: list[str] = field(default_factory=list)
    route: str = "keyword"''',
     '''    warnings: list[str] = field(default_factory=list)
    route: str = "keyword"
    composed: str = "llm"                 # "python" | "llm" - which path wrote text
    compose_notes: list[str] = field(default_factory=list)''',
     "agent.py  Answer records the compose path", skip_if='composed: str = "llm"')

edit("app/agent/agent.py",
     '''def _summarise(results: list[dict]) -> str | None:
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
    return "\\n\\n".join(blocks) if blocks else None''',
     '''def _summarise(results: list[dict], notes: list | None = None) -> str | None:
    """Compose the answer in Python when every tool in the plan has a renderer.

    If any tool does not, return None so the LLM narrates the whole payload
    rather than the answer silently losing part of it.

    Every reason for falling back is recorded in `notes` and warned on stderr.
    A silent fallback once hid a renderer crash for an entire release; it should
    never be possible to degrade to narration without a trace.
    """
    def note(msg: str):
        if notes is not None:
            notes.append(msg)
        print(f"[compose] falling back to the model: {msg}", file=_sys.stderr)

    blocks = []
    for r in results:
        tool = r.get("tool")
        fn = _RENDERERS.get(tool)
        if fn is None:
            note(f"no renderer for {tool}")
            return None
        res = r.get("result")
        if not isinstance(res, dict):
            note(f"{tool} returned {type(res).__name__}, expected dict")
            return None
        try:
            out = fn(res)
        except Exception as ex:
            note(f"renderer for {tool} raised {type(ex).__name__}: {ex}")
            return None
        if not out:
            note(f"renderer for {tool} produced nothing")
            return None
        blocks.append(out)
    if not blocks:
        note("no tool results to compose from")
        return None
    return "\\n\\n".join(blocks)''',
     "agent.py  fallback reasons recorded and logged", skip_if="def note(msg: str):")

edit("app/agent/agent.py",
     "import json, os, re",
     "import json, os, re\nimport sys as _sys",
     "agent.py  stderr import", skip_if="import sys as _sys")

edit("app/agent/agent.py",
     '''    summary = (_summarise(ans.results)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    if summary:
        # Composed from the record - no narration call, nothing to hallucinate.
        ans.text = summary
        ans.warnings = check_grounding(ans.text, ans.results)
        ans.grounded = not ans.warnings
        return ans''',
     '''    notes: list[str] = []
    summary = (_summarise(ans.results, notes)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    ans.compose_notes = notes
    if summary:
        # Composed from the record - no narration call, nothing to hallucinate.
        # Grounding still runs: a renderer bug must not get a free pass either.
        ans.composed = "python"
        ans.text = summary
        ans.warnings = check_grounding(ans.text, ans.results)
        ans.grounded = not ans.warnings
        return ans
    ans.composed = "llm"''',
     "agent.py  ask() records how the answer was built", skip_if='ans.composed = "python"')


# ------------------------------------------------------- UI shows the path
edit("app/ui/gradio_app.py",
     '''            cites = ", ".join(a.citations[:6])
            body = a.text + (f"\\n\\n---\\nTools: {', '.join(c['name'] for c in a.tool_calls)}"
                             f"  ·  Sources: {cites}" if cites else "")''',
     '''            cites = ", ".join(a.citations[:6])
            how = ("computed from the records"
                   if getattr(a, "composed", "") == "python" else "narrated by the model")
            foot = (f"\\n\\n---\\nTools: {', '.join(c['name'] for c in a.tool_calls)}"
                    f"  ·  {how}")
            if cites:
                foot += f"  ·  Sources: {cites}"
            # A degradation should be visible, not silently indistinguishable
            # from a normal answer.
            if getattr(a, "compose_notes", None):
                foot += ("\\n\\n_Fell back to the model: "
                         + "; ".join(a.compose_notes[:2]) + "_")
            body = a.text + foot''',
     "gradio_app.py  footer states how the answer was built",
     skip_if="computed from the records")


print("Quality pass 8:")
for c in CHANGES:
    print(c)
for f in ("app/agent/agent.py", "app/ui/gradio_app.py"):
    ast.parse((ROOT / f).read_text())
print("\nBoth files parse cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q")
print("Then:  .venv/bin/python verify_answers.py      <- proves it against your data")
