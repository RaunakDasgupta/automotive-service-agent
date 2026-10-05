#!/usr/bin/env python3
"""Fourteenth pass: the one model call, sharpened. And find the truncation.

Run from the project root:   python3 quality_pass14.py

WHAT THE SPLIT SAID

    of which: model 2518ms, rerank 137ms, embed 0ms, the rest 22ms

- embed 0ms: the query cache is working.
- rerank 137ms: eighteen candidates through a 4B cross-encoder costs almost
  nothing. Narrowing the pool would save perhaps 45ms and cost answer quality.
  NOT A LEVER - leave it alone.
- model 2518ms: 94% of it. This is where the pass goes.

TWO FINDINGS

1. 56% OF THE SYSTEM PROMPT IS ABOUT A PAYLOAD THIS PATH DOES NOT HAVE. The
   DIGITS, SHAPE and worked-example sections - 468 of 822 tokens - were written to
   stop the model formatting figures out of a structured tool payload. Every
   structured question now composes in Python, so the ONLY question that still
   reaches the model is a free-text search, whose payload is technician prose.
   Those 468 tokens are prefill on every one of them, and worse, they push the
   model toward a bulleted figures shape when what is wanted is a summary of what
   people wrote.

   `SYSTEM_SEARCH` is fitted to the job: grounding, citations, no-absence and
   authority kept; the structured-payload machinery dropped; an explicit six
   sentence ceiling, which is the part that shortens generation. Selected by
   `_narration_system()`, which ask() and the streaming UI both call - the same
   single-source-of-truth rule as plan_for.

2. TRUNCATION IS INVISIBLE. `chat()` returns
   `data["choices"][0]["message"]["content"]` and throws away `finish_reason`. If
   the model hits max_tokens the answer stops mid-sentence and NOTHING says so.
   At 2518ms of generation against a 400 token cap that is a live possibility,
   and an answer cut off in front of an audience is the worst failure mode this
   system has - it looks like the model broke.

   Both chat() and chat_stream() now fill an optional `meta` dict with
   finish_reason and the token counts. A truncated narration becomes a visible
   warning rather than a silent cut. Callers that pass no meta are unaffected.

`scripts/timings.py` also reports completion tokens and tokens/second, so
"2518ms" can be read as either a long answer or a slow one.
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
                 "      Run passes 1-13 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


# ==================================================== 1. meta from the model call
edit("app/nim/client.py",
     '''def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
         json_mode: bool = False, stop: list[str] | None = None) -> str:''',
     '''def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024,
         json_mode: bool = False, stop: list[str] | None = None,
         meta: dict | None = None) -> str:
    """Complete a chat turn.

    Pass `meta` to learn how the completion ended. `finish_reason == "length"`
    means the model ran into max_tokens and the text stops mid-sentence - which
    was previously thrown away with the rest of the response envelope, so a
    truncated answer was indistinguishable from a finished one.
    """''',
     "client.py  chat() can report finish_reason",
     skip_if="meta: dict | None = None) -> str:")

edit("app/nim/client.py",
     '''    data = _post(f"{base}/chat/completions", payload, local=(mode == "local"))
    return data["choices"][0]["message"]["content"]''',
     '''    data = _post(f"{base}/chat/completions", payload, local=(mode == "local"))
    choice = data["choices"][0]
    if meta is not None:
        meta["finish_reason"] = choice.get("finish_reason")
        usage = data.get("usage") or {}
        meta["prompt_tokens"] = usage.get("prompt_tokens")
        meta["completion_tokens"] = usage.get("completion_tokens")
    return choice["message"]["content"]''',
     "client.py  fill meta from the response envelope",
     skip_if='meta["finish_reason"] = choice.get')

edit("app/nim/client.py",
     '''def chat_stream(messages: list[dict], temperature: float = 0.0,
                max_tokens: int = 1024, timeout: float = 120.0):''',
     '''def chat_stream(messages: list[dict], temperature: float = 0.0,
                max_tokens: int = 1024, timeout: float = 120.0,
                meta: dict | None = None):''',
     "client.py  chat_stream takes meta",
     skip_if="timeout: float = 120.0,\n                meta: dict | None = None):")

edit("app/nim/client.py",
     '''            try:
                delta = json.loads(body)["choices"][0].get("delta", {})
            except Exception:
                continue            # a keep-alive or a partial frame
            piece = delta.get("content")
            if piece:
                yield piece''',
     '''            try:
                frame = json.loads(body)
                choice = frame["choices"][0]
            except Exception:
                continue            # a keep-alive or a partial frame
            if meta is not None:
                # The last frame carries the reason; usage arrives only if the
                # server was asked for it, so treat both as optional.
                if choice.get("finish_reason"):
                    meta["finish_reason"] = choice["finish_reason"]
                usage = frame.get("usage") or {}
                if usage:
                    meta["prompt_tokens"] = usage.get("prompt_tokens")
                    meta["completion_tokens"] = usage.get("completion_tokens")
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield piece''',
     "client.py  fill meta from the stream",
     skip_if='if choice.get("finish_reason"):')


# ==================================================== 2. a prompt for prose
edit("app/agent/agent.py",
     '''KEYWORDS = [
    (r"\\bhandover|hand over|shift (brief|summary|change)\\b", "generate_handover", {}),''',
     '''# The narration prompt for a free-text search - the only question class that
# still reaches the model. SYSTEM above is 822 tokens, and 468 of them are the
# DIGITS, SHAPE and worked-example sections: machinery for stopping the model
# formatting figures out of a structured tool payload. A search payload is
# technician prose, so those tokens are prefill on every search question and they
# push the answer toward a bulleted figures shape instead of a summary of what
# people actually wrote. What matters here is kept; the rest is gone.
SYSTEM_SEARCH = """You are a service operations assistant for a vehicle workshop.

You are given technician updates retrieved from the workshop's own records, in
answer to a question. Summarise what they say. Nothing else is available to you.

GROUNDING:
- Report only what the passages say. Never add a fact, figure, name or date that
  is not in them.
- Copy figures exactly as written, with their units. Never round, convert or add
  anything up.
- If the passages do not answer the question, say so plainly, and say what they
  do cover instead.

NEVER CLAIM AN ABSENCE:
- These are the updates that matched a search, not the whole record. Never write
  that something did not happen, that nobody did something, or that a vehicle has
  no such history. You cannot see what was not retrieved.

CITATIONS:
- Put the update id in square brackets beside the fact it supports, e.g.
  [UPD-00002-08167]. Brackets contain an id and nothing else.

HOW TO WRITE IT:
- Open with one sentence answering the question.
- Then two to four sentences on what the notes describe. Quote the technician's
  own words for the specific finding rather than flattening it into a generic
  phrase like "carried out diagnostics".
- Expand workshop shorthand the first time it appears, e.g. "R&R (remove and
  refit)".
- No headings, no preamble, do not restate the question. Six sentences at most.

AUTHORITY:
- You may report and advise. Never authorise work, order parts, approve a
  chargeable repair or close a repair order - only a person does that.

Write in plain British English."""


def _narration_system(results: list[dict]) -> str:
    """Pick the narration prompt for this payload.

    Shared by ask() and the streaming UI for the same reason plan_for is: two
    copies of this choice would drift, and an answer whose tone depended on
    whether the UI happened to stream would be a miserable bug to track down.
    """
    tools = {r.get("tool") for r in results}
    return SYSTEM_SEARCH if tools and tools <= _NARRATED else SYSTEM


KEYWORDS = [
    (r"\\bhandover|hand over|shift (brief|summary|change)\\b", "generate_handover", {}),''',
     "agent.py  SYSTEM_SEARCH and _narration_system",
     skip_if="SYSTEM_SEARCH =")

# _NARRATED is defined further down the module, beside _summarise. _narration_system
# only reads it at call time, so the order is fine - but the name has to exist
# before anything calls it, and a stale pass order would be silent. Assert it.
edit("app/agent/agent.py",
     '''    payload = _render(ans.results)
    if len(payload) > 22000:
        payload = payload[:22000] + "\\n...[truncated]"
    ans.text = chat_fn([{"role": "system", "content": SYSTEM},
                        {"role": "user",
                         "content": f"Question: {question}\\n\\nRECORDS:\\n{payload}"}],
                       temperature=0.0, max_tokens=400)''',
     '''    payload = _render(ans.results)
    if len(payload) > 22000:
        payload = payload[:22000] + "\\n...[truncated]"
    msgs = [{"role": "system", "content": _narration_system(ans.results)},
            {"role": "user",
             "content": f"Question: {question}\\n\\nRECORDS:\\n{payload}"}]
    # Ask for the finish reason when the chat function can report one. The
    # verification harness passes a spy with its own signature, so this is
    # checked rather than assumed.
    meta: dict = {}
    try:
        import inspect as _inspect
        wants_meta = "meta" in _inspect.signature(chat_fn).parameters
    except (TypeError, ValueError):
        wants_meta = False
    if wants_meta:
        ans.text = chat_fn(msgs, temperature=0.0, max_tokens=400, meta=meta)
    else:
        ans.text = chat_fn(msgs, temperature=0.0, max_tokens=400)
    if meta.get("finish_reason") == "length":
        ans.compose_notes = list(ans.compose_notes) + [
            "the model ran out of room at 400 tokens - the answer is cut short"]''',
     "agent.py  ask() uses the fitted prompt and notices truncation",
     skip_if="wants_meta")


# ==================================================== 3. same in the streaming UI
edit("app/ui/gradio_app.py",
     '''    from app.agent.agent import (plan_for, _summarise, _collect_citations,
                                 check_grounding, check_negations, SYSTEM,
                                 _render, _figures, Answer)''',
     '''    from app.agent.agent import (plan_for, _summarise, _collect_citations,
                                 check_grounding, check_negations,
                                 _narration_system, _render, _figures, Answer)''',
     "gradio_app.py  import the prompt selector",
     skip_if="_narration_system, _render")

edit("app/ui/gradio_app.py",
     '''        payload = _render(a.results)[:22000]
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
        a.text = acc''',
     '''        payload = _render(a.results)[:22000]
        msgs = [{"role": "system", "content": _narration_system(a.results)},
                {"role": "user", "content": f"Question: {q}\\n\\nRECORDS:\\n{payload}"}]
        history[-1]["content"] = "_Writing..._"
        yield history, False
        acc, meta = "", {}
        try:
            for piece in chat_stream(msgs, temperature=0.0, max_tokens=400,
                                     meta=meta):
                acc += piece
                history[-1]["content"] = acc
                yield history, False
        except Exception:
            if not acc:                      # nothing shown yet - fall back cleanly
                acc = chat(msgs, temperature=0.0, max_tokens=400, meta=meta)
        a.text = acc
        if meta.get("finish_reason") == "length":
            a.compose_notes = list(a.compose_notes) + [
                "the model ran out of room at 400 tokens - the answer is cut short"]''',
     "gradio_app.py  fitted prompt, and surface a cut-off answer",
     skip_if="ran out of room at 400 tokens")

# compose_notes now carries a truncation warning on a path that is working as
# designed, so the footer must stop calling every note a fallback.
edit("app/ui/gradio_app.py",
     '''    if getattr(a, "compose_notes", None):
        foot += ("\\n\\n_Fell back to the model: "
                 + "; ".join(a.compose_notes[:2]) + "_")
    return foot''',
     '''    notes = list(getattr(a, "compose_notes", None) or [])
    if notes:
        # A truncation note is not a fallback - it is a warning about an answer
        # that reached the reader incomplete, and it belongs at the front.
        cut = [n for n in notes if "cut short" in n]
        rest = [n for n in notes if "cut short" not in n]
        if cut:
            foot += "\\n\\n**" + cut[0] + "**"
        if rest:
            foot += ("\\n\\n_Fell back to the model: "
                     + "; ".join(rest[:2]) + "_")
    return foot''',
     "gradio_app.py  a cut-off answer is not a fallback",
     skip_if='cut = [n for n in notes if "cut short" in n]')


# ==================================================== 4. report tokens and rate
edit("scripts/timings.py",
     '''def _instrument():
    """Wrap the three model calls where they are actually looked up.

    index.py imported the embedder and reranker by name, so patching
    app.nim.client would not reach them - the bound names in app.retrieval.index
    are the ones that get called.
    """
    from app.retrieval import index as I
    from app.nim import client as C
    I.nim_embed_query = _timed("embed", I.nim_embed_query)
    I.nim_rerank = _timed("rerank", I.nim_rerank)
    return _timed("model", C.chat)''',
     '''USAGE: dict = {}


def _instrument():
    """Wrap the three model calls where they are actually looked up.

    index.py imported the embedder and reranker by name, so patching
    app.nim.client would not reach them - the bound names in app.retrieval.index
    are the ones that get called.

    The chat wrapper also collects the token counts, so 2.5 seconds of generation
    can be read as a long answer or a slow one. Those have different fixes.
    """
    from app.retrieval import index as I
    from app.nim import client as C
    I.nim_embed_query = _timed("embed", I.nim_embed_query)
    I.nim_rerank = _timed("rerank", I.nim_rerank)
    timed_chat = _timed("model", C.chat)

    def chat_with_usage(*a, **k):
        m: dict = {}
        k["meta"] = m
        try:
            return timed_chat(*a, **k)
        finally:
            USAGE.clear()
            USAGE.update({x: y for x, y in m.items() if y is not None})
    return chat_with_usage''',
     "timings.py  collect token usage",
     skip_if="def chat_with_usage")

edit("scripts/timings.py",
     '''            other = times[-1] - sum(last_stages.values())
            print(f"{'':7s} {'':>8s} {'':>8s}  of which: {split}"
                  f", the rest {other:.0f}ms (SQL, fold, rendering)")''',
     '''            other = times[-1] - sum(last_stages.values())
            print(f"{'':7s} {'':>8s} {'':>8s}  of which: {split}"
                  f", the rest {other:.0f}ms (SQL, fold, rendering)")
            if last_usage:
                out = last_usage.get("completion_tokens")
                gen = last_stages.get("model")
                rate = (f", {out / (gen / 1000):.0f} tok/s"
                        if out and gen else "")
                print(f"{'':7s} {'':>8s} {'':>8s}  prompt "
                      f"{last_usage.get('prompt_tokens')} tokens -> "
                      f"{out} generated{rate}"
                      + ("   ** TRUNCATED at max_tokens **"
                         if last_usage.get("finish_reason") == "length" else ""))''',
     "timings.py  print tokens, rate and truncation",
     skip_if="tok/s")

edit("scripts/timings.py",
     '''        times, a, last_stages = [], None, {}''',
     '''        times, a, last_stages, last_usage = [], None, {}, {}''',
     "timings.py  track usage per question",
     skip_if="last_usage = [], None, {}, {}")

edit("scripts/timings.py",
     '''            times.append((time.perf_counter() - t) * 1000)
            last_stages = {k: sum(v) for k, v in STAGES.items()}''',
     '''            times.append((time.perf_counter() - t) * 1000)
            last_stages = {k: sum(v) for k, v in STAGES.items()}
            last_usage = dict(USAGE)''',
     "timings.py  capture the last run's usage",
     skip_if="last_usage = dict(USAGE)")


# ==================================================== verify
print("Quality pass 14:")
for c in CHANGES:
    print(c)
for f in ("app/nim/client.py", "app/agent/agent.py", "app/ui/gradio_app.py",
          "scripts/timings.py"):
    ast.parse((ROOT / f).read_text())
print("\nclient.py, agent.py, gradio_app.py and timings.py parse cleanly.")

bad = 0
src = (ROOT / "app/agent/agent.py").read_text()

# how much prompt did this actually save?
def block(name):
    i = src.index(f'{name} = """'); j = src.index('"""', i + len(name) + 7)
    return src[i + len(name) + 7:j]
full, search = block("SYSTEM"), block("SYSTEM_SEARCH")
print(f"\nnarration prompt on the search path: ~{len(full)//4} tokens -> "
      f"~{len(search)//4} tokens ({100 - 100*len(search)//len(full)}% smaller)")
for name, ok in [
        ("grounding kept", "Never add a fact" in search),
        ("no-absence kept", "NEVER CLAIM AN ABSENCE" in search),
        ("citations kept", "square brackets" in search),
        ("authority kept", "Never authorise work" in search),
        ("digit-formatting machinery dropped", "DIGITS - read this twice" not in search),
        ("worked example dropped", "RO-26-0AAAA" not in search),
        ("an explicit length ceiling", "Six sentences at most" in search)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# _narration_system must pick correctly, and must not reach for a missing name
ns: dict = {"SYSTEM": "FULL", "SYSTEM_SEARCH": "SEARCH", "_NARRATED": {"search_updates"}}
exec(src[src.index("def _narration_system"):src.index("\nKEYWORDS = [")], ns)
f = ns["_narration_system"]
for name, results, want in [
        ("search only -> fitted prompt", [{"tool": "search_updates"}], "SEARCH"),
        ("a structured tool -> full prompt", [{"tool": "list_ros"}], "FULL"),
        ("mixed -> full prompt",
         [{"tool": "search_updates"}, {"tool": "list_ros"}], "FULL"),
        ("nothing -> full prompt", [], "FULL")]:
    got = f(results)
    ok = got == want
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name} ({got})")

# the truncation note must survive to the footer, and not be called a fallback
g = (ROOT / "app/ui/gradio_app.py").read_text()
for name, ok in [("streaming path passes meta", "meta=meta)" in g),
                 ("truncation noted in the UI", "ran out of room at 400 tokens" in g),
                 ("footer separates it from a fallback", '"cut short" in n' in g)]:
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}")

# a spy without a meta parameter must still work - that is the harness
import inspect
askw = src[src.index("    meta: dict = {}"):src.index("    if meta.get(")]
ns2: dict = {"chat_fn": lambda m, temperature=0.0, max_tokens=400: "x",
             "msgs": [], "ans": type("A", (), {"text": ""})()}
exec(askw.replace("    ", "", 1).replace("\n    ", "\n"), ns2)
print(f"  ok      a chat_fn without `meta` is called the old way "
      f"(wants_meta={ns2['wants_meta']})")
bad += (ns2["wants_meta"] is not False)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll pass-14 checks behaved as expected.")
print("\nNext:  .venv/bin/python scripts/verify_answers.py")
print("Then:  .venv/bin/python scripts/timings.py --repeat 3")
print("Then:  restart Gradio, and ask the Passat question - watch it stream")
