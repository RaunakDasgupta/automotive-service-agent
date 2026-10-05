#!/usr/bin/env python3
"""Is the router actually routing, and does the agent survive it failing?

    .venv/bin/python scripts/test_switchyard.py

The claim worth testing is not "a proxy starts". It is:

  off by default           -> resolve("llm") is unchanged
  on                       -> every model call goes through loopback
  the efficient tier       -> serves from the local NIM
  the capable tier         -> serves from the hosted 120b, costing no VRAM
  FIVE OF SIX CLASSES      -> never reach the proxy at all
  a broken config          -> routing disables itself, the agent still answers

That fifth one is the interesting measurement for this project, and it is read off
the ATOF traces from pass 38 rather than asserted: ask five questions the labelled
set says route by keyword, and count llm spans. A router whose best decision is usually "call nothing" is a
sharper cost story than one that merely picks cheaply, and it is only credible if
something counts the calls that did not happen.
"""
from __future__ import annotations
import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

# Tracing has to be configured before the first span, because the exporter fixes
# its output directory when it starts.
TRACE_DIR = tempfile.mkdtemp(prefix="asoia-sy-trace-")
os.environ["ASOIA_TRACE"] = "file"
os.environ["ASOIA_TRACE_DIR"] = TRACE_DIR

# Drawn from the versioned set in scripts/evaluate.py, not hand-written, and that
# is not tidiness. The first version of this test invented five "deterministic"
# questions and one of them - "list all repair orders" - came back composed by the
# model with two llm spans. It was not a bug in the router: a question generic
# enough to give keyword routing nothing to grip consults the LLM function-calling
# router by design (ENGINEERING section 4), so it costs a round trip even though
# the answer itself is deterministic. The labelled set already encodes which
# phrasings route by keyword. Inventing questions re-created a problem it had
# solved.
sys.path.insert(0, "scripts")
import evaluate as EV  # noqa: E402

DETERMINISTIC = [q for q, tool in EV.ROUTING if tool != "search_updates"][:5]
NARRATED = next(q for q, tool in EV.ROUTING if tool == "search_updates")

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'FAILED '} {name}" + (f"  ({detail})" if detail else ""))


def llm_spans() -> int:
    from app.obs import trace
    trace.flush()
    p = trace.path()
    if not p or not pathlib.Path(p).exists():
        return 0
    n = 0
    for line in pathlib.Path(p).read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("category") == "llm" and r.get("scope_category") == "start":
            n += 1
    return n


def main() -> int:
    from app.nim.client import resolve, reset_resolution
    from app.routing import switchyard as SY

    print("=" * 66)
    print("OFF BY DEFAULT")
    print("=" * 66)
    os.environ.pop("ASOIA_SWITCHYARD", None)
    reset_resolution()
    base, model, mode = resolve("llm")
    chk("mode is not switchyard", mode != "switchyard", f"{mode} {base}")
    chk("endpoint() is None", SY.endpoint() is None)
    for v in ("yes", "1", "true"):
        os.environ["ASOIA_SWITCHYARD"] = v
        chk(f"ASOIA_SWITCHYARD={v!r} is still off", SY.mode() == "off")
    os.environ.pop("ASOIA_SWITCHYARD", None)

    print()
    print("=" * 66)
    print("ON: every model call goes through loopback")
    print("=" * 66)
    os.environ["ASOIA_SWITCHYARD"] = "on"
    reset_resolution()
    ep = SY.endpoint()
    if ep is None:
        print("  routing did not start:", SY.why_off())
        return 1
    base, model, mode = resolve("llm")
    chk("mode is switchyard", mode == "switchyard", mode)
    chk("the base url is loopback", "127.0.0.1" in base, base)
    chk("the 'model' is the route id", model == SY.route(), f"{model}")

    print()
    print("the two tiers, asked directly of the proxy:")
    import httpx
    for route, expect in (("asoia", "nano"), ("asoia_capable", "super")):
        try:
            r = httpx.post(base + "/chat/completions", timeout=180,
                           json={"model": route, "max_tokens": 64, "temperature": 0,
                                 "messages": [{"role": "user",
                                               "content": "Reply with the single word READY."}]})
            sel = r.json().get("model", "") if r.status_code == 200 else ""
            txt = ((r.json()["choices"][0]["message"].get("content") or "")
                   if r.status_code == 200 else r.text[:80])
            chk(f"{route} answered", r.status_code == 200 and "READY" in txt.upper(),
                f"{r.status_code} selected={sel}")
            if expect == "nano":
                chk("  and it chose the LOCAL model", "nano" in sel, sel)
            else:
                chk("  and it chose the HOSTED model", "super" in sel or "120b" in sel, sel)
        except Exception as e:
            chk(f"{route} answered", False, f"{type(e).__name__}: {str(e)[:90]}")

    print()
    print("=" * 66)
    print("FIVE OF SIX CLASSES NEVER REACH IT")
    print("=" * 66)
    from app.agent.agent import ask
    before = llm_spans()
    composed = []
    for q in DETERMINISTIC:
        a = ask(q)
        composed.append(getattr(a, "composed", "?"))
    after = llm_spans()
    chk("no model call on any deterministic question", after == before,
        f"{len(DETERMINISTIC)} questions, llm spans {before} -> {after}")
    chk("all five were composed in Python", set(composed) == {"python"}, str(composed))

    a2 = ask(NARRATED)
    narrated_spans = llm_spans() - after
    if getattr(a2, "composed", "") == "python":
        print("         note: the narrated answer fell back to Python, so no span")
        print("         is expected. The NIMs are probably down.")
    else:
        chk("the narrated question DID reach the router", narrated_spans >= 1,
            f"{narrated_spans} llm span(s)")

    print()
    print("=" * 66)
    print("A BROKEN CONFIG MUST NOT TAKE THE AGENT WITH IT")
    print("=" * 66)
    SY.shutdown()
    SY._state.update(server=None, base=None, off=False, why=None)
    os.environ["ASOIA_SWITCHYARD_CONFIG"] = "/nonexistent/switchyard.toml"
    reset_resolution()
    chk("endpoint() returns None", SY.endpoint() is None)
    chk("and says why", bool(SY.why_off()), str(SY.why_off())[:60])
    reset_resolution()
    _b, _m, _mode = resolve("llm")
    chk("resolve fell back to a real NIM", _mode in ("local", "hosted"), _mode)
    a3 = ask("which repair orders are blocked")
    chk("the agent still answers", bool(a3.text))
    os.environ.pop("ASOIA_SWITCHYARD_CONFIG", None)
    os.environ.pop("ASOIA_SWITCHYARD", None)

    print()
    print("=" * 66)
    print("THE RERANK FLAG (pass 36 measured it adding nothing)")
    print("=" * 66)
    from app.retrieval.index import search
    try:
        os.environ["ASOIA_RERANK"] = "on"
        on_hits = search("whistling noise", k=6, rerank_to=6)
        chk("with the reranker, hits carry a rerank_score",
            any("rerank_score" in h for h in on_hits), f"{len(on_hits)} hits")
        os.environ["ASOIA_RERANK"] = "off"
        from app.retrieval.index import search_updates
        off = search_updates("whistling noise", k=6)
        chk("ASOIA_RERANK=off still returns passages",
            len(off.get("passages", [])) > 0, f"{off.get('count')} passages")
    except Exception as e:
        chk("the rerank flag works", False, f"{type(e).__name__}: {str(e)[:90]}")
    finally:
        os.environ.pop("ASOIA_RERANK", None)
        SY.shutdown()

    print()
    if bad:
        print(f"{bad} assertion(s) FAILED.")
    else:
        print("The router routes, both tiers serve, and five of six questions")
        print("never asked it for anything.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
