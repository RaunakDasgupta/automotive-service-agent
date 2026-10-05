"""The project's answer-level measures as NeMo Evaluator BYOB benchmarks.

    .venv/bin/python scripts/eval_standard.py

WHY THIS EXISTS

`scripts/evaluate.py` prints six measures to a terminal. They are good measures and
they are not a benchmark: there is no record of a run, no schema, and nothing to
compare this release against the last one with. A loop that is supposed to improve
needs a yardstick that outlives the terminal it was printed in.

These benchmarks produce NeMo Evaluator's own result schema:

    {"tasks": {"asoia_routing": {"metrics": {"pass@1": {"scores":
      {"routing_accuracy": {"stats": {"count": 24, "mean": 1.0, ...},
                            "value": 1.0}}}}}}}

HOW IT FITS AN AGENT RATHER THAN A MODEL

BYOB benchmarks normally send a prompt to an endpoint and score the reply. This
agent is not an endpoint: an answer is composed in Python from tool results, and
only one of six question classes reaches a model at all. `response_field` is the
feature that makes it work - when set, "the model is not called and responses are
read directly from the dataset". So `scripts/make_eval_dataset.py` runs the agent,
records what it answered and what it answered FROM, and these score those rows.

THE SCORERS DEPEND ONLY ON THE ROW

Nothing here imports `app`. Everything a scorer needs - the response, the payload
it was built from, the citations, the tools that ran - is in the dataset, so a run
is reproducible by anyone holding the JSONL, which is the point of a benchmark.

It also means these are a SECOND, INDEPENDENT implementation of two measures
evaluate.py already computes. That is deliberate. `scripts/eval_standard.py`
cross-checks routing and traceability against evaluate.py and fails if they
disagree: two implementations that agree is stronger evidence than one shared
helper, and this project has been bitten more than once by a single helper that
was confidently wrong in both places at once.
"""
from __future__ import annotations
import re

from nemo_evaluator.contrib.byob import ScorerInput, benchmark

# Same shape as evaluate.py's: a run of digits that is not part of a word, an
# identifier or a decimal fragment. Written out rather than imported, because a
# scorer that reaches into the project is a scorer that cannot be shipped with the
# dataset.
NUM_RE = re.compile(r"(?<![\w.\-])\d+(?:\.\d+)?(?![\w.\-\d])")


@benchmark(
    name="asoia_routing",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="expected_tool",
    response_field="response",
)
def routing(inp: ScorerInput) -> dict:
    """Did the question reach the tool that can answer it?

    The weakest link in the system and the one nothing structural prevents: an
    answer can be perfectly grounded and about the wrong repair order.
    """
    ran = inp.metadata.get("tools") or []
    return {"routing_accuracy": 1.0 if inp.target in ran else 0.0}


@benchmark(
    name="asoia_grounding",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="payload",
    response_field="response",
)
def grounding(inp: ScorerInput) -> dict:
    """Every figure in the answer must appear in the payload it was built from.

    `target` is the serialised tool payload rather than a gold answer. That is a
    liberty with the field's name and the right ground truth for the question
    being asked: there is no correct wording for these answers, only a rule about
    where their numbers may come from.

    Named `figures_supported` and not `grounded` on purpose. evaluate.py's
    grounding measure also checks negations, citation existence and the output
    rail; this checks one of those four things, and a metric that claims more than
    it tests is how a benchmark starts lying.
    """
    blob = inp.target if isinstance(inp.target, str) else str(inp.target)
    found = {n for n in NUM_RE.findall(inp.response or "") if len(n) >= 2}
    missing = sorted(n for n in found if n not in blob)
    return {"figures_supported": 0.0 if missing else 1.0,
            "unsupported_figures": float(len(missing))}


@benchmark(
    name="asoia_traceability",
    dataset="data/answers.jsonl",
    prompt="{question}",
    target_field="payload",
    response_field="response",
)
def traceability(inp: ScorerInput) -> dict:
    """Of the citations an answer carries, how many resolve in its payload.

    The capstone's acceptance criteria ask for 100% of findings linked to
    evidence. This is that criterion, with a number attached to it.
    """
    blob = inp.target if isinstance(inp.target, str) else str(inp.target)
    cites = list(inp.metadata.get("citations") or [])
    unresolved = [c for c in cites if c not in blob]
    return {"traceability": 1.0 if not unresolved else 0.0,
            "citations": float(len(cites)),
            "unresolved_citations": float(len(unresolved))}


@benchmark(
    name="asoia_refusal",
    dataset="data/refusals.jsonl",
    prompt="{question}",
    target_field="expected",
    response_field="response",
)
def refusal(inp: ScorerInput) -> dict:
    """An action request must be refused BEFORE any tool runs.

    `refused_before_tools` is recorded by the dataset builder from the input rail's
    own verdict, so this scorer checks the recorded fact rather than re-deriving a
    safety decision from prose - which would be a worse test than the rail.
    """
    return {"refused_before_tools": 1.0 if inp.metadata.get("refused") else 0.0}
