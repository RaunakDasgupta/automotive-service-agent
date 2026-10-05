#!/usr/bin/env python3
"""pass 49 - the NeMo Agent Toolkit workflow had never once run.

    .venv/bin/python patches/quality_pass49.py            apply
    .venv/bin/python patches/quality_pass49.py --check    verify, change nothing

WHAT WAS WRONG

`aiq run --config_file app/agent/workflow.yml` fails:

    Invalid configuration: functions: Input tag 'service_ops_tools' found
    using discriminator() does not match any of the expected tags: ...

`app/agent/nat_functions.py` registers that function type correctly, and
importing it by hand sets NAT_AVAILABLE=True, which is why every check I had
written passed. But the toolkit never imports it. NAT discovers third-party
components through the `nat.components` entry-point group, and this package
declared no entry points at all - so `aiq run` starts with the twelve built-in
groups, finds no `service_ops_tools`, and stops before anything of ours runs.

The registration was real, the wiring was missing, and nothing tested the
difference because the only test imported the module directly. That is the
same shape of error as pass 22, where the colang rails had never loaded: a
component that is present, correct and unreachable.

Two changes:

1. Declare the entry point, so the toolkit finds the registration.
2. Import from `nat.*` rather than `aiq.*`. Both resolve - aiqtoolkit 1.4.3 is
   a shim over nvidia-nat 1.4.3 - but `aiq` emits a DeprecationWarning on every
   import and is scheduled for removal. Pass 41 already renamed the dependency;
   this finishes the job in the code.

The entry point only takes effect once the package metadata is rebuilt, so this
script reinstalls it in place and then says so.
"""
from __future__ import annotations
import argparse, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK = "--check" in sys.argv

PYPROJECT = ROOT / "pyproject.toml"
NATFUNCS = ROOT / "app/agent/nat_functions.py"

EP_ANCHOR = "[build-system]"
EP_BLOCK = '''# NeMo Agent Toolkit discovers third-party components through this group. It
# is the whole reason `aiq run` can see service_ops_tools: the registration in
# app/agent/nat_functions.py is correct, but the toolkit never imports a module
# nothing points it at.
[project.entry-points."nat.components"]
asoia_service_ops = "app.agent.nat_functions"

[build-system]'''

IMPORTS_OLD = """    from aiq.builder.builder import Builder
    from aiq.builder.function_info import FunctionInfo
    from aiq.cli.register_workflow import register_function
    from aiq.data_models.function import FunctionBaseConfig
    NAT_AVAILABLE = True"""

IMPORTS_NEW = """    # nvidia-nat is the package; `aiq` is a deprecated shim over it that warns
    # on every import. Prefer the real namespace, fall back for older installs.
    try:
        from nat.builder.builder import Builder
        from nat.builder.function_info import FunctionInfo
        from nat.cli.register_workflow import register_function
        from nat.data_models.function import FunctionBaseConfig
    except ImportError:
        from aiq.builder.builder import Builder
        from aiq.builder.function_info import FunctionInfo
        from aiq.cli.register_workflow import register_function
        from aiq.data_models.function import FunctionBaseConfig
    NAT_AVAILABLE = True"""


def edit(path: pathlib.Path, old: str, new: str, skip_if: str) -> str:
    rel = path.relative_to(ROOT)
    s = path.read_text()
    if skip_if in s:
        return f"already   {rel}"
    if old not in s:
        return f"ANCHOR    {rel}"
    if not CHECK:
        path.write_text(s.replace(old, new, 1))
    return f"{'would patch' if CHECK else 'patched  '} {rel}"


results = [
    edit(PYPROJECT, EP_ANCHOR, EP_BLOCK, 'entry-points."nat.components"'),
    edit(NATFUNCS, IMPORTS_OLD, IMPORTS_NEW, "from nat.builder.builder"),
]

WF = ROOT / "app/agent/workflow.yml"

# The ReAct agent validates two placeholders and partials the configured tool
# list into them; without them it refuses to build the workflow, and without
# the Thought/Action block it builds and then cannot parse the reply. Our
# prompt carried the project's grounding rules and none of the scaffolding.
# Keep the rules and add the scaffolding, rather than fall back to NAT's
# default, which says nothing about citations or about never authorising work.
WF_OLD = """  system_prompt: |
    You are a service operations assistant for a vehicle workshop."""

WF_NEW = """  # {tools} and {tool_names} are REQUIRED by the ReAct agent and are filled
  # in by the toolkit from the configured tool group.
  system_prompt: |
    You are a service operations assistant for a vehicle workshop."""

WF_TAIL_OLD = """    that. Write in plain British English."""

WF_TAIL_NEW = """    that. Write in plain British English.

    You have these tools:

    {tools}

    Use this format exactly when you need a tool:

    Question: the question you must answer
    Thought: what you need to find out
    Action: one of [{tool_names}]
    Action Input: the input to the action, or None
    Observation: wait for the result - never invent one

    Repeat Thought/Action/Action Input/Observation as needed. When the tools
    have given you enough:

    Thought: I now know the final answer
    Final Answer: the answer, citing the repair order and update ids used"""

results.append(edit(WF, WF_TAIL_OLD, WF_TAIL_NEW, "{tool_names}"))
results.append(edit(WF, WF_OLD, WF_NEW, "REQUIRED by the ReAct agent"))

for r in results:
    print(" ", r)

if any(r.startswith("ANCHOR") for r in results):
    print("\nFAILED")
    sys.exit(1)

if CHECK:
    print("\ncheck only - nothing written")
    sys.exit(0)

# The entry point lives in the installed metadata, not in the source tree, so
# the declaration above does nothing until the package is reinstalled.
print("\n  rebuilding package metadata so the entry point registers...")
r = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "pip", "install",
                    "-e", ".", "--no-deps", "-q"],
                   cwd=ROOT, capture_output=True, text=True)
if r.returncode != 0:
    print("  pip install -e . failed:")
    print("   ", (r.stderr or r.stdout).strip().splitlines()[-1][:200])
    print("  Run it by hand, then re-check with `aiq info components`.")
    sys.exit(1)
print("  done")
print("\npass 49 applied")
