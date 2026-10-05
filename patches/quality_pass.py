#!/usr/bin/env python3
"""Response-quality pass for automotive-service-agent.

Run from the project root:   python3 quality_pass.py

Four changes, each idempotent and asserted:

 1. agent.py   SYSTEM prompt - the old one told the model to lead with safety
               items on EVERY question, which is why a "what did EMP014 do"
               question came back headed "Safety items:". Now the priority
               ordering applies only to handover/shop-wide questions, figures
               are mandatory, and the output shape is specified.

 2. agent.py   Tool results are handed to the model as labelled lines instead
               of a single-line JSON dump. An 8B model narrates structured
               text far better than raw JSON. check_grounding still matches
               against the original results object, so grounding is unaffected.

 3. queries.py get_technician_activity also returns the technician's recent
               update texts, so the model has real prose to summarise and
               update_ids to cite, rather than only aggregate counts.

 4. index.py   Fixes the candidate-pool bug: limit() widened the pool to 3x
               the rerank target, then the slice threw it away, so the
               reranker only ever saw k candidates. Now it sees the full pool.
               Defaults widened to retrieve 18 / rerank to 6.
"""
import sys, pathlib

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run this from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1. "
                 "File differs from what this script expects - stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ---------------------------------------------------------------- 1. SYSTEM
OLD_SYSTEM = '''SYSTEM = """You are a service operations assistant for a vehicle workshop.

You answer from TOOL RESULTS ONLY. The tool results are the complete truth
available to you.

Rules:
- Never state a number, date, state or name that is not in the tool results.
- If the tool results do not answer the question, say exactly what is missing.
- Cite the repair order numbers and update ids you used, in square brackets.
- Lead with what needs action. Safety items first, then breached promises,
  then at-risk, then blocked work.
- Be concise and concrete. A service manager is reading this between jobs.
- You may report and advise. You must NEVER authorise work, order parts,
  approve chargeable repairs, or close a repair order - only a person does that.
Write in plain British English."""'''

NEW_SYSTEM = '''SYSTEM = """You are a service operations assistant for a vehicle workshop.

You answer from TOOL RESULTS ONLY. They are the complete truth available to you.

GROUNDING - non-negotiable:
- Never state a number, date, state or name that is not in the tool results.
- Never calculate. Do not sum, average, or derive any figure. Every number you
  write must appear verbatim in the tool results.
- If the tool results do not answer the question, say plainly what is missing.
- Cite the repair order numbers and update ids you used, in square brackets,
  next to the fact they support.

ANSWER THE QUESTION THAT WAS ASKED:
- Direct questions - what a person did, the state of one repair order, what
  changed - answer directly from the figures. Do NOT reorder by urgency and do
  NOT open with a safety preamble.
- Only for shift handovers and shop-wide reviews, lead with what needs action:
  safety first, then breached promises, then at-risk, then blocked work.

SHAPE:
- First line: one sentence that answers the question directly, with the
  headline figure in it.
- Then a short markdown bullet list, one fact per bullet, each with its figure
  and its citation.
- Report every relevant figure the tool results contain - ops completed, hours
  booked, flat-rate earned, proficiency, updates posted, dates. Naming a
  category without its number is not an answer.
- Where update text is provided, quote the specific concern or correction
  rather than summarising it into a generic phrase.
- No headings. No preamble. Do not restate the question. Under 180 words.

AUTHORITY:
- You may report and advise. You must NEVER authorise work, order parts,
  approve chargeable repairs, or close a repair order - only a person does that.

Write in plain British English."""'''

edit("app/agent/agent.py", OLD_SYSTEM, NEW_SYSTEM,
     "agent.py  SYSTEM prompt rewritten", skip_if="GROUNDING - non-negotiable")


# ------------------------------------------------- 2. readable tool payload
RENDER_FN = '''def _render(results: list[dict]) -> str:
    """Tool results as labelled lines. A small model narrates this far better
    than a single-line JSON dump, and every figure stays verbatim so
    check_grounding still matches."""
    def lines(o, pad="", depth=0):
        if depth > 5:
            return pad + json.dumps(o, default=str)[:300]
        if isinstance(o, dict):
            out = []
            for k, v in o.items():
                if isinstance(v, (dict, list)) and v:
                    out.append(f"{pad}{k}:")
                    out.append(lines(v, pad + "  ", depth + 1))
                else:
                    out.append(f"{pad}{k}: {v}")
            return "\\n".join(out)
        if isinstance(o, list):
            out = []
            for x in o[:25]:
                if isinstance(x, list) and not any(isinstance(y, (dict, list)) for y in x):
                    out.append(f"{pad}- " + ", ".join(str(y) for y in x))
                elif isinstance(x, (dict, list)):
                    out.append(f"{pad}-")
                    out.append(lines(x, pad + "  ", depth + 1))
                else:
                    out.append(f"{pad}- {x}")
            if len(o) > 25:
                out.append(f"{pad}... {len(o) - 25} more")
            return "\\n".join(out)
        return f"{pad}{o}"

    blocks = []
    for r in results:
        args = ", ".join(f"{k}={v}" for k, v in (r.get("args") or {}).items())
        blocks.append(f"TOOL {r['tool']}({args})\\n{lines(r.get('result'), '  ')}")
    return "\\n\\n".join(blocks)


def ask('''

edit("app/agent/agent.py", "def ask(", RENDER_FN,
     "agent.py  _render() added", skip_if="def _render(")

edit("app/agent/agent.py",
     "    payload = json.dumps(ans.results, default=str)",
     "    payload = _render(ans.results)",
     "agent.py  ask() uses _render", skip_if="payload = _render(")


# --------------------------------------------- 3. richer technician activity
edit("app/analytics/queries.py",
     '''    cats = {}
    for c in completed:''',
     '''    recent = con.execute(
        "SELECT update_id, ro_number, at, text FROM updates "
        "WHERE staff_id=? AND at>=? ORDER BY at DESC LIMIT 6",
        (staff_id, since)).fetchall()
    cats = {}
    for c in completed:''',
     "queries.py  recent update texts fetched", skip_if="ORDER BY at DESC LIMIT 6")

edit("app/analytics/queries.py",
     '            "window_days": days,',
     '            "window_days": days,\n'
     '            "recent_updates": [dict(r) for r in recent],',
     "queries.py  recent_updates returned", skip_if='"recent_updates"')


# ------------------------------------------------ 4. retrieval candidate pool
edit("app/retrieval/index.py",
     '''    qv = nim_embed([query], input_type="query")[0]
    q = _table(uri).search(qv).limit(max(k, (rerank_to or 0) * 3))''',
     '''    qv = nim_embed([query], input_type="query")[0]
    # Retrieve wide, rerank narrow. cand must be used for BOTH the limit and the
    # slice below - slicing back to k would hide the wide pool from the reranker.
    cand = max(k, (rerank_to or 0) * 3)
    q = _table(uri).search(qv).limit(cand)''',
     "index.py  candidate pool widened", skip_if="cand = max(k,")

edit("app/retrieval/index.py",
     "    hits = q.to_list()[:max(k, 1)]",
     "    hits = q.to_list()[:max(cand, 1)]",
     "index.py  slice keeps the wide pool", skip_if="[:max(cand, 1)]")

edit("app/retrieval/index.py",
     '''def search_updates(query: str, k: int = 4, ro_number: str | None = None) -> dict:
    """Agent-tool shape: grounded passages plus their citations."""
    hits = search(query, k=max(k * 2, 8), rerank_to=k, ro_number=ro_number)''',
     '''def search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:
    """Agent-tool shape: grounded passages plus their citations."""
    hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)''',
     "index.py  defaults widened to 18/6", skip_if="k * 3, 18")


# ------------------------------------------------------------------ report
print("Quality pass:")
for c in CHANGES:
    print(c)

import ast
for f in ("app/agent/agent.py", "app/analytics/queries.py", "app/retrieval/index.py"):
    ast.parse(pathlib.Path(f).read_text())
print("\nAll three files parse cleanly.")
print("Next:  .venv/bin/python -m pytest tests/ -q      then restart Gradio")
