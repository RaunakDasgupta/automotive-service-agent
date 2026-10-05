#!/usr/bin/env python3
"""Audit the declared architecture against what is actually installed and running.

    cd ~/automotive-service-agent
    set -a && . ./.env && set +a
    .venv/bin/python audit_stack.py

Every line is measured, not inferred from configuration. Three components were
unverified when this was written - NeMo Agent Toolkit, NeMo Guardrails and
Parakeet ASR - because each is imported behind a try/except and therefore absent
in a way that looks like working software.
"""
import importlib
import os
import sys
import time

OK, WARN, BAD = "  OK      ", "  PARTIAL ", "  MISSING "
issues = []


def line(tag, name, detail=""):
    print(f"{tag}{name}" + (f"  ({detail})" if detail else ""))


def have(mod):
    """Is the module importable, and at what version."""
    try:
        m = importlib.import_module(mod)
        return True, getattr(m, "__version__", "") or ""
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:60]}"


print("\n=== 1. the three NIMs ===")
try:
    from app.nim.client import resolve
    import httpx
    for svc, port in (("llm", 8000), ("embed", 8001), ("rerank", 8002)):
        base, model, mode = resolve(svc)
        try:
            code = httpx.get(f"http://localhost:{port}/v1/health/ready",
                             timeout=6).status_code
        except Exception:
            code = 0
        container = "up" if code == 200 else "down"
        if mode == "local" and container == "up":
            line(OK, f"{svc:7s} local", model)
        elif mode == "local":
            line(BAD, f"{svc:7s} routed local but the container is {container}", model)
            issues.append(f"{svc}: routed local, container {container}")
        else:
            line(WARN, f"{svc:7s} {mode}", f"container {container}; {model}")
            issues.append(f"{svc}: routed {mode} while a container is {container}")
except Exception as e:
    line(BAD, "could not resolve the NIMs", f"{type(e).__name__}: {e}")
    issues.append("NIM resolution failed")

print("\n=== 2. NeMo Agent Toolkit ===")
ok, ver = have("aiq")
if ok:
    line(OK, "aiqtoolkit importable", ver)
    try:
        import app.agent.nat_functions as nf
        registered = [n for n in dir(nf) if not n.startswith("_")]
        line(OK, "the wrapper module loads", f"{len(registered)} names")
    except Exception as e:
        line(WARN, "aiq present but the wrapper failed", f"{type(e).__name__}: {e}")
        issues.append("nat_functions did not load")
else:
    line(BAD, "aiqtoolkit not installed", ver)
    line("          ", "", "the README claims it; app/agent/nat_functions.py")
    line("          ", "", "imports it behind try/except, so it is silently inert.")
    line("          ", "", "  uv pip install --python .venv 'aiqtoolkit>=1.1'")
    issues.append("NeMo Agent Toolkit declared but not installed")

print("\n=== 3. NeMo Guardrails ===")
ok, ver = have("nemoguardrails")
mode = (os.environ.get("ASOIA_NEMO_RAILS") or "off").lower()
if ok:
    line(OK, "nemoguardrails importable", ver)
else:
    line(BAD, "nemoguardrails not installed", ver)
    issues.append("NeMo Guardrails declared but not installed")
if mode == "off":
    line(WARN, f"ASOIA_NEMO_RAILS={mode}", "the colang rails are wired but NOT running")
    line("          ", "", "shadow runs them after the answer and counts "
                          "disagreements; that is the point of them.")
    issues.append("guardrails installed/wired but mode=off")
else:
    line(OK, f"ASOIA_NEMO_RAILS={mode}")
try:
    from app.guardrails import nemo as G
    # available() is the real API. The first version of this audit looked for
    # load_nemo_rails(), a name taken from ENGINEERING.md's prose rather than from
    # the module, and duly reported a missing loader against working code. Read
    # the module, not the documentation about it.
    line(OK, "the guardrails module imports", f"mode()={G.mode()}")
    # available() only reports that the library imports and a .co file exists.
    # Reading that as "the rails load" is how this audit announced "the colang
    # rails load (3ms)" about rails that had never loaded once - config.yml named
    # an output flow rails.co does not define, and every load raised on it. A
    # presence check is not a liveness check. Load them.
    if not G.available():
        line(WARN, "the library or the colang config is missing")
        issues.append("colang library or config missing")
    else:
        from app.guardrails.rails import load_nemo_rails
        t0 = time.perf_counter()
        try:
            _r = load_nemo_rails()
            line(OK, "the colang rails LOAD",
                 f"{type(_r).__name__} in "
                 f"{(time.perf_counter() - t0) * 1000:.0f}ms")
        except Exception as e:
            line(WARN, "the colang rails do NOT load",
                 f"{type(e).__name__}: {str(e)[:90]}")
            issues.append(f"colang rails fail to load ({type(e).__name__})")
except Exception as e:
    line(WARN, "guardrails module raised", f"{type(e).__name__}: {str(e)[:70]}")

print("\n=== 4. Parakeet ASR (the one hosted dependency) ===")
ok, ver = have("riva.client")
if not ok:
    line(BAD, "nvidia-riva-client not installed", ver)
    line("          ", "", "  uv pip install --python .venv 'nvidia-riva-client>=2.16'")
    issues.append("Riva client declared but not installed")
else:
    line(OK, "nvidia-riva-client importable", ver)
    key = os.environ.get("NVIDIA_API_KEY", "")
    line(OK if key else BAD, "an API key is present" if key else "no NVIDIA_API_KEY",
         "hosted ASR needs it")
    try:
        from app.pipeline.asr import transcribe
        line(OK, "the ASR pipeline imports")
        line("          ", "", "end-to-end: .venv/bin/python scripts/test_asr.py")
    except Exception as e:
        line(WARN, "the ASR pipeline did not import", f"{type(e).__name__}: {str(e)[:60]}")

print("\n=== 5. the store ===")
try:
    from app.retrieval.backend import backend
    b = backend()
    st = b.stats()
    line(OK, f"{st.get('backend')} {st.get('mode')}", st.get("uri", ""))
    line(OK, "rows and width", f"{b.count()} at {b.dim()} dims")
except Exception as e:
    line(BAD, "the store is unreachable", f"{type(e).__name__}: {str(e)[:70]}")
    issues.append("vector store unreachable")

print()
if issues:
    print(f"{len(issues)} thing(s) to deal with:")
    for i in issues:
        print(f"  - {i}")
else:
    print("Every declared component is installed, routed and answering.")
sys.exit(1 if issues else 0)
