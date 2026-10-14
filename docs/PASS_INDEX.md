# Pass index

Sixty-one numbered passes shaped this codebase. Each was a one-shot script
`patches/quality_passNN.py` that found a defect by measuring something, fixed
it, and wrote down how it was found. Passes 1–47 were applied before the first
commit and arrived in it together; passes 48–61 are one commit each. The scripts
have been **removed from the tree** because they are history, not tooling: every
one is already reflected in the code, several would now undo later work if run,
and a directory of 62 scripts beside the source suggests otherwise.

Nothing was lost. They are in git history, as of commit `0da0c58`:

```bash
git show 0da0c58:patches/quality_pass41.py        # read one
git ls-tree -r --name-only 0da0c58 patches/       # list them all
```

This page is the index that `patches/README.md` used to be: what each pass
addressed, and where `ENGINEERING.md` tells the story. Comments in the code that
say "pass 44" mean the row below.

## What was checked before they were removed

The scripts were applied once, in numeric order, and were never meant to be
re-run. So "are they all applied?" was answered three ways, none of which is
"run them against the real tree":

1. **Each script against its own fresh copy of HEAD**, with subprocesses faked
   and the network blocked. 47 of 62 change nothing that is tracked. The other
   15 (passes 11, 12, 22, 23, 24, 25, 27, 30, 31, 35, 37, 42, 49, 55, 56) would
   still edit something, and each was read: in every case the change they carry
   is an *older state* of code a later pass or a deliberate fix has since
   replaced - pass 31 would strip the `stores` verb and the restart policy back
   out of `stack.sh`, pass 35 would restore the rails config pass 46 replaced,
   pass 24 would put back a LanceDB review layer, pass 55 would append scorers
   that pass 56, 57 and 61 rewrote. Running them would regress the tree. Pass 41
   did not finish: it starts a UI and waits for it, which the harness cannot
   give it - its edits were checked by the second method.
2. **Every edit they declare, tested against HEAD**: 258 `edit()` calls plus 119
   `(old, new)` pairs held as data. Each is applied, or superseded, or an
   insertion whose anchor still exists because the inserted text has since
   evolved. **One was genuinely unapplied**: pass 41 removed `GRADIO_AUTH` from
   the code, the launcher and the prose, but its README edit never landed, so
   the README kept documenting a variable nothing reads and a `--share`
   precondition that no longer exists. Fixed with this change, along with the
   same stale claim in `.env.example`, `docs/BREV_RUNBOOK.md` and the notebook
   generator.
3. **The behaviour**: `pytest` (81), `scripts/agent_loop.py fast` against the
   committed baseline (routing 37/37, grounding 35/35, traceability 905/905,
   refusal 4/4, nothing regressed), `verify_answers.py`, `verify_data.py`,
   `test_review.py` and `test_injection.py`.

What this could not check, because the flywheel and NeMo packages are not
installed outside the GPU box: `test_trace.py`, `test_switchyard.py`, the
NeMo Guardrails rails and the Agent Toolkit workflow were checked statically
only. Run them on the box before relying on them.

## How the passes worked

- **Anchor-asserting.** A script located its edit by an exact string, refused if
  it matched zero or more than once, and said so. Re-running was a no-op or a
  clear failure, never a second application.
- **A skip test has to cover everything its edit does.** Pass 16's fourth edit
  added `-u` to `docker run` and changed a port mapping, but its skip test only
  checked the port. On a tree where the port had been fixed by hand the whole
  edit skipped, the `-u` was never added, and the script reported success.
- **Order mattered, and later passes broke earlier ones on purpose.** Pass 10
  fixes a regression pass 8 introduced; pass 19 fixes a rail hole pass 11 opened;
  pass 15's tie-break exists because its first version broke two of the 81
  tests. That is the useful part of the record.

## Index

| pass | what it addressed | in `ENGINEERING.md` |
|---|---|---|
| 1 | system prompt led with safety on every question; tool payload was a single-line JSON dump; the technician tool discarded the repair-order numbers it computed; the reranker never saw the wide candidate pool | §2–§4 |
| 2 | the model cited the payload header, because "TOOL RESULTS" was primed three times; single-sentence answers | §2–§4 |
| 3 | the LLM router cost an extra round trip on every question; figures made deterministic | §2–§4 |
| 4 | the model copied concrete figures out of the prompt's own worked example | §2–§4 |
| 5 | answers composed in Python for the technician path; tools enriched with operation descriptions, vehicle and concern | §2–§4 |
| 6 | `list_ros` carried a safety flag but not the finding; renderers for the remaining tools; the guardrail degrades to computed figures | §2–§4 |
| 7 | `snapshot.parts` is a dict and was sliced as a list, silently disabling a renderer; shared-part questions routed to the wrong tool | §2–§4 |
| 8 | `detect_anomalies` answers cited nothing, so the output rail blocked them; silent fallbacks made observable | §2–§4 |
| 9 | the `waiter` filter was only reachable by two exact phrasings | §2–§4 |
| 10 | `list_ros` records were stringified into the citation list — a regression pass 8 introduced and `verify_answers.py` caught | §2–§4 |
| 11 | no tool could answer "who worked yesterday afternoon", so it fell to semantic search over update text; the model invented an absence; an empty result was treated as an ungrounded answer | §7 |
| 12 | query embeddings re-fetched on every repeat; the LLM router consulted when it could not help; cold start on the first question; `ui_ask` blocked until the whole answer was ready | §8 |
| 13 | a designed path (`search_updates` has no renderer on purpose) warned on stderr and told the reader it had "fallen back" | §8 |
| 14 | 56% of the narration prompt was rules for a payload the only remaining model path does not have; a truncated answer was indistinguishable from a finished one | §8 |
| 15 | `resolve_op` returned a confident wrong operation when the only shared word was generic; the ambiguity guard sat above the acceptance threshold and had never blocked anything | §9 |
| 16 | the four `start_nims.sh` defects that were only ever fixed by hand on the instance, plus a VRAM cap set on the wrong backend and an HTTP 400 retried four times | §10 |
| 17 | a "what cars" question answered with a roster of technicians; a bare ISO date that made a correct answer look stale; three phrasings that reached no tool, and "overnight" resolving to the wrong twelve hours | §10b |
| 18 | `prometheus-client` was a dependency referenced by nothing — metrics, a scrape config and a provisioned Grafana dashboard | §11 |
| 19 | `fastapi`/`uvicorn` likewise — an HTTP API, and the cross-thread SQLite bug and rail hole it exposed within seconds of having a threadpool in front of it | §12 |
| 20 | an evaluator, and the two attacks it found walking through the guardrails: the injection pattern needed the literal word "previous", and one adjective defeated the action pattern | §13 |
| 21 | the colang rails had never been called; wired in behind off/shadow/on, defaulting to off | §14 |
| 22 | the hosted ASR is gRPC, not REST, and the UI hid that it was failing | §15 |
| 23 | the ASR self-test sent a 440 Hz sine tone and reported success on an empty transcript; real speech, and a graded comparison | §15 |
| 24 | the review layer: `app/review/store.py`, the Data & Retrieval tab and `/review/*` on the API - every number the app shows about its own evidence, from one module so the tab and the API cannot disagree | §16 |
| 25 | the clock follows the newest event instead of the wall clock, and a stale index says so | §17 |
| 25 (docs) | the same pass's documentation, split out because a README anchor must never be able to stop a code pass | §17 |
| 26 | the test suite stops depending on the project's database | §18 |
| 27 | Milvus, and a vector store you can actually correct | §19 |
| 28 | model ids are configuration, not code — the hosted embedder was retired underneath us | §19 |
| 29 | the Vector store tab crashed on a key I renamed without grepping for its readers | §19 |
| 30 | a launcher for Milvus standalone, and the four edit operations on the API | §19 |
| 31 | one command up and down for the whole stack, and a restart policy on the store | §20 |
| 32 | a degraded reranker returned a differently-shaped result and crashed a checker two modules away; the engineering record caught up | §21 |
| 33 | the whole stack self-hosted after the hosted LLM reached end of life (HTTP 410); a row count that read 0 over 1,949 rows | — |
| 34 | the hosted ASR serves streaming only, so `offline_recognize` had never once worked; and a diagnostic that blamed the network for an argument error | — |
| 35 | the colang rails had never loaded: a flow name that does not exist, an undeclared package, and a base url pointing at a retired model | §22 |
| 36 | groundedness was measured only where hallucination is impossible, so the one path that narrates was never scored; traceability was enforced and never reported; and an injection arriving in a note met no rail at all | §23–§24 |
| 37 | a script run as the README says it measured a different vector store and nobody noticed; and the rails guarded the question while a release authorisation walked in through a technician's note | §25–§26 |
| 38 | the agent recorded what it answered and never how; ATOF traces of every tool and model call, and the Relay API that looks right for this and would have captured nothing | §27 |
| 39 | six good measures that only existed in a terminal; the answer-level ones are NeMo Evaluator benchmarks now, scored twice by different code so a disagreement is reported rather than averaged | §28 |
| 40 | the loop could capture and score but not decide; a Switchyard proxy routes every model call, its schema reverse-engineered from the loader's own errors, and five of six questions still ask it for nothing | §29 |
| 41 | the login in front of the public UI removed on request, everywhere rather than in one place, and the risk written down where the decision was made instead of left to be discovered | §30 |
| 42 | operator view of the stores: a startup report of every store and loopback Attu + sqlite-web UIs, read-write, outside the agent's UI | §31 |
| 43 | pass 42 installed sqlite-web without declaring it, so a fresh box reproduced the stack minus both store UIs; declared as an `admin` extra, with a check that the constraint and the command that installs it cannot drift apart | §31 |
| 44 | the shadow rail comparison matched refusal wording, but a colang `stop` emits no wording at all - so every real block was recorded as an allow, and the colang rails looked inert when they were firing in 1ms with no model call | §31 |
| 45 | Prometheus and Grafana had never been created on this box - stack.sh never mentioned the script that starts them, so the shadow-rail counters were in-process only and died on every restart; and when started they bound every interface, Grafana with anonymous admin | §31 |
| 46 | the three colang rails were dialog flows used as input/output rails, so one of them stopped every utterance in ~1ms with no model call; replaced with the documented prompt-based `self check input`/`self check output` rails, 4/4 blocked and 24/24 allowed on the versioned sets | §32 |
| 47 | row 3 had no code at all; a six-stage NeMo Curator pipeline over the real corpus, whose five heuristic stages correctly remove nothing from generated data and whose sixth quarantines notes that address the model - the injection vector - caught 1/1 with 0 false positives across 1,949 notes | §33 |
| 48 | the two components that were not NVIDIA but had an NVIDIA equivalent going unused: text-to-speech shelled out to `say` or `espeak` (and this box has neither, so the speech harness could not run here at all) - now Riva Magpie TTS, whose output round-trips through the project's own Parakeet ASR with the measurement intact; and Prometheus scraped the application but not the GPU - now NVIDIA DCGM, 19 series, with a GPU row on the provisioned dashboard | §36 |
| 49 | the NeMo Agent Toolkit workflow had never run - the package declared no `nat.components` entry point, so the toolkit never imported the registration that every test had verified by importing it directly; the react prompt was missing the required {tools}/{tool_names}; and no framework binding was installed, which would have downgraded openai 3.3 to 2.54 in the serving venv, so it went into .venv-nat. Three fixed, a fourth found and left: the registration yields ten FunctionInfo where NAT takes one | §38 |
| 50 | the toolkit workflow now runs - one function type per tool instead of one type yielding ten, which registered the first and dropped nine; also exposed get_shift_activity, which was in TOOLS and not in the toolkit registry, and replaced the silently ignored max_iterations with the real max_tool_calls. Five of six question classes complete; free-text search exhausts the loop budget on the 8B. On retrieval: a wider rerank pool gained +7.5 points on the 40 queries it was chosen with and +0.0 on 120 held out, so it was reverted - but the same measurement showed the reranker DOES earn its latency, and the 40-query sample was what had said otherwise | §39 |
| 51 | the sixth question class the toolkit workflow could not answer was a FORMAT limit, not a model one: ReAct asks for a text protocol and a written "Final Answer", and on a page of technician prose the 8B kept narrating instead of stopping. tool_calling_agent uses native function calling - the same mechanism this project's own router has used since pass 11 - and takes the workflow from 5 of 6 to 6 of 6 | §40 |
| 52 | the toolkit workflow chose the right tool for all six question classes and executed none of them: this NIM returns a tool call as assistant TEXT with no `tool_calls` field, so the agent saw nothing to call and handed the JSON back as its answer - and a run that terminates cleanly graded as a pass. An `asoia_nim_toolshim` LLM provider lifts the call out of the text; measured after, selection 18/18 and execution 18/18 over three runs of six, answers 3/18 | §42 |
| 53 | "how many cars came into the shop this week?" was answered **four** against a true **179**: the router knows every weekday and not "this week", so a count over a window fell through to semantic search. Adds `get_intake` (the 11th tool) and a window parser; stops the narration prompt reciting its own rules into the answer; fuses an IDF-weighted lexical ranking into retrieval before the reranker - recall@6 50.0% -> 52.5% on the standard sample and 51.7% -> 55.0% on a slice never used to decide. Routing 24/24 -> 30/30, grounding 22/22 -> 28/28, traceability 524/524 -> 762/762 | §43 |
| 54 | pass 53's intake rule matched the NOUN, so "how many cars were worked on yesterday" was answered with arrivals over a week, and "how many cars are blocked" ran two tools. Arrival, activity and state are now told apart by the VERB; `get_shift_activity` takes a window; the routing measure scores the EXACT PLAN over 37 questions including the three collisions. And the retrieval benchmark turned out to have a ceiling of 53.0% - 400 repair orders share 36 complaints - against a measured 52.5% and a floor of 60%, so it now scores the question a person asks, the complaint AND the car: 83.3% | §44 |
| 55 | three more NeMo Evaluator benchmarks, because the four that existed could all be satisfied by a wrong answer: `asoia_tool_calls` scores the whole call including arguments derived from the question, `asoia_accuracy` checks the stated number against direct SQL the agent never touches, and `asoia_relevance` scores whether the text answers the form asked, names what the question named, and is free of meta-commentary. They immediately found that every handover was the AFTERNOON one - the route passed no shift at all - which routing had scored correct since it was written | §45 |
| 56 | asoia_accuracy scored 10 of 37 questions and reported 100%. evals/truth.py derives blocked, safety, at-risk, waiters, people and shared part holds in SQL from the raw event log with no import of `app`, lifting coverage to 89.2% - and the moment it did, answer_accuracy fell to 91.9%: "One part blocking several jobs" was a hardcoded heading in a renderer whose docstring says every figure is read from the payload. Coverage is now gated at 80%, so a question added without a truth value fails the run | §46 |
| 57 | pass 56 said the handover had "no single headline figure to check". Its second line has four - 46 open, 14 with safety findings, 27 at risk, 25 blocked - and three were already derived in SQL for the list_ros questions. The accuracy scorer now takes a LIST of expected figures, so 37 rows carry 41 checked numbers; coverage 89.2% -> 94.6%, which is the ceiling, and the floor ratchets 80% -> 90% | §47 |
| 58 | a NemoClaw launchable was deployed to improve this agent, and connecting it to the GPU box would not have done that: NemoClaw is a coding-agent sandbox platform, `nemoclaw-asoia` has no GPU, and its gateway's only ingress is browser SSO that a headless client cannot complete. So the loop uses GitHub as the transport and `scripts/evaluate.py` without `--with-llm` as the sandbox's model-free signal - no second scorer, because that subset already existed. `evals/harness.lock` checksums the five files that turn behaviour into a number and both verbs refuse to print a score while one differs, because an agent optimising against a scorer eventually edits the scorer. Verified by appending one comment to `evals/truth.py`: `fast` exited 2 and named the file | §48 |
| 59 | latency had been measured and printed since `timings.py` was written and never *gated*, so an agent told to make the agent faster could trade correctness for milliseconds with every check still green. `timings.py` gains `--json`, `gate` reads it, and six lower-is-better numbers are gated. Thresholds measured before being chosen - three runs gave 0% spread on the model path and on both token counts, 1-2% on Python paths - so the gate allows 15%/5ms and 10% on tokens, roughly ten times the noise. Verified against ten synthetic cases: +14% passes, +16% fails, a doubled stage fails, a vanished metric fails. `timings.py` joins the lock, because a measure that feeds a gate is one an agent can edit | §49 |
| 60 | **no code change.** Five attempts to shorten the narration prompt and cut generation length, all measured, all worse: a 9.4% shorter prompt produced a 27% LONGER answer and a 20% slower turn, because the verbosity removed from `SYSTEM_SEARCH` was what suppressed note-by-note listing. Changing only the sentence budget took one answer from 48 words to 83 - instructing this 8B model to be shorter makes it longer. Two gaps fell out and are worth more than the optimisation: all 19 correctness metrics stayed flat on a variant that misattributes a Kia's symptom to a Passat, so only pass 59's latency gate failed it; and `free_of_meta` scores 100% on the baseline answer opening "Notes indicate", a phrasing the prompt explicitly bans | §50 |
| 61 | the two holes pass 60 found, closed. `free_of_meta` required BOTH an article and one of two verbs, so `Notes indicate ...` scored 100% on the gated baseline; the referent is now matched generally, including the existential `There are four notes about ...` the model produced the moment the first forms were closed off. Quoted spans are stripped first, because SYSTEM_SEARCH tells the model to quote technicians whose words contain `Notes on the RO.` - which is the real reason the old patterns were narrow enough to miss a violation. `traceability` asked only whether citations RESOLVE, so an answer with none scored 1.0 vacuously; `cited` is the floor, at 100% over 37. Cost: free_of_meta 100% -> 97.3%, which is not a regression but the first honest measurement of it | §51 |

Sections 1–14 of `ENGINEERING.md` are thematic, not keyed by pass, so the
mapping for passes 1–21 is by subject. Sections 15–21 were written together in
pass 32 and cover passes 22–32. Passes 33 and 34 have no section of their own;
their account is the table row above and the comments at the code they touched.
