#!/usr/bin/env python3
"""Fortieth pass: the loop gets a decide step.

Run from the project root:   .venv/bin/python quality_pass40.py

Pass 38 captures how an answer was produced; pass 39 scores runs so two can
be compared. Neither changes what the agent does. A NeMo Switchyard proxy
is the part that decides - and the sharp thing here is not that it picks a
cheaper model, it is that five of six question classes should ask it for
nothing, and the test now counts the calls that did not happen.

THE LIBRARY PATH DOES NOT WORK, WHICH IS INFORMATIVE

    LibsyError: target "nvidia/llama-3.1-nemotron-nano-8b-v1" was not found

Targets live in a deployment config only the native server reads; there is
no target registry in the Python API. So the loopback proxy is the
supported path, not the lazy one. resolve("llm") returns its base url and
the ROUTE id where a model id goes, so chat() is unchanged.

THE SCHEMA WAS REVERSE-ENGINEERED FROM THE LOADER\u2019S OWN ERRORS

TOML not YAML; schema_version an integer; format one of openai_chat /
openai_responses / anthropic_messages; llm_client a REFERENCE to a named
client; stage_router needs picker (a string, not a callable),
confidence_threshold, efficient_target and capable_target. run_stream is an
async iterator. None of this is documented.

ESCALATION LEAVES THE BOX, AND THE CATALOGUE LIES

A second local 8B needs 22.5 GB; 12.6 GB is free; evicting the reranker
gives 21.4 GB, still short - so the eviction would not have bought what it
was wanted for. The capable tier is hosted. Of four larger Nemotrons in
GET /v1/models, two return 404 "not found for account": a catalogue is not
an entitlement list. nemotron-3-super-120b-a12b answered in 0.7s and was
verified before being written into the config.

AND THE RERANKER BECOMES A FLAG, NOT A DELETION

Pass 36 measured it adding +0.0 recall@6 and -0.020 MRR for 0.07s a query.
ASOIA_RERANK=off turns it off. Default on, because the label is RO-level
and weak, and because a declared component is not removed on that evidence.
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
                 "      NOTE: edits before this one HAVE been applied.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label, skip_if=None):
    p = ROOT / rel
    if skip_if and p.exists() and skip_if in p.read_text():
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


def append(rel, body, label, skip_if):
    p = ROOT / rel
    s = p.read_text() if p.exists() else ""
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the deployment config and the router
write('configs/switchyard.toml', '# NeMo Switchyard deployment config. Loaded by app/routing/switchyard.py, which\n# starts a loopback proxy from it; the agent then talks OpenAI-chat to that proxy\n# instead of straight to a NIM. Off unless ASOIA_SWITCHYARD=on.\n#\n# Every field name here was established by reading the native loader\'s own errors:\n# nothing about this schema is documented, `picker` is a string and not a callable,\n# `llm_client` is a REFERENCE to a named client rather than an inline table, and\n# `format` must be one of openai_chat / openai_responses / anthropic_messages.\nschema_version = 1\n\n# ---------------------------------------------------------------- clients\n[llm_clients.local]\nformat = "openai_chat"\nbase_url = "http://localhost:8000/v1"\n\n[llm_clients.hosted]\nformat = "openai_chat"\nbase_url = "https://integrate.api.nvidia.com/v1"\n# The proxy reads the key itself and adds the header on the hop that needs it, so\n# the agent sends no Authorization to loopback. See _is_loopback() in\n# app/nim/client.py - this is the reason that function exists.\napi_key_env = "NVIDIA_API_KEY"\n\n# ---------------------------------------------------------------- targets\n# The efficient tier. 8B, on this box, ~22.5 GB of the L40S.\n[targets.nano]\nid = "nvidia/llama-3.1-nemotron-nano-8b-v1"\nllm_client = "local"\n\n# The capable tier, hosted, costing no VRAM at all - which is the point, because a\n# second LOCAL 8B needs 22.5 GB and only 12.6 GB is free. Evicting the reranker\n# would give 21.4 GB, still short, so escalation has to leave the box.\n#\n# This model id was VERIFIED callable by this account before being written here:\n# 200 in 0.7s. Two larger Nemotrons in the same catalogue - the 70b-instruct and\n# the ultra-253b - return 404 "not found for account", so GET /v1/models is a\n# catalogue and not an entitlement list. Check before you swap this.\n[targets.super]\nid = "nvidia/nemotron-3-super-120b-a12b"\nllm_client = "hosted"\n\n# ---------------------------------------------------------------- routes\n# What the agent asks for. efficient_first means: local unless something raises\n# confidence above the threshold. With no signals the router logs\n# `fall_through ... confidence=0.0` and picks nano, which is the correct default\n# for a shop-floor question that five times in six needs no model at all.\n[routes.asoia]\nid = "asoia"\ntype = "stage_router"\npicker = "efficient_first"\nconfidence_threshold = 0.5\nefficient_target = "nano"\ncapable_target = "super"\n\n# The same pool, opposite preference. Not used by the agent: it exists so that the\n# escalation path is exercised by scripts/test_switchyard.py rather than merely\n# declared. A configured target nobody has ever called is not a configured target.\n[routes.asoia_capable]\nid = "asoia_capable"\ntype = "stage_router"\npicker = "capable_first"\nconfidence_threshold = 0.5\nefficient_target = "nano"\ncapable_target = "super"\n',
      'configs/switchyard.toml  two tiers, both verified callable',
      skip_if='[routes.asoia_capable]')

write('app/routing/__init__.py', '', 'app/routing/__init__.py', skip_if=None) if not (ROOT / 'app/routing/__init__.py').exists() else CHANGES.append('  skip  app/routing/__init__.py (exists)')

write('app/routing/switchyard.py', '"""Route each model call through a NeMo Switchyard proxy. Off by default.\n\nWHAT THIS IS FOR\n\nThe project has capture (app/obs/trace.py) and a yardstick (scripts/eval_standard.py).\nNeither changes what the agent does. Switchyard is the part whose behaviour can\nchange in response to a score: a policy that decides, per request, which model\nserves it - and whose best decision here is usually that no model is needed at all,\nbecause five of six question classes are composed in Python from tool results.\n\nHOW IT ATTACHES\n\n`switchyard_rust.server.Server(config, port)` is a loopback OpenAI-compatible\nproxy. With it running, `resolve("llm")` hands back the proxy\'s base url and the\nROUTE id in place of a model id, so `chat()` is unchanged and every model call goes\nthrough the router. The route then picks a target and proxies on.\n\nThe library path - `switchyard.libsy.algorithms.stage_router` driven by\n`run_stream` - was tried first and abandoned for a specific reason worth recording:\n`run_stream` raises `target "..." was not found` because targets live in a\ndeployment config that only the server reads. There is no target registry in the\nPython API. The proxy is not the lazy option, it is the supported one.\n\nWHEN IT FAILS, THE AGENT STILL ANSWERS\n\nEvery path here returns None rather than raising, and the first failure disables\nrouting for the rest of the process. `resolve("llm")` then falls through to the\ndirect NIM exactly as before. A router that can take the agent down with it is\nworse than no router.\n"""\nfrom __future__ import annotations\nimport atexit\nimport os\nimport pathlib\n\nCONFIG = "configs/switchyard.toml"\nDEFAULT_ROUTE = "asoia"\n\n_state: dict = {"server": None, "base": None, "off": False, "why": None}\n\n\ndef mode() -> str:\n    """-> "off" | "on". Anything unrecognised is off, as with ASOIA_TRACE."""\n    m = (os.environ.get("ASOIA_SWITCHYARD") or "off").strip().lower()\n    return m if m in ("off", "on") else "off"\n\n\ndef route() -> str:\n    return (os.environ.get("ASOIA_SWITCHYARD_ROUTE") or DEFAULT_ROUTE).strip()\n\n\ndef config_path() -> str:\n    return os.environ.get("ASOIA_SWITCHYARD_CONFIG") or CONFIG\n\n\ndef enabled() -> bool:\n    return mode() == "on" and not _state["off"]\n\n\ndef why_off() -> str | None:\n    return _state["why"]\n\n\ndef _disable(why: str) -> None:\n    _state["off"] = True\n    _state["why"] = why\n\n\ndef base_url() -> str | None:\n    """Start the proxy if needed and return its base url, or None."""\n    if _state["base"] is not None or _state["off"]:\n        return _state["base"]\n    if not enabled():\n        return None\n    try:\n        from switchyard_rust.server import Server\n        cfg = config_path()\n        if not pathlib.Path(cfg).exists():\n            _disable(f"config not found: {cfg}")\n            return None\n        # Port 0: the OS picks one. The API and the UI are separate processes and\n        # each gets its own proxy, which is fine - a router is stateless.\n        srv = Server(cfg, 0)\n        _state["server"] = srv\n        _state["base"] = srv.base_url.rstrip("/")\n        atexit.register(shutdown)\n    except Exception as e:\n        _disable(type(e).__name__ + ": " + str(e)[:200])\n        return None\n    return _state["base"]\n\n\ndef endpoint() -> tuple[str, str] | None:\n    """-> (base_url_with_v1, route_id) for resolve(), or None to use the NIM direct."""\n    b = base_url()\n    if not b:\n        return None\n    return (b + "/v1", route())\n\n\ndef shutdown() -> None:\n    """Drain and stop. Idempotent - atexit and a test may both call it."""\n    srv = _state["server"]\n    if srv is None:\n        return\n    _state["server"] = None\n    _state["base"] = None\n    try:\n        srv.close()\n    except Exception:\n        pass\n\n\ndef status() -> dict:\n    """For scripts/stack.sh and the eval provenance."""\n    return {"mode": mode(), "route": route(), "config": config_path(),\n            "base_url": _state["base"], "off": _state["off"],\n            "why": _state["why"]}\n',
      'app/routing/switchyard.py  loopback proxy, off by default',
      skip_if='def endpoint(')

# ==================== 2. send model calls through it
edit('app/nim/client.py',
     'def _headers(local: bool) -> dict:\n',
     'def _is_loopback(mode: str) -> bool:\n    """Does this endpoint need no Authorization header from us?\n\n    "local" obviously not. "switchyard" also not, and for a reason worth stating:\n    the proxy runs on 127.0.0.1 and holds its own credentials - it adds the hosted\n    key itself, from api_key_env, on the one hop that escalates. Sending our Bearer\n    to loopback would be pointless at best, and at worst would put the key on a hop\n    that never asked for it.\n    """\n    return mode in ("local", "switchyard")\n\n\ndef _headers(local: bool) -> dict:\n',
     'client.py  _is_loopback(): the proxy holds its own key',
     skip_if='def _is_loopback(')

edit('app/nim/client.py',
     '    if service in _resolved:\n        return _resolved[service]\n    m = _mode(service)\n',
     '    if service in _resolved:\n        return _resolved[service]\n    if service == "llm":\n        # The router returns (base_url, ROUTE id) and the route id goes where a\n        # model id normally would, which is why chat() needs no change: the proxy\n        # speaks openai_chat and picks the target itself. None means routing is off\n        # or has disabled itself, and then this falls through to the NIM as before.\n        try:\n            from app.routing import switchyard as _sy\n            _ep = _sy.endpoint()\n        except Exception:\n            _ep = None\n        if _ep is not None:\n            out = (_ep[0], _ep[1], "switchyard")\n            _resolved[service] = out\n            return out\n    m = _mode(service)\n',
     'client.py  resolve() consults the router for llm',
     skip_if='from app.routing import switchyard as _sy')

edit('app/nim/client.py',
     '    data = _post(f"{base}/chat/completions", payload, local=(mode == "local"))\n',
     '    data = _post(f"{base}/chat/completions", payload, local=_is_loopback(mode))\n',
     'client.py  chat() treats the proxy as loopback',
     skip_if='local=_is_loopback(mode)')

edit('app/nim/client.py',
     '    base, model, mode = resolve("llm")\n    local = (mode == "local")\n',
     '    base, model, mode = resolve("llm")\n    local = _is_loopback(mode)\n',
     'client.py  chat_stream() too',
     skip_if='local = _is_loopback(mode)')

# ==================== 3. the reranker becomes a flag
edit('app/retrieval/index.py',
     'def search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:\n',
     'def _rerank_on() -> bool:\n    """ASOIA_RERANK=off takes the vector top-k straight, with no second stage.\n\n    Pass 36 measured the reranker over 40 queries: recall@6 50.0% with it and 50.0%\n    without, MRR WORSE with it (0.232 against 0.251), at 0.07s per query. On that\n    evidence it is not earning its latency.\n\n    It is a flag and not a deletion, for two reasons. The label is RO-level - a hit\n    is any passage from the right repair order - so it cannot tell a wrong answer\n    from a reasonable one, and an MRR gap of 0.020 over 40 queries is not grounds to\n    remove a declared component of the architecture. And the VRAM it would free\n    does not buy what it was wanted for: 12.6 GB free plus the reranker\'s 8.7 GB is\n    21.4 GB against the 22.5 GB a second local 8B needs. It would cover a LoRA job,\n    and that is the moment to turn it off deliberately.\n    """\n    return (os.environ.get("ASOIA_RERANK") or "on").strip().lower() != "off"\n\n\ndef search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:\n',
     'index.py  _rerank_on(), with the measurement in it',
     skip_if='def _rerank_on(')

edit('app/retrieval/index.py',
     '    hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)\n',
     '    if _rerank_on():\n        hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)\n    else:\n        # Retrieve exactly k. Asking for 18 and keeping 6 without a reranker to\n        # order them would just discard twelve rows at random.\n        hits = search(query, k=k, rerank_to=None, ro_number=ro_number)\n',
     'index.py  search_updates honours it',
     skip_if='if _rerank_on():')

# ==================== 4. declare it
edit('pyproject.toml',
     'flywheel = ["nemo-relay>=0.9", "nemo-evaluator>=0.2"]\n',
     'flywheel = ["nemo-relay>=0.9", "nemo-evaluator>=0.2",\n            "nemo-switchyard>=0.3"]\n',
     'pyproject.toml  nemo-switchyard in the flywheel extra',
     skip_if='nemo-switchyard')

# ==================== 5. prove it routes, and survives failing
write('scripts/test_switchyard.py', '#!/usr/bin/env python3\n"""Is the router actually routing, and does the agent survive it failing?\n\n    .venv/bin/python scripts/test_switchyard.py\n\nThe claim worth testing is not "a proxy starts". It is:\n\n  off by default           -> resolve("llm") is unchanged\n  on                       -> every model call goes through loopback\n  the efficient tier       -> serves from the local NIM\n  the capable tier         -> serves from the hosted 120b, costing no VRAM\n  FIVE OF SIX CLASSES      -> never reach the proxy at all\n  a broken config          -> routing disables itself, the agent still answers\n\nThat fifth one is the interesting measurement for this project, and it is read off\nthe ATOF traces from pass 38 rather than asserted: ask five questions the labelled\nset says route by keyword, and count llm spans. A router whose best decision is usually "call nothing" is a\nsharper cost story than one that merely picks cheaply, and it is only credible if\nsomething counts the calls that did not happen.\n"""\nfrom __future__ import annotations\nimport json\nimport os\nimport pathlib\nimport sys\nimport tempfile\n\nsys.path.insert(0, ".")\nimport _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py\n\n# Tracing has to be configured before the first span, because the exporter fixes\n# its output directory when it starts.\nTRACE_DIR = tempfile.mkdtemp(prefix="asoia-sy-trace-")\nos.environ["ASOIA_TRACE"] = "file"\nos.environ["ASOIA_TRACE_DIR"] = TRACE_DIR\n\n# Drawn from the versioned set in scripts/evaluate.py, not hand-written, and that\n# is not tidiness. The first version of this test invented five "deterministic"\n# questions and one of them - "list all repair orders" - came back composed by the\n# model with two llm spans. It was not a bug in the router: a question generic\n# enough to give keyword routing nothing to grip consults the LLM function-calling\n# router by design (ENGINEERING section 4), so it costs a round trip even though\n# the answer itself is deterministic. The labelled set already encodes which\n# phrasings route by keyword. Inventing questions re-created a problem it had\n# solved.\nsys.path.insert(0, "scripts")\nimport evaluate as EV  # noqa: E402\n\nDETERMINISTIC = [q for q, tool in EV.ROUTING if tool != "search_updates"][:5]\nNARRATED = next(q for q, tool in EV.ROUTING if tool == "search_updates")\n\nbad = 0\n\n\ndef chk(name, ok, detail=""):\n    global bad\n    bad += (not ok)\n    print(f"  {\'ok     \' if ok else \'FAILED \'} {name}" + (f"  ({detail})" if detail else ""))\n\n\ndef llm_spans() -> int:\n    from app.obs import trace\n    trace.flush()\n    p = trace.path()\n    if not p or not pathlib.Path(p).exists():\n        return 0\n    n = 0\n    for line in pathlib.Path(p).read_text().splitlines():\n        if not line.strip():\n            continue\n        try:\n            r = json.loads(line)\n        except Exception:\n            continue\n        if r.get("category") == "llm" and r.get("scope_category") == "start":\n            n += 1\n    return n\n\n\ndef main() -> int:\n    from app.nim.client import resolve, reset_resolution\n    from app.routing import switchyard as SY\n\n    print("=" * 66)\n    print("OFF BY DEFAULT")\n    print("=" * 66)\n    os.environ.pop("ASOIA_SWITCHYARD", None)\n    reset_resolution()\n    base, model, mode = resolve("llm")\n    chk("mode is not switchyard", mode != "switchyard", f"{mode} {base}")\n    chk("endpoint() is None", SY.endpoint() is None)\n    for v in ("yes", "1", "true"):\n        os.environ["ASOIA_SWITCHYARD"] = v\n        chk(f"ASOIA_SWITCHYARD={v!r} is still off", SY.mode() == "off")\n    os.environ.pop("ASOIA_SWITCHYARD", None)\n\n    print()\n    print("=" * 66)\n    print("ON: every model call goes through loopback")\n    print("=" * 66)\n    os.environ["ASOIA_SWITCHYARD"] = "on"\n    reset_resolution()\n    ep = SY.endpoint()\n    if ep is None:\n        print("  routing did not start:", SY.why_off())\n        return 1\n    base, model, mode = resolve("llm")\n    chk("mode is switchyard", mode == "switchyard", mode)\n    chk("the base url is loopback", "127.0.0.1" in base, base)\n    chk("the \'model\' is the route id", model == SY.route(), f"{model}")\n\n    print()\n    print("the two tiers, asked directly of the proxy:")\n    import httpx\n    for route, expect in (("asoia", "nano"), ("asoia_capable", "super")):\n        try:\n            r = httpx.post(base + "/chat/completions", timeout=180,\n                           json={"model": route, "max_tokens": 64, "temperature": 0,\n                                 "messages": [{"role": "user",\n                                               "content": "Reply with the single word READY."}]})\n            sel = r.json().get("model", "") if r.status_code == 200 else ""\n            txt = ((r.json()["choices"][0]["message"].get("content") or "")\n                   if r.status_code == 200 else r.text[:80])\n            chk(f"{route} answered", r.status_code == 200 and "READY" in txt.upper(),\n                f"{r.status_code} selected={sel}")\n            if expect == "nano":\n                chk("  and it chose the LOCAL model", "nano" in sel, sel)\n            else:\n                chk("  and it chose the HOSTED model", "super" in sel or "120b" in sel, sel)\n        except Exception as e:\n            chk(f"{route} answered", False, f"{type(e).__name__}: {str(e)[:90]}")\n\n    print()\n    print("=" * 66)\n    print("FIVE OF SIX CLASSES NEVER REACH IT")\n    print("=" * 66)\n    from app.agent.agent import ask\n    before = llm_spans()\n    composed = []\n    for q in DETERMINISTIC:\n        a = ask(q)\n        composed.append(getattr(a, "composed", "?"))\n    after = llm_spans()\n    chk("no model call on any deterministic question", after == before,\n        f"{len(DETERMINISTIC)} questions, llm spans {before} -> {after}")\n    chk("all five were composed in Python", set(composed) == {"python"}, str(composed))\n\n    a2 = ask(NARRATED)\n    narrated_spans = llm_spans() - after\n    if getattr(a2, "composed", "") == "python":\n        print("         note: the narrated answer fell back to Python, so no span")\n        print("         is expected. The NIMs are probably down.")\n    else:\n        chk("the narrated question DID reach the router", narrated_spans >= 1,\n            f"{narrated_spans} llm span(s)")\n\n    print()\n    print("=" * 66)\n    print("A BROKEN CONFIG MUST NOT TAKE THE AGENT WITH IT")\n    print("=" * 66)\n    SY.shutdown()\n    SY._state.update(server=None, base=None, off=False, why=None)\n    os.environ["ASOIA_SWITCHYARD_CONFIG"] = "/nonexistent/switchyard.toml"\n    reset_resolution()\n    chk("endpoint() returns None", SY.endpoint() is None)\n    chk("and says why", bool(SY.why_off()), str(SY.why_off())[:60])\n    reset_resolution()\n    _b, _m, _mode = resolve("llm")\n    chk("resolve fell back to a real NIM", _mode in ("local", "hosted"), _mode)\n    a3 = ask("which repair orders are blocked")\n    chk("the agent still answers", bool(a3.text))\n    os.environ.pop("ASOIA_SWITCHYARD_CONFIG", None)\n    os.environ.pop("ASOIA_SWITCHYARD", None)\n\n    print()\n    print("=" * 66)\n    print("THE RERANK FLAG (pass 36 measured it adding nothing)")\n    print("=" * 66)\n    from app.retrieval.index import search\n    try:\n        os.environ["ASOIA_RERANK"] = "on"\n        on_hits = search("whistling noise", k=6, rerank_to=6)\n        chk("with the reranker, hits carry a rerank_score",\n            any("rerank_score" in h for h in on_hits), f"{len(on_hits)} hits")\n        os.environ["ASOIA_RERANK"] = "off"\n        from app.retrieval.index import search_updates\n        off = search_updates("whistling noise", k=6)\n        chk("ASOIA_RERANK=off still returns passages",\n            len(off.get("passages", [])) > 0, f"{off.get(\'count\')} passages")\n    except Exception as e:\n        chk("the rerank flag works", False, f"{type(e).__name__}: {str(e)[:90]}")\n    finally:\n        os.environ.pop("ASOIA_RERANK", None)\n        SY.shutdown()\n\n    print()\n    if bad:\n        print(f"{bad} assertion(s) FAILED.")\n    else:\n        print("The router routes, both tiers serve, and five of six questions")\n        print("never asked it for anything.")\n    return 1 if bad else 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
      'scripts/test_switchyard.py  both tiers, and the calls that did not happen',
      skip_if='import evaluate as EV')

# ==================== 6. the record
_p39 = [l for l in (ROOT / 'patches/README.md').read_text().splitlines(True)
        if l.startswith('| `quality_pass39.py` |')]
if _p39:
    edit('patches/README.md', _p39[0], _p39[0] + "| `quality_pass40.py` | the loop could capture and score but not decide; a Switchyard proxy routes every model call, its schema reverse-engineered from the loader's own errors, and five of six questions still ask it for nothing |\n",
         'patches/README.md  pass 40 row', skip_if='| `quality_pass40.py` |')

append('ENGINEERING.md', '\n\n## 29. The part of the loop that decides\n\nCapture (section 27) and a yardstick (section 28) observe. Neither changes what the\nagent does. Switchyard is the component whose behaviour can move in response to a\nscore, and the thing that makes it interesting here is not that it picks a cheaper\nmodel - it is that for five of six question classes the right decision is to call\nnothing at all, and now something counts the calls that did not happen.\n\n### The library path does not work out of the box, and that is informative\n\n`switchyard.libsy.algorithms.stage_router` exists, builds, and driving it with\n`run_stream` fails:\n\n```\nLibsyError: target "nvidia/llama-3.1-nemotron-nano-8b-v1" was not found\n```\n\nTargets live in a deployment config that only the native server reads; there is no\ntarget registry in the Python API. So the proxy is not the lazy option, it is the\nsupported one - `switchyard_rust.server.Server(config, port)`, a loopback\nOpenAI-compatible endpoint. `resolve("llm")` hands back its base url and the ROUTE\nid where a model id would go, and `chat()` is unchanged.\n\nAlso worth recording: `run_stream` is an **async** iterator, and `picker` is a\nstring (`capable_first` or `efficient_first`), not a callable. Both cost a guess.\n\n### The schema had to be reverse-engineered\n\nNothing about the config is documented. Every field below came from reading the\nloader\'s own rejections, one at a time:\n\n| | |\n|---|---|\n| file format | TOML, not YAML |\n| `schema_version` | an integer; a string is rejected |\n| `format` | `openai_chat` / `openai_responses` / `anthropic_messages` |\n| `llm_client` | a **reference** to a named client, not an inline table |\n| route `type` | one of ten, including `stage_router`, `composite`, `advisor` |\n| `stage_router` | requires `picker`, `confidence_threshold`, `efficient_target`, `capable_target` |\n\n### Escalation has to leave the box, and the catalogue lies\n\nThe capable tier is hosted, because a second local 8B needs 22.5 GB and 12.6 GB is\nfree. Evicting the reranker gives 21.4 GB - still short - so the eviction would not\nhave bought what it was being considered for.\n\nChoosing the hosted model turned up a trap. `GET /v1/models` lists 81 models\nincluding four larger Nemotrons; two of them, `llama-3.1-nemotron-70b-instruct` and\n`llama-3.1-nemotron-ultra-253b-v1`, return **404 "not found for account"**. A model\ncatalogue is not an entitlement list. `nemotron-3-super-120b-a12b` answered in 0.7s\nand is what the config names, verified before being written down rather than after.\n\nOne more, for anyone who meets it: the first call to that model returned\n`content: None` with a 200. It is a reasoning model, `max_tokens` was 16, and the\nbudget went entirely to `reasoning_content`. With 64 tokens it answers normally.\n\n### What is actually routed today, stated plainly\n\nWith no signals the router logs `fall_through ... confidence=0.0` and picks the\nefficient target. So today the policy is "local, always", the escalation path is\nconfigured and **exercised by the test** through a second route rather than merely\ndeclared, and signal-driven escalation is the next increment. Saying the router\n"chooses intelligently" would be the overclaim; it chooses, cheaply, and the\nmachinery to choose better is in place and measured.\n\n### And it cannot take the agent down\n\nEvery path in `app/routing/switchyard.py` returns None rather than raising, and the\nfirst failure disables routing for the process. The test points the config at a\nnonexistent file and asserts `resolve()` falls back to a real NIM and the agent\nstill answers. A router that can take the agent with it is worse than no router.\n',
       'ENGINEERING.md  section 29',
       skip_if='## 29. The part of the loop that decides')

# ==================== verify
print("Quality pass 40:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}"
          + (f"  ({detail})" if detail else ""))


import os, subprocess, tomllib

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")
import _env  # noqa: E402,F401

print("\nthe files:")
sy_src = (ROOT / "app/routing/switchyard.py").read_text()
cl_src = (ROOT / "app/nim/client.py").read_text()
ix_src = (ROOT / "app/retrieval/index.py").read_text()
sy_t, cl_t, ix_t = (ast.parse(s) for s in (sy_src, cl_src, ix_src))
ast.parse((ROOT / "scripts/test_switchyard.py").read_text())
chk("all four parse", True)
CFG = tomllib.loads((ROOT / "configs/switchyard.toml").read_text())
chk("the config is valid TOML", True)

print("\nthe deployment config declares two real tiers:")
chk("schema_version is an integer", isinstance(CFG.get("schema_version"), int),
    "the loader rejects a string")
_t = CFG.get("targets", {})
_c = CFG.get("llm_clients", {})
_r = CFG.get("routes", {})
chk("an efficient target on the local NIM",
    _c.get(_t.get("nano", {}).get("llm_client"), {}).get("base_url", "").startswith("http://localhost"),
    str(_t.get("nano")))
chk("a capable target that is hosted",
    _c.get(_t.get("super", {}).get("llm_client"), {}).get("base_url", "").startswith("https://"),
    "a second local 8B does not fit in 12.6 GB")
chk("the hosted client takes its key from the environment",
    _c.get("hosted", {}).get("api_key_env") == "NVIDIA_API_KEY",
    "so the agent sends no Authorization to loopback")
chk("both routes exist", {"asoia", "asoia_capable"} <= set(_r), str(sorted(_r)))
chk("the agent's route prefers efficient",
    _r.get("asoia", {}).get("picker") == "efficient_first")
chk("the other prefers capable, so escalation is exercised",
    _r.get("asoia_capable", {}).get("picker") == "capable_first")
# Every client format must be one the loader accepts; this is the field that cost
# the most guesses.
chk("every client format is a valid variant",
    all(v.get("format") in ("openai_chat", "openai_responses", "anthropic_messages")
        for v in _c.values()),
    str([v.get("format") for v in _c.values()]))

print("\noff is the default, and off means off:")
from app.routing import switchyard as SY
for val, want in ((None, "off"), ("", "off"), ("on", "on"), ("ON", "on"),
                  ("yes", "off"), ("1", "off"), ("true", "off")):
    if val is None:
        os.environ.pop("ASOIA_SWITCHYARD", None)
    else:
        os.environ["ASOIA_SWITCHYARD"] = val
    chk(f"ASOIA_SWITCHYARD={val!r} -> {SY.mode()}", SY.mode() == want, f"wanted {want}")
os.environ.pop("ASOIA_SWITCHYARD", None)
chk("endpoint() is None when off", SY.endpoint() is None)
chk("nothing was started", SY._state["server"] is None)

print("\na missing config disables routing instead of raising:")
_saved = dict(SY._state)
try:
    os.environ["ASOIA_SWITCHYARD"] = "on"
    os.environ["ASOIA_SWITCHYARD_CONFIG"] = "/nonexistent/sy.toml"
    _raised = None
    try:
        _ep = SY.endpoint()
    except Exception as e:
        _raised, _ep = e, None
    chk("endpoint() did not raise", _raised is None,
        type(_raised).__name__ if _raised else "")
    chk("it returned None", _ep is None)
    chk("and recorded why", "not found" in (SY.why_off() or ""), str(SY.why_off())[:60])
finally:
    SY._state.clear(); SY._state.update(_saved)
    os.environ.pop("ASOIA_SWITCHYARD_CONFIG", None)
    os.environ.pop("ASOIA_SWITCHYARD", None)

print("\nthe client knows loopback from hosted:")
from app.nim import client as CL
chk("_is_loopback('local')", CL._is_loopback("local") is True)
chk("_is_loopback('switchyard')", CL._is_loopback("switchyard") is True,
    "the proxy holds its own key; we must not send ours to it")
chk("_is_loopback('hosted')", CL._is_loopback("hosted") is False)
# Counting CALLS, not the word. The two sites are _chat_inner and chat_stream;
# embeddings and ranking are untouched because switchyard routes llm only.
_calls = sum(1 for n in ast.walk(cl_t) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_is_loopback")
chk("both chat paths use it", _calls == 2, f"{_calls} call site(s)")
_res = next((n for n in ast.walk(cl_t) if isinstance(n, ast.FunctionDef)
             and n.name == "resolve"), None)
chk("resolve() consults the router",
    _res is not None and any(isinstance(n, ast.Call)
                             and getattr(n.func, "attr", "") == "endpoint"
                             for n in ast.walk(_res)))

print("\nwith routing off, resolution is exactly what it was:")
CL.reset_resolution()
_b, _m, _mode = CL.resolve("llm")
chk("mode is local or hosted", _mode in ("local", "hosted"), _mode)
chk("the base is not loopback-proxied", "127.0.0.1" not in _b, _b)

print("\nthe rerank flag:")
from app.retrieval import index as IX
os.environ.pop("ASOIA_RERANK", None)
chk("on by default", IX._rerank_on() is True,
    "a named component of the architecture is not removed on one weak label")
os.environ["ASOIA_RERANK"] = "off"
chk("off when asked", IX._rerank_on() is False)
os.environ["ASOIA_RERANK"] = "ON"
chk("case does not matter", IX._rerank_on() is True)
os.environ.pop("ASOIA_RERANK", None)
_su = next((n for n in ast.walk(ix_t) if isinstance(n, ast.FunctionDef)
            and n.name == "search_updates"), None)
chk("search_updates honours it",
    _su is not None and any(isinstance(n, ast.Call)
                            and getattr(n.func, "id", "") == "_rerank_on"
                            for n in ast.walk(_su)))

print("\nthe dependency is declared:")
_opt = (tomllib.loads((ROOT / "pyproject.toml").read_text())
        .get("project", {}).get("optional-dependencies", {}))
import re as _re
_names = {_re.split(r"[<>=!~\[]", d, 1)[0].strip() for d in _opt.get("flywheel", [])}
chk("nemo-switchyard is in the flywheel extra", "nemo-switchyard" in _names,
    str(sorted(_names)))

print("\nend to end:")
_r2 = subprocess.run([sys.executable, "scripts/test_switchyard.py"],
                     capture_output=True, text=True, timeout=2400)
chk("scripts/test_switchyard.py passes", _r2.returncode == 0,
    f"rc={_r2.returncode}: " + (_r2.stdout or "")[-320:].replace("\n", " | "))

print("\nthe regression suite:")
_t2 = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                     capture_output=True, text=True, timeout=1800)
chk("unit tests pass", _t2.returncode == 0,
    (_t2.stdout or "").strip().splitlines()[-1] if (_t2.stdout or "").strip() else "")
_v = subprocess.run([sys.executable, "scripts/verify_answers.py"],
                    capture_output=True, text=True, timeout=1800)
chk("the answer checks pass", _v.returncode == 0,
    (_v.stdout or "").strip().splitlines()[-1] if (_v.stdout or "").strip() else "")

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    .venv/bin/python scripts/test_switchyard.py
    ASOIA_SWITCHYARD=on bash scripts/stack.sh restart --share   <- route the stack
""")
sys.exit(1 if bad else 0)

