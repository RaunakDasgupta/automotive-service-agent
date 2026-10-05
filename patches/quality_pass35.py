#!/usr/bin/env python3
"""Thirty-fifth pass: the colang rails had never once loaded.

Run from the project root:   .venv/bin/python quality_pass35.py

WHAT WAS WRONG, IN THREE LAYERS

Pass 21 wired NeMo Guardrails in behind off/shadow/on. Enabling shadow did
nothing at all, and the reason was three separate faults stacked on top of each
other, each of which hid the next.

1. config.yml named an output flow that does not exist.

       InvalidRailsConfigurationError: The provided output rail flow
       `require grounding` does not exist

   rails.co defines three flows - refuse out of scope, refuse prompt injection,
   refuse unauthorised action - and config.yml listed four. Every single load
   raised on the fourth. It is DELETED rather than written, because grounding here
   is checked deterministically in Python: check_output/check_grounding verify
   every figure in an answer against the tool results. Asking the model to judge
   its own grounding would be weaker than what already runs, and would contradict
   the first of this project's two principles. The three refusals are real colang
   work; grounding is not its job.

2. langchain-nvidia-ai-endpoints was never declared, so it was never installed.

   `engine: nim` in the colang config instantiates ChatNVIDIA from that package.
   It was missing from the nvidia extra, so even with the flow names right the
   rails could not have run. Declared now.

3. The model had no base url, so it pointed at a model that is gone.

       parameters={}  ->  https://integrate.api.nvidia.com/v1
       HTTP 410 Gone: llama-3.1-nemotron-nano-8b-v1 reached end of life
                      on 2026-08-26

   It now points at the local NIM. The field is `base_url`, and it is worth being
   explicit about why it is not `nim_base_url`: ChatNVIDIA has no such field.
   Passing it is accepted, moved silently into model_kwargs with a UserWarning,
   and the base url stays hosted - measured:

       base_url      accepted -> base_url=http://localhost:8000/v1
       nim_base_url  accepted -> base_url=https://integrate.api.nvidia.com/v1

A DEPRECATION WARNING MUST NOT BE ABLE TO DISABLE A GUARDRAIL

nemoguardrails 0.24.1 raises a DeprecationWarning against ITSELF while validating
its jailbreak-detection config:

    nemoguardrails/library/jailbreak_detection/rail_config.py:77
      if self.nim_url and not self.nim_base_url:
    DeprecationWarning: Use 'nim_base_url' instead.

Nothing on our side triggers it and there is nothing of ours to rename. But in any
process that runs warnings as errors - a strict pytest, a CI job, `-W error` - it
becomes an exception, `_get()` catches it, and the rails turn themselves off with a
one-line notice. That is a safety control being disabled by somebody else's
housekeeping, so the load suppresses it locally.

AND THE AUDIT WAS ASKING THE WRONG QUESTION

scripts/audit_stack.py reported "the colang rails load (3ms)" about rails that had
never loaded, because it called `available()` - which only checks that the library
is importable and a .co file exists. A presence check read as a liveness check.
It loads them now, which is the only way to know.
"""
import sys, pathlib, ast, subprocess

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
                 "      NOTE: edits before this one HAVE been applied - this\n"
                 "      harness writes as it goes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label):
    """Whole file. The only shape of change that cannot half-apply."""
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_text() == body:
        CHANGES.append(f"  skip  {label} (already present)")
        return
    existed = p.exists()
    p.write_text(body)
    CHANGES.append(f"  ok    {label}" + (" (replaced)" if existed else ""))


def append(rel, body, label, skip_if):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found")
    s = p.read_text()
    if skip_if in s:
        CHANGES.append(f"  skip  {label} (already present)")
        return
    if not s.endswith("\n"):
        s += "\n"
    p.write_text(s + body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the colang config, whole
write('app/guardrails/config/config.yml',
      '''models:
  - type: main
    engine: nim
    model: nvidia/llama-3.1-nemotron-nano-8b-v1
    parameters:
      # base_url, and NOT nim_base_url. ChatNVIDIA has no nim_base_url field:
      # passing it is accepted, moved silently into model_kwargs with a
      # UserWarning, and the base url stays hosted. Measured on this box:
      #   base_url      -> http://localhost:8000/v1      (what we want)
      #   nim_base_url  -> https://integrate.api.nvidia.com/v1  (silently wrong)
      # The hosted copy of this model reached end of life on 2026-08-26 and
      # answers HTTP 410, so pointing there disables the rails in a way that
      # only shows up as a failed LLM call inside a guardrail.
      base_url: http://localhost:8000/v1

instructions:
  - type: general
    content: |
      You are a service operations assistant for a vehicle workshop.
      You report and advise on repair orders from tool results only.
      You never authorise work, order parts, approve chargeable repairs,
      or close a repair order. Only a person does those things.

# Exactly the flows rails.co defines, and no others: nemoguardrails refuses the
# whole config if one is missing, so a fourth name here - there used to be a
# `require grounding` - stopped the rails loading at all, every time.
#
# There is no grounding flow on purpose. Grounding is checked deterministically:
# check_output/check_grounding verify every figure in an answer against the tool
# results. A model judging its own grounding would be weaker than that.
rails:
  input:
    flows:
      - refuse out of scope
      - refuse prompt injection
  output:
    flows:
      - refuse unauthorised action
''',
      'config.yml  three real flows, and a local base_url')


# ==================== 2. a deprecation must not switch off a guardrail
edit('app/guardrails/rails.py',
     '''def load_nemo_rails():
    """Load the colang config through NeMo Guardrails, if installed."""
    from nemoguardrails import LLMRails, RailsConfig
    return LLMRails(RailsConfig.from_path(str(CONFIG_DIR)))''',
     '''def load_nemo_rails():
    """Load the colang config through NeMo Guardrails, if installed.

    The suppression is not cosmetic. nemoguardrails 0.24.1 raises a
    DeprecationWarning against ITSELF while validating its jailbreak-detection
    config:

        nemoguardrails/library/jailbreak_detection/rail_config.py:77
          if self.nim_url and not self.nim_base_url:
        DeprecationWarning: Use 'nim_base_url' instead.

    Nothing here sets either field and there is nothing of ours to rename. But in
    a process that runs warnings as errors - a strict pytest, a CI job, anything
    with -W error - that warning becomes an exception, the caller in
    app/guardrails/nemo.py catches it, and THE GUARDRAILS SILENTLY TURN OFF. A
    third party's housekeeping must not be able to disable a safety control, so it
    is ignored here, around this load only, and nowhere else.
    """
    import warnings
    from nemoguardrails import LLMRails, RailsConfig
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return LLMRails(RailsConfig.from_path(str(CONFIG_DIR)))''',
     'rails.py  load through a local DeprecationWarning filter',
     skip_if='warnings.catch_warnings()')


# ==================== 3. declare what engine: nim actually needs
edit('pyproject.toml',
     '''nvidia = ["nemoguardrails>=0.11", "aiqtoolkit>=1.1"]''',
     '''# langchain-nvidia-ai-endpoints is what `engine: nim` in the colang config
# instantiates (ChatNVIDIA). It was not declared, so it was not installed, so the
# rails could not have run even after the flow names were correct.
nvidia = ["nemoguardrails>=0.11", "aiqtoolkit>=1.1",
          "langchain-nvidia-ai-endpoints>=1.4"]''',
     'pyproject.toml  declare langchain-nvidia-ai-endpoints',
     skip_if='langchain-nvidia-ai-endpoints')


# ==================== 4. the audit must load, not look
edit('scripts/audit_stack.py',
     '''    line(OK, "the guardrails module imports", f"mode()={G.mode()}")
    t0 = time.perf_counter()
    avail = G.available()
    line(OK if avail else WARN,
         "the colang rails load" if avail else "the colang rails did not load",
         f"{(time.perf_counter() - t0) * 1000:.0f}ms")
    if not avail:
        issues.append("colang rails wired but not loadable")''',
     '''    line(OK, "the guardrails module imports", f"mode()={G.mode()}")
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
            issues.append(f"colang rails fail to load ({type(e).__name__})")''',
     'audit_stack.py  load the rails instead of checking for a file',
     skip_if='the colang rails LOAD')


# ==================== 5. the record
append('ENGINEERING.md',
       '''
## 22. The colang rails had never once loaded

`ASOIA_NEMO_RAILS=shadow` was set and nothing happened. Three faults were stacked,
and each one hid the next.

**config.yml named a flow that does not exist.** `rails.co` defines three flows;
the config listed four, and nemoguardrails rejects the whole configuration if one
is missing:

    InvalidRailsConfigurationError: The provided output rail flow
    `require grounding` does not exist

So every load raised, `_get()` caught it, printed one line, and carried on without
rails. The flow is deleted rather than written: grounding here is checked
deterministically, and a model judging its own grounding would be weaker than
`check_grounding` comparing figures against tool results.

**The package that `engine: nim` needs was never declared.** That engine
instantiates `ChatNVIDIA` from `langchain-nvidia-ai-endpoints`, which was not in
the `nvidia` extra and so was never installed.

**The model had no base url.** `parameters={}` meant the hosted endpoint, and that
model has answered HTTP 410 since 2026-08-26. The field is `base_url`;
`nim_base_url` - the name in the deprecation warning everyone sees - is *not* a
ChatNVIDIA field. It is accepted, moved into `model_kwargs` with a UserWarning, and
the url stays hosted:

    base_url      -> http://localhost:8000/v1
    nim_base_url  -> https://integrate.api.nvidia.com/v1

### That deprecation warning is not yours

    nemoguardrails/library/jailbreak_detection/rail_config.py:77
      if self.nim_url and not self.nim_base_url:

nemoguardrails raises it against its own field while validating its own
jailbreak-detection config. Nothing here sets it. It is still worth handling,
because under `-W error` it becomes an exception and the rails disable themselves:
a third party's deprecation notice should not be able to switch off a safety
control. `load_nemo_rails()` suppresses it around that one call.

### A presence check read as a liveness check

`scripts/audit_stack.py` reported "the colang rails load (3ms)" about rails that
had never loaded, because it called `available()` - which asks only whether the
library imports and a `.co` file is on disk. It loads them now. Every claim in an
audit should be something the audit actually did.
''',
       'ENGINEERING.md  section 22', skip_if='## 22. The colang rails had never')

edit('patches/README.md',
     '''| `quality_pass34.py` |''',
     '''| `quality_pass35.py` | the colang rails had never loaded: a flow name that does not exist, an undeclared package, and a base url pointing at a retired model |
| `quality_pass34.py` |''',
     'patches/README.md  the pass 35 row',
     skip_if='`quality_pass35.py`')


# ==================== verify
print("Quality pass 35:")
for c in CHANGES:
    print(c)

bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


print("\nthe colang config:")
cfg = (ROOT / "app/guardrails/config/config.yml").read_text()
co = (ROOT / "app/guardrails/config/rails.co").read_text()
# The property that broke it: every flow named must be defined. Compare the two
# files rather than asserting a count, which would drift the moment a flow is added.
named = [l.strip()[2:] for l in cfg.splitlines()
         if l.startswith("      - ")]
defined = [l[len("define flow "):].strip() for l in co.splitlines()
           if l.startswith("define flow ")]
missing = [f for f in named if f not in defined]
chk("every flow named in config.yml is defined in rails.co", not missing,
    f"missing: {missing}" if missing else f"{len(named)} flows, all defined")
# `named`, not the file text. The comment in config.yml explains that a
# `require grounding` flow used to be listed here, so searching the raw file finds
# the explanation and calls it the bug. That is the SIXTH time in this project
# (29, 30, 31, 33, 34, here) and every one of them had the same shape: a check
# reading the prose next to the code. Assert against parsed structure.
chk("no grounding flow is enabled", "require grounding" not in named,
    f"enabled: {named}")
chk("the model points at the local NIM",
    "base_url: http://localhost:8000/v1" in cfg)
chk("and does not use the non-field",
    "nim_base_url:" not in cfg,
    "ChatNVIDIA has no such field; it lands in model_kwargs")

print("\nthe load:")
r = (ROOT / "app/guardrails/rails.py").read_text()
ast.parse(r)
chk("rails.py parses", True)
chk("the load ignores DeprecationWarning",
    "warnings.catch_warnings()" in r and 'simplefilter("ignore", DeprecationWarning)' in r)
chk("only around the load",
    r.count("catch_warnings()") == 1,
    "a blanket filter would hide our own deprecations too")
pj = (ROOT / "pyproject.toml").read_text()
chk("engine: nim's package is declared",
    "langchain-nvidia-ai-endpoints" in pj)

print("\nthe audit:")
au = (ROOT / "scripts/audit_stack.py").read_text()
ast.parse(au)
chk("audit_stack.py parses", True)
chk("it loads the rails", "load_nemo_rails" in au)
chk("it no longer reports available() as a load",
    'avail = G.available()' not in au,
    "a presence check is not a liveness check")

print("\nit actually loads (needs nemoguardrails and the local NIM):")
try:
    sys.path.insert(0, ".")
    from app.guardrails.rails import load_nemo_rails
    obj = load_nemo_rails()
    chk("load_nemo_rails() returns LLMRails", type(obj).__name__ == "LLMRails",
        type(obj).__name__)
except Exception as e:
    chk("load_nemo_rails() succeeds", False, f"{type(e).__name__}: {str(e)[:110]}")

print("\nand survives warnings-as-errors, which is the point:")
try:
    out = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c",
         "from app.guardrails.rails import load_nemo_rails as f; "
         "print(type(f()).__name__)"],
        capture_output=True, text=True, timeout=180)
    ok = "LLMRails" in (out.stdout or "")
    chk("the rails load under -W error::DeprecationWarning", ok,
        (out.stdout or out.stderr or "").strip().splitlines()[-1][:100]
        if (out.stdout or out.stderr) else "no output")
except Exception as e:
    chk("the -W error check ran", False, f"{type(e).__name__}: {e}")

print("\nthe record:")
eng = (ROOT / "ENGINEERING.md").read_text()
chk("ENGINEERING section 22", "## 22. The colang rails had never" in eng)
chk("it records the flow that did not exist", "require grounding" in eng)
chk("it records that nim_base_url is not a field",
    "not* a\nChatNVIDIA field" in eng or "is *not* a" in eng)
pr = (ROOT / "patches/README.md").read_text()
chk("pass 35 is in the table", "`quality_pass35.py`" in pr)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
    bash scripts/stack.sh restart          the rails are cached per process
    .venv/bin/python scripts/audit_stack.py
""")
sys.exit(1 if bad else 0)
