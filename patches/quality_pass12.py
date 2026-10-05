#!/usr/bin/env python3
"""Twelfth pass: response time. Measure it, then cut it - no extra GPU cost.

Run from the project root:   python3 quality_pass12.py

Pass 11 removed the LLM from every day-and-shift question, so the only slow path
left is `search_updates`, which costs four network round trips in sequence:

    router (LLM)  ->  embed query  ->  rerank 18 passages  ->  narrate (LLM)

Four changes, none of which needs another GPU:

1. CACHE THE QUERY EMBEDDING. A demo asks the same handful of questions over and
   over, and every repeat currently pays a full round trip to the embedding NIM
   to turn identical text into an identical vector. An LRU cache on the query
   side removes it. Passage embedding is untouched - that is a one-off at index
   build time and must not be cached.

2. SKIP THE LLM ROUTER WHEN IT CANNOT HELP. `plan_llm` runs whenever keyword
   routing finds nothing more specific than the catch-all search. But if the
   question contains no operational vocabulary at all - no repair order, no staff
   id, no shift, no filter word - there is nothing for the router to route to and
   it returns `search_updates` anyway. That round trip was pure cost. Questions
   that DO carry vocabulary the keyword table missed still get the router.

3. WARM THE ENDPOINTS AT STARTUP. The first request to a NIM after idle carries
   cold-start overhead, so the first question of a demo was always the slowest
   one. A tiny warm-up runs in a background thread as the UI comes up.

4. SHOW THE WORK WHILE IT HAPPENS. `ui_ask` becomes a generator: it names the
   stage it is in, then streams the narration token by token. The deterministic
   answer arrives in one piece, because there is nothing to wait for.

   One honest caveat: streamed text has not been through the grounding rail yet.
   If the rail then blocks the answer, the streamed text is replaced by the
   refusal. That is a visible retraction - but it happens only when the rail
   fires, which is exactly the moment the reader should see that something was
   wrong. Set ASOIA_STREAM=0 to render only gated text.

Also adds scripts/timings.py, because "response time is not ideal" deserves
numbers per stage rather than a guess.
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
                 "      Run passes 1-11 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ==================================================== 1. query embedding cache
edit("app/nim/client.py",
     '''# ----------------------------------------------------------------- embed
def embed(texts: list[str], input_type: str = "passage") -> list[list[float]]:''',
     '''# ----------------------------------------------------------------- embed
@lru_cache(maxsize=512)
def _embed_query_cached(text: str) -> tuple[float, ...]:
    return tuple(embed([text], input_type="query")[0])


def embed_query(text: str) -> list[float]:
    """Embed one search query, caching the result.

    The same question asked twice produces the same vector, so the second round
    trip to the embedding NIM buys nothing. A demo asks a handful of questions
    repeatedly, which makes this most of the embedding traffic.

    Query side only. Passage embedding happens once at index build time, where a
    cache would only consume memory, and where a stale hit would be a correctness
    bug rather than a saving.
    """
    return list(_embed_query_cached(text))


def embed(texts: list[str], input_type: str = "passage") -> list[list[float]]:''',
     "client.py  cache query embeddings",
     skip_if="def embed_query")

edit("app/nim/client.py",
     '''from typing import Any''',
     '''from functools import lru_cache
from typing import Any''',
     "client.py  import lru_cache",
     skip_if="from functools import lru_cache")

edit("app/retrieval/index.py",
     '''from app.nim.client import embed as nim_embed, rerank as nim_rerank''',
     '''from app.nim.client import (embed as nim_embed, embed_query as nim_embed_query,
                            rerank as nim_rerank)''',
     "index.py  import the cached query embedder",
     skip_if="embed_query as nim_embed_query")

edit("app/retrieval/index.py",
     '''    qv = nim_embed([query], input_type="query")[0]''',
     '''    qv = nim_embed_query(query)''',
     "index.py  use it in search()",
     skip_if="nim_embed_query(query)")


# ==================================================== 2. streaming chat
edit("app/nim/client.py",
     '''# ----------------------------------------------------------------- embed
@lru_cache(maxsize=512)''',
     '''def chat_stream(messages: list[dict], temperature: float = 0.0,
                max_tokens: int = 1024, timeout: float = 120.0):
    """Yield the narration as it is generated.

    Same request as chat() with stream=true, parsed from the server-sent event
    stream. Deliberately not retried: half a response has already been shown to
    the reader, so a retry would restart the text in front of them. The caller
    falls back to chat() if this raises before yielding anything.
    """
    base, model, mode = resolve("llm")
    local = (mode == "local")
    if not local:
        _LIMITER.wait()
    payload: dict[str, Any] = {"model": model, "messages": messages,
                               "temperature": temperature,
                               "max_tokens": max_tokens, "stream": True}
    with httpx.stream("POST", f"{base}/chat/completions", json=payload,
                      headers=_headers(local), timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                return
            try:
                delta = json.loads(body)["choices"][0].get("delta", {})
            except Exception:
                continue            # a keep-alive or a partial frame
            piece = delta.get("content")
            if piece:
                yield piece


# ----------------------------------------------------------------- embed
@lru_cache(maxsize=512)''',
     "client.py  chat_stream",
     skip_if="def chat_stream")


# ==================================================== 3. skip the pointless router
# One planner, shared by ask() and the streaming UI. Two copies of this decision
# would drift, and a question answered by different tools depending on whether
# the UI happened to stream would be a very hard bug to see.
edit("app/agent/agent.py",
     '''    kw = plan_keyword(question)
    generic = len(kw) == 1 and kw[0]["name"] == "search_updates"
    plan = plan_llm(question, chat_fn) if (use_llm_router and generic) else None
    ans.route = "llm" if plan else "keyword"
    plan = plan or kw''',
     '''    plan, ans.route = plan_for(question, chat_fn, use_llm_router)''',
     "agent.py  ask() uses the shared planner",
     skip_if="plan_for(question, chat_fn, use_llm_router)")

# That comment described the routing logic that has just moved into plan_for,
# where it now lives as a docstring. Leaving it here is how comments start lying.
edit("app/agent/agent.py",
     '''    # Keyword routing first: it is deterministic, instant, and handles every
    # RO / staff-id / handover / filter question. The LLM router costs a whole
    # extra round trip, so only consult it when keyword routing found nothing
    # more specific than the catch-all search.
    plan, ans.route = plan_for''',
     '''    # Routing, and the decision not to pay for the LLM router - see plan_for.
    plan, ans.route = plan_for''',
     "agent.py  drop the comment that moved with the code",
     skip_if="not to pay for the LLM router - see plan_for")

edit("app/agent/agent.py",
     '''def check_grounding(text: str, results: list[dict]) -> list[str]:''',
     '''_ROUTABLE_RE = re.compile(
    r"\\bro\\b|repair order|job|vehicle|car|tech\\w*|advisor|foreman|part|shift|"
    r"handover|promis\\w*|safety|blocked|waiting|outstanding|overdue|status|state|"
    r"open|closed|invoiced", re.I)


def plan_for(question: str, chat_fn=None,
             use_llm_router: bool = True) -> tuple[list[dict], str]:
    """Decide which tools to run, and say which router decided it.

    Keyword routing runs first because the LLM router costs a whole round trip.
    It is consulted only when keyword routing found nothing more specific than
    the catch-all search AND the question names something operational. A question
    with no operational vocabulary in it at all - "has anyone seen a whistling
    noise" - gives the router nothing to route to: it returns search_updates as
    well, one round trip later, on the slowest path in the system.

    Single source of truth on purpose: ask() and the streaming UI both call this.
    """
    kw = plan_keyword(question)
    generic = len(kw) == 1 and kw[0]["name"] == "search_updates"
    routable = bool(RO_RE.search(question) or ID_RE.search(question)
                    or _timeframe(question) or _ROUTABLE_RE.search(question))
    plan = (plan_llm(question, chat_fn)
            if (use_llm_router and generic and routable) else None)
    return (plan or kw), ("llm" if plan else "keyword")


def check_grounding(text: str, results: list[dict]) -> list[str]:''',
     "agent.py  plan_for: one planner, and no router call that cannot help",
     skip_if="def plan_for")


# ==================================================== 4. a streaming ui_ask
edit("app/ui/gradio_app.py",
     '''def ui_ask(question, history):
    """Manager assistant. Guardrails on the way in and on the way out."""
    from app.guardrails.rails import check_input, check_output
    history = history or []
    q = (question or "").strip()
    if not q:
        return history, ""
    gate = check_input(q)
    if not gate.allowed:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant",
                        "content": f"{gate.text}\\n\\n_(blocked by {gate.rail})_"})
        return history, ""
    try:
        from app.agent.agent import ask
        a = ask(q)''',
     '''def _warm_nims() -> None:
    """Take the cold start off the first question of a demo.

    The first request to a NIM after idle pays engine and cache warm-up, so
    without this the opening question of a demo is always the slowest one. Runs
    in a background thread and swallows everything: a workshop with no GPU
    endpoints must still get a UI.
    """
    def go():
        try:
            from app.nim.client import chat, embed_query
            embed_query("warm up")
            chat([{"role": "user", "content": "ok"}], max_tokens=1)
        except Exception:
            pass
    import threading
    threading.Thread(target=go, daemon=True).start()


def _footer(a) -> str:
    """The provenance line under an answer: which tools, which path, what sources."""
    how = ("computed from the records"
           if getattr(a, "composed", "") == "python" else "narrated by the model")
    foot = (f"\\n\\n---\\nTools: {', '.join(c['name'] for c in a.tool_calls)}"
            f"  ·  {how}")
    cites = ", ".join(a.citations[:6])
    if cites:
        foot += f"  ·  Sources: {cites}"
    if getattr(a, "compose_notes", None):
        foot += ("\\n\\n_Fell back to the model: "
                 + "; ".join(a.compose_notes[:2]) + "_")
    return foot


def ui_ask(question, history):
    """Manager assistant. Guardrails on the way in and on the way out.

    A generator, so the reader sees the stage the pipeline is in rather than a
    still screen. A deterministic answer needs no model call and arrives whole;
    only narration streams.
    """
    from app.guardrails.rails import check_input, check_output
    history = history or []
    q = (question or "").strip()
    if not q:
        yield history, ""
        return
    gate = check_input(q)
    if not gate.allowed:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant",
                        "content": f"{gate.text}\\n\\n_(blocked by {gate.rail})_"})
        yield history, ""
        return

    history = history + [{"role": "user", "content": q},
                         {"role": "assistant", "content": "_Reading the records..._"}]
    yield history, ""

    stream = os.environ.get("ASOIA_STREAM", "1") == "1"
    if stream:
        try:
            for h, done in _ask_streaming(q, history):
                history = h
                if not done:
                    yield history, ""
            yield history, ""
            return
        except Exception as e:
            history[-1]["content"] = f"_Streaming unavailable ({type(e).__name__}), " \\
                                     f"answering in one piece..._"
            yield history, ""

    try:
        from app.agent.agent import ask
        a = ask(q)''',
     "gradio_app.py  ui_ask becomes a generator",
     skip_if="def _warm_nims")

edit("app/ui/gradio_app.py",
     '''    except Exception as e:
        body = (f"The assistant needs a reachable LLM endpoint. "
                f"({type(e).__name__}: {str(e)[:160]})")
    history.append({"role": "user", "content": q})
    history.append({"role": "assistant", "content": body})
    return history, ""''',
     '''    except Exception as e:
        body = (f"The assistant needs a reachable LLM endpoint. "
                f"({type(e).__name__}: {str(e)[:160]})")
    history[-1]["content"] = body
    yield history, ""


def _ask_streaming(q, history):
    """Run the pipeline, yielding (history, done) as each stage completes.

    The plan and the tools run first, so by the time anything is streamed the
    facts are already fixed - only the wording is still arriving. A deterministic
    answer therefore never streams: it is already complete.
    """
    from app.agent.agent import (plan_for, _summarise, _collect_citations,
                                 check_grounding, check_negations, SYSTEM,
                                 _render, _figures, Answer)
    from app.agent.tools import call
    from app.guardrails.rails import check_output
    from app.nim.client import chat, chat_stream

    a = Answer(question=q)
    a.tool_calls, a.route = plan_for(q)
    history[-1]["content"] = ("_Reading the records: "
                              + ", ".join(c["name"] for c in a.tool_calls) + "..._")
    yield history, False

    for step in a.tool_calls:
        a.results.append({"tool": step["name"], "args": step.get("args", {}),
                          "result": call(step["name"], **step.get("args", {}))})
    a.citations = _collect_citations(a.results)

    notes: list = []
    summary = (_summarise(a.results, notes)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    a.compose_notes = notes
    if summary:
        a.composed, a.text = "python", summary
        a.warnings = check_grounding(a.text, a.results)
    else:
        a.composed = "llm"
        payload = _render(a.results)[:22000]
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Question: {q}\\n\\nRECORDS:\\n{payload}"}]
        history[-1]["content"] = "_Writing..._"
        yield history, False
        acc = ""
        try:
            for piece in chat_stream(msgs, temperature=0.0, max_tokens=400):
                acc += piece
                history[-1]["content"] = acc
                yield history, False
        except Exception:
            if not acc:                      # nothing shown yet - fall back cleanly
                acc = chat(msgs, temperature=0.0, max_tokens=400)
        a.text = acc
        if os.environ.get("ASOIA_FIGURES", "1") == "1":
            fig = _figures(a.results)
            if fig:
                a.text = (a.text.rstrip() + "\\n\\n**Figures** (computed from the "
                          "record, not generated):\\n" + fig)
        a.warnings = check_grounding(a.text, a.results)
        if os.environ.get("ASOIA_NEGATION_RAIL", "1") == "1":
            a.warnings += check_negations(a.text)
    a.grounded = not a.warnings

    g = check_output(a)
    if not g.allowed:
        body = f"{g.text}\\n\\n_(blocked by {g.rail})_"
        fig = _figures(a.results)
        if fig:
            body += ("\\n\\nThese figures come straight from the record and "
                     "are unaffected:\\n" + fig)
        if a.citations:
            body += "\\n\\nSources: " + ", ".join(a.citations[:6])
    else:
        body = a.text + _footer(a)
    history[-1]["content"] = body
    yield history, True''',
     "gradio_app.py  _ask_streaming pipeline",
     skip_if="def _ask_streaming")

edit("app/ui/gradio_app.py",
     '''    return demo


if __name__ == "__main__":''',
     '''    _warm_nims()
    return demo


if __name__ == "__main__":''',
     "gradio_app.py  warm the endpoints at startup",
     skip_if="_warm_nims()\n    return demo")

edit("app/ui/gradio_app.py",
     '''                "What has EMP014 done this week?",
                "Go ahead and order the parts for RO-26-08165",''',
     '''                "What has EMP014 done this week?",
                "Who worked in the afternoon yesterday?",
                "Go ahead and order the parts for RO-26-08165",''',
     "gradio_app.py  offer the shift question as an example",
     skip_if='"Who worked in the afternoon yesterday?",')

edit("app/ui/gradio_app.py",
     '''        else:
            cites = ", ".join(a.citations[:6])
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
     '''        else:
            body = a.text + _footer(a)''',
     "gradio_app.py  one footer, not two",
     # _ask_streaming already contains `body = a.text + _footer(a)` at a shallower
     # indent, so the skip test has to be the indented copy this edit produces.
     skip_if="        else:\n            body = a.text + _footer(a)")



# ==================================================== 5. a way to measure it
p = ROOT / "scripts/timings.py"
if p.exists():
    CHANGES.append("  skip  scripts/timings.py (already present)")
else:
    p.parent.mkdir(exist_ok=True)
    p.write_text('''#!/usr/bin/env python3
"""Time each stage of the pipeline, per question class.

    .venv/bin/python scripts/timings.py
    .venv/bin/python scripts/timings.py --repeat 3

Reports, for each question: which tools ran, whether the answer was composed in
Python or narrated, and the wall time. Run it twice - the second run shows what
the query-embedding cache and a warm endpoint are worth.

"Response time is not ideal" is worth a number rather than an impression, and
the number that matters is per class: a deterministic answer should be tens of
milliseconds, and only search should cost seconds.
"""
from __future__ import annotations
import argparse, os, statistics, sys, time

sys.path.insert(0, ".")

QUESTIONS = [
    "Which vehicles cannot be released on safety grounds?",
    "Give me the afternoon handover, worst first.",
    "What has EMP014 done this week?",
    "Who worked in the afternoon yesterday?",
    "Any unusual patterns in the shop this week?",
    "has anyone seen a whistling noise on a Passat",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/agent")):
        print("Run from the project root:\\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/timings.py")
        return 2

    from app.agent.agent import ask
    print(f"ASOIA_NOW = {os.environ.get('ASOIA_NOW', '(wall clock)')}")
    print(f"{args.repeat} runs each; the first pays cold start and a cold cache.\\n")
    print(f"{'path':7s} {'best':>8s} {'median':>8s}  question")
    print("-" * 78)
    slow = []
    for q in QUESTIONS:
        times, a = [], None
        for _ in range(args.repeat):
            t = time.perf_counter()
            try:
                a = ask(q)
            except Exception as e:
                print(f"{'ERROR':7s} {'':>8s} {'':>8s}  {q}\\n"
                      f"        {type(e).__name__}: {str(e)[:90]}")
                a = None
                break
            times.append((time.perf_counter() - t) * 1000)
        if not times or a is None:
            continue
        path = getattr(a, "composed", "?")
        best, med = min(times), statistics.median(times)
        print(f"{path:7s} {best:7.0f}ms {med:7.0f}ms  {q}")
        print(f"{'':7s} {'':>8s} {'':>8s}  tools: "
              f"{', '.join(c['name'] for c in a.tool_calls)}")
        if best > 1500:
            slow.append((best, q))
    print()
    if slow:
        print("Over 1.5s, so still making model calls:")
        for ms, q in sorted(slow, reverse=True):
            print(f"  {ms:6.0f}ms  {q}")
    else:
        print("Every question under 1.5s.")
    print("\\nA 'python' path makes no LLM call at all - if one of those is slow, "
          "the time is SQL or the event fold, not the GPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''')
    CHANGES.append("  ok    scripts/timings.py  per-stage measurement")


# ==================================================== verify
print("Quality pass 12:")
for c in CHANGES:
    print(c)
for f in ("app/nim/client.py", "app/retrieval/index.py", "app/agent/agent.py",
          "app/ui/gradio_app.py", "scripts/timings.py"):
    ast.parse((ROOT / f).read_text())
print("\nclient.py, index.py, agent.py, gradio_app.py and timings.py parse cleanly.")

import os, re as _re
src = (ROOT / "app/ui/gradio_app.py").read_text()
checks = [
    ("ui_ask is a generator (it yields)",
     bool(_re.search(r"def ui_ask\(.*?\n(?:.|\n)*?yield history", src))),
    ("no `return history, \"\"` left in ui_ask",
     "    return history, \"\"" not in src.split("def _ask_streaming")[0]
     .split("def ui_ask")[1]),
    ("warm-up is wired into build()", "_warm_nims()\n    return demo" in src),
    ("streaming can be switched off", "ASOIA_STREAM" in src),
]
print("\nUI wiring:")
bad = 0
for name, ok in checks:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# the router skip must not change any verified routing decision
asrc = (ROOT / "app/agent/agent.py").read_text()
import re, datetime
ns = {"re": re, "_clock": lambda: datetime.datetime.fromisoformat("2026-09-24T16:55:00")}
exec(asrc[asrc.index("_WEEKDAYS = {"):asrc.index("RO_RE = re.compile")], ns)
ns.update({"RO_RE": re.compile(r"\bRO[- ]?\d{2}[- ]?\d{4,5}\b", re.I),
           "ID_RE": re.compile(r"\b(EMP|ADV|FOR|PRT|MGR)\d{3}\b", re.I)})
routable_src = asrc[asrc.index("    routable = bool("):asrc.index("    plan = (plan_llm")]
exec(asrc[asrc.index("_ROUTABLE_RE = re.compile"):asrc.index("def plan_for")], ns)
ROUTABLE = [
    ("has anyone seen a whistling noise on a Passat",        False),  # no router call
    ("any notes about a burning smell",                      False),
    ("what is the status of the Golf",                       True),   # worth asking
    ("is anything outstanding on the courtesy car",           True),
]
print("\nrouter is consulted only when it could help:")
for q, want in ROUTABLE:
    loc = dict(ns); loc["question"] = q
    exec(routable_src.replace("    routable", "routable"), loc)
    got = bool(loc["routable"])
    ok = got == want
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} router {'asked' if got else 'skipped'}"
          f"  <- {q}")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll pass-12 checks behaved as expected.")
print("\nNext:  .venv/bin/python scripts/verify_answers.py")
print("Then:  .venv/bin/python scripts/timings.py --repeat 3")
print("Then:  restart Gradio")
