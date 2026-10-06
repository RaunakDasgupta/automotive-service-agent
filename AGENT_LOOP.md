# The improvement loop

You are a coding agent in a NemoClaw sandbox, working on this repository. This
file is the whole brief: assume you have no other context.

## What this repository is

An automotive service-advisor agent on the NVIDIA stack. A router picks from
eleven tools, most answers are assembled in Python from DuckDB and an event
log, and only free-text search is narrated by a model. There is a measurement
suite over 37 labelled questions - seven NeMo Evaluator benchmarks plus a
second, independent implementation in `scripts/evaluate.py` that exists to
disagree with the first one.

The project's standard is that **no claim is made without a measurement that
could have failed.** Every number in the README was produced by running
something. If you cannot measure a change, do not describe it as an
improvement.

## The box you are on cannot run the full suite

This sandbox is CPU-only. It cannot serve the chat NIM or the embedding model,
so retrieval, rerank and narration cannot be scored here. What runs here is the
model-free half:

```
python scripts/agent_loop.py fast
```

That scores routing, grounding, traceability and refusal against a committed
baseline, and takes seconds. It is a **signal, not a verdict**. The verdict is
`agent_loop.py gate` on the GPU box, which regenerates every answer with the
real models and runs all seven benchmarks.

A `fast` run that improves while the `gate` run regresses is the expected
failure mode of working here. Do not assume the fast number generalises.

### Setup, once

```
python -m venv .venv && . .venv/bin/activate && pip install -e .
python -m app.data.generate
python scripts/agent_loop.py status
```

The dataset is seeded (20260924) and the clock anchors to the newest event in
the log, so your shop is the same shop the gate will score. Do not pin
`ASOIA_NOW` and do not reseed - that is what makes your numbers comparable.

**Your counts will not match the gate's, and that is expected.** Your database
is freshly generated and pristine; the GPU box's has accumulated `updates` from
demo and voice use. Measured: the same code scores 891 resolving citations here
and 954 there. Every *gated* metric is a rate, and those matched exactly - but
do not read a differing total as a regression you caused.

## What you may not edit

These five files are the measure:

```
evals/truth.py              evals/asoia_byob.py       scripts/evaluate.py
scripts/eval_standard.py    scripts/make_eval_dataset.py
```

They are checksummed in `evals/harness.lock`, and both `fast` and `gate` refuse
to print any score while one of them differs. This is not a formality. An agent
optimising against a scorer will eventually edit the scorer, usually while
believing it is fixing a bug in it, and a number from a modified measure cannot
be compared to the baseline it is being compared against.

If you are convinced the measure itself is wrong, **stop and say so in the
handoff** with the evidence. Do not relock; that verb is for a human.

Also do not: add a question without adding its SQL truth to
`make_eval_dataset.py` (the coverage floor will fail the run, by design), widen
a tolerance, delete a failing question, or special-case a benchmark input.

## What counts as an improvement

`gate` passes only when all three agree: the suite's own exit code, the
cross-check between the two implementations, and no regression against the
baseline. A metric that is absent from your run is treated as a regression, not
as a pass.

Three metrics are inverted (`spurious_tools`, `unresolved_citations`,
`unsupported_figures`) - lower is better. Two are counts that say how much the
measure looks at (`arg_rules_checked`, `figures_per_row`) and are gated upward,
because letting them fall is how a suite stays green while checking less.

## Where the headroom actually is

Be aware of this before you start: **most gated metrics are already at 100%.**
`plan_exact`, `arg_agreement`, `answer_accuracy`, `relevance`, `traceability`,
`figures_supported` and `refused_before_tools` are saturated, and
`accuracy_scored` is at 94.6%, which is its ceiling - the two remaining
questions are free-text searches with no correct number to check, and they are
covered by grounding and relevance instead.

So "raise the numbers" is nearly exhausted, and an agent pointed at a saturated
metric will overfit or quietly weaken the measure. The real work is:

1. **The NeMo Agent Toolkit path composes badly.** It selects the right tool
   18/18 and executes 18/18, but produces a good answer only 3/18. The wiring
   is fixed; the composition is weak. This is the largest measured gap in the
   project.
2. **Retrieval recall is 83.3%** on the realistic query (complaint + car).
   Complaint-only text has a hard 53.0% ceiling because 400 repair orders share
   36 complaint texts, so do not chase that one.
3. **Strengthen the measure where it is thin.** `figures_per_row` is 1.17 and
   `arg_rules_checked` is 1.19 - most rows have one independently derived
   figure. More SQL-derived truth per answer makes the suite harder to satisfy
   by accident, which is worth more than another saturated percentage.

If you cannot find a real improvement, say that. A handoff saying "I tried four
things, here is what each measured, none of them helped" is a good outcome and
an honest one. Inventing a change to have something to show is not.

## Conventions you must follow

- Every behaviour change gets an idempotent, anchor-asserting patch script
  `patches/quality_passNN.py` supporting `--check`, plus a row in
  `patches/README.md` and a numbered section in `ENGINEERING.md` explaining what
  was wrong and how it was proved wrong.
- Comments explain *why*, and particularly why the obvious alternative was not
  chosen. Match the surrounding density.
- Do not commit `.env`, and never print a key.

## Handing off

```
git checkout -b loop/<short-topic>
git commit -am "<what the measurement showed, not what you attempted>"
git push origin loop/<short-topic>
```

Then write a handoff containing, for each thing you tried: what you changed,
the `fast` numbers before and after, and whether you believe it will survive
the gate. Flag anything you could not measure here. The GPU box pulls the
branch and runs `agent_loop.py gate`; if it regresses, the branch is not merged
and the numbers in the gate output are the reason.
