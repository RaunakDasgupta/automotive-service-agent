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
scripts/timings.py
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

## Latency is gated too, and you cannot measure it here

`gate` also compares six latency numbers, all lower-is-better:

```
worst_python_ms   llm_best_ms   llm_model_ms
llm_prompt_tokens llm_completion_tokens   total_best_ms
```

**Timing needs the NIMs, so it runs only on the GPU box.** You can reason about
latency here - count what you are adding to a prompt, notice a loop over
retrieved rows - but you cannot measure it. Say so in the handoff rather than
estimating a millisecond figure you did not observe.

The thresholds come from three consecutive runs on an idle L40S: the model path
varied 0% (1797/1799/1795 ms), prompt and completion tokens 0%, and the Python
paths 1-2% above 6 ms. The gate allows 15% or 5 ms on times and 10% on tokens -
roughly ten times the observed noise - because a latency gate that cries wolf
gets switched off. It is there to catch a change that doubles a stage.

### Do not try to shorten the narration prompt

Five variants were measured and every one was worse; section 50 of
`ENGINEERING.md` has the numbers. The short version: the system prompt is 46% of
the narration prompt and compressing it made the answer 27% LONGER and the turn
20% slower, because the restatement being removed is what stops the model
listing each note with a quote. Changing only the sentence budget - one line,
"two to four" to "two or three" - took one answer from 48 words to 83.

Instructing this 8B model to be shorter makes it longer. If you have a new idea
here, measure it on both search questions before you believe it, and expect the
latency gate rather than the correctness suite to be the thing that fails you.

### The measured profile, so you optimise the right thing

```
python paths        2-62 ms   no model call at all
search question     1797 ms   model 1453, rerank 108, embed 0 (cached), rest 235
                              prompt 1146 tokens -> 99 generated, 68 tok/s
```

Five of six questions never touch a model. **If a Python path is slow the cost
is SQL or the event fold, not the GPU** - do not look for a model optimisation
there.

For the one model path, generation dominates: 1453 of 1797 ms. The levers in
order of measured size are generation length, then the 1146-token prompt, then
the 235 ms of SQL and rendering. Note that `completion_tokens` is 99 against a
`max_tokens` of 400, so the answer is not being truncated - it is simply that
length. An answer that gets *shorter* will get faster, which is a quality
decision and not a free win.

**Do not remove the reranker.** The ablation measures it at +5.0 points of
recall@6 and +0.018 MRR for +0.01 s per query, over 120 queries - it earns its
latency, and this has been measured twice because the first attempt used too
small a sample and wrongly concluded it did not.

## Where the headroom actually is

Be aware of this before you start: **most gated metrics are already at 100%.**
`plan_exact`, `arg_agreement`, `answer_accuracy`, `traceability`, `cited`,
`figures_supported` and `refused_before_tools` are saturated, and
`accuracy_scored` is at 94.6%, which is its ceiling - the two remaining
questions are free-text searches with no correct number to check, and they are
covered by grounding and relevance instead.

**`free_of_meta` is 97.3% and that one is real.** The answer to "any notes about
a burning smell" opens by referring to the records rather than answering, which
`SYSTEM_SEARCH` explicitly forbids, and `relevance` is 99.1% because it is the
mean of three. This is the only unsaturated quality metric with a genuine defect
behind it, so it is the best target in this list - but read section 50 and 51 of
`ENGINEERING.md` first: five fixes were measured and all of them made something
worse. A prompt rule broadened to ban the bare form produced "There are four
notes about a burning smell" and then listed the four. If you try a
deterministic fix on the agent side, implement the check independently of
`_META` in `evals/asoia_byob.py` - if the agent filters on the same regex the
benchmark scores, the benchmark stops being evidence.

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
