# patches/

Sixteen one-shot migration scripts, kept as the record of what was changed and
why. Each carries a docstring explaining the defect it fixes and how it was found;
`../ENGINEERING.md` groups them by area.

They were applied in numeric order against the code as originally delivered.

| script | what it addressed |
|---|---|
| `quality_pass.py` | system prompt led with safety on every question; tool payload was a single-line JSON dump; the technician tool discarded the repair-order numbers it computed; the reranker never saw the wide candidate pool |
| `quality_pass2.py` | the model cited the payload header, because "TOOL RESULTS" was primed three times; single-sentence answers |
| `quality_pass3.py` | the LLM router cost an extra round trip on every question; figures made deterministic |
| `quality_pass4.py` | the model copied concrete figures out of the prompt's own worked example |
| `quality_pass5.py` | answers composed in Python for the technician path; tools enriched with operation descriptions, vehicle and concern |
| `quality_pass6.py` | `list_ros` carried a safety flag but not the finding; renderers for the remaining tools; the guardrail degrades to computed figures |
| `quality_pass7.py` | `snapshot.parts` is a dict and was sliced as a list, silently disabling a renderer; shared-part questions routed to the wrong tool |
| `quality_pass8.py` | `detect_anomalies` answers cited nothing, so the output rail blocked them; silent fallbacks made observable |
| `quality_pass9.py` | the `waiter` filter was only reachable by two exact phrasings |
| `quality_pass10.py` | `list_ros` records were stringified into the citation list — a regression pass 8 introduced and `verify_answers.py` caught |
| `quality_pass11.py` | no tool could answer "who worked yesterday afternoon", so it fell to semantic search over update text; the model invented an absence; an empty result was treated as an ungrounded answer |
| `quality_pass12.py` | query embeddings re-fetched on every repeat; the LLM router consulted when it could not help; cold start on the first question; `ui_ask` blocked until the whole answer was ready |
| `quality_pass13.py` | a designed path (`search_updates` has no renderer on purpose) warned on stderr and told the reader it had "fallen back" |
| `quality_pass14.py` | 56% of the narration prompt was rules for a payload the only remaining model path does not have; a truncated answer was indistinguishable from a finished one |
| `quality_pass15.py` | `resolve_op` returned a confident wrong operation when the only shared word was generic; the ambiguity guard sat above the acceptance threshold and had never blocked anything |
| `quality_pass16.py` | the four `start_nims.sh` defects that were only ever fixed by hand on the instance, plus a VRAM cap set on the wrong backend and an HTTP 400 retried four times |
| `quality_pass17.py` | a "what cars" question answered with a roster of technicians; a bare ISO date that made a correct answer look stale; three phrasings that reached no tool, and "overnight" resolving to the wrong twelve hours |
| `quality_pass18.py` | `prometheus-client` was a dependency referenced by nothing — metrics, a scrape config and a provisioned Grafana dashboard |
| `quality_pass19.py` | `fastapi`/`uvicorn` likewise — an HTTP API, and the cross-thread SQLite bug and rail hole it exposed within seconds of having a threadpool in front of it |
| `quality_pass20.py` | an evaluator, and the two attacks it found walking through the guardrails: the injection pattern needed the literal word "previous", and one adjective defeated the action pattern |
| `quality_pass21.py` | the colang rails had never been called; wired in behind off/shadow/on, defaulting to off |
| `quality_pass22.py` | the hosted ASR is gRPC, not REST, and the UI hid that it was failing |
| `quality_pass23.py` | the ASR self-test sent a 440 Hz sine tone and reported success on an empty transcript; real speech, and a graded comparison |
| *(pass 24 — missing)* | the review layer. Applied and working (`app/review/store.py`, the Data & Retrieval tab) but **its script was never archived here**; see below |
| `quality_pass25.py` | the clock follows the newest event instead of the wall clock, and a stale index says so |
| `quality_pass25_readme.py` | the same pass's documentation, split out because a README anchor must never be able to stop a code pass |
| `quality_pass26.py` | the test suite stops depending on the project's database |
| `quality_pass27.py` | Milvus, and a vector store you can actually correct |
| `quality_pass28.py` | model ids are configuration, not code — the hosted embedder was retired underneath us |
| `quality_pass29.py` | the Vector store tab crashed on a key I renamed without grepping for its readers |
| `quality_pass30.py` | a launcher for Milvus standalone, and the four edit operations on the API |
| `quality_pass31.py` | one command up and down for the whole stack, and a restart policy on the store |
| `quality_pass32.py` | a degraded reranker returned a differently-shaped result and crashed a checker two modules away; the engineering record caught up |
| `quality_pass33.py` | the whole stack self-hosted after the hosted LLM reached end of life (HTTP 410); a row count that read 0 over 1,949 rows |
| `quality_pass34.py` | the hosted ASR serves streaming only, so `offline_recognize` had never once worked; and a diagnostic that blamed the network for an argument error |
| `quality_pass35.py` | the colang rails had never loaded: a flow name that does not exist, an undeclared package, and a base url pointing at a retired model |
| `quality_pass36.py` | groundedness was measured only where hallucination is impossible, so the one path that narrates was never scored; traceability was enforced and never reported; and an injection arriving in a note met no rail at all |
| `quality_pass37.py` | a script run as the README says it measured a different vector store and nobody noticed; and the rails guarded the question while a release authorisation walked in through a technician's note |
| `quality_pass38.py` | the agent recorded what it answered and never how; ATOF traces of every tool and model call, and the Relay API that looks right for this and would have captured nothing |
| `quality_pass39.py` | six good measures that only existed in a terminal; the answer-level ones are NeMo Evaluator benchmarks now, scored twice by different code so a disagreement is reported rather than averaged |
| `quality_pass40.py` | the loop could capture and score but not decide; a Switchyard proxy routes every model call, its schema reverse-engineered from the loader's own errors, and five of six questions still ask it for nothing |
| `quality_pass41.py` | the login in front of the public UI removed on request, everywhere rather than in one place, and the risk written down where the decision was made instead of left to be discovered |
| `quality_pass42.py` | operator view of the stores: a startup report of every store and loopback Attu + sqlite-web UIs, read-write, outside the agent's UI |
| `quality_pass43.py` | pass 42 installed sqlite-web without declaring it, so a fresh box reproduced the stack minus both store UIs; declared as an `admin` extra, with a check that the constraint and the command that installs it cannot drift apart |
| `quality_pass44.py` | the shadow rail comparison matched refusal wording, but a colang `stop` emits no wording at all - so every real block was recorded as an allow, and the colang rails looked inert when they were firing in 1ms with no model call |
| `quality_pass45.py` | Prometheus and Grafana had never been created on this box - stack.sh never mentioned the script that starts them, so the shadow-rail counters were in-process only and died on every restart; and when started they bound every interface, Grafana with anonymous admin |
| `quality_pass46.py` | the three colang rails were dialog flows used as input/output rails, so one of them stopped every utterance in ~1ms with no model call; replaced with the documented prompt-based `self check input`/`self check output` rails, 4/4 blocked and 24/24 allowed on the versioned sets |
| `quality_pass51.py` | the sixth question class the toolkit workflow could not answer was a FORMAT limit, not a model one: ReAct asks for a text protocol and a written "Final Answer", and on a page of technician prose the 8B kept narrating instead of stopping. tool_calling_agent uses native function calling - the same mechanism this project's own router has used since pass 11 - and takes the workflow from 5 of 6 to 6 of 6 |
| `quality_pass52.py` | the toolkit workflow chose the right tool for all six question classes and executed none of them: this NIM returns a tool call as assistant TEXT with no `tool_calls` field, so the agent saw nothing to call and handed the JSON back as its answer - and a run that terminates cleanly graded as a pass. An `asoia_nim_toolshim` LLM provider lifts the call out of the text; measured after, selection 18/18 and execution 18/18 over three runs of six, answers 3/18 |
| `quality_pass53.py` | "how many cars came into the shop this week?" was answered **four** against a true **179**: the router knows every weekday and not "this week", so a count over a window fell through to semantic search. Adds `get_intake` (the 11th tool) and a window parser; stops the narration prompt reciting its own rules into the answer; fuses an IDF-weighted lexical ranking into retrieval before the reranker - recall@6 50.0% -> 52.5% on the standard sample and 51.7% -> 55.0% on a slice never used to decide. Routing 24/24 -> 30/30, grounding 22/22 -> 28/28, traceability 524/524 -> 762/762 |
| `quality_pass54.py` | pass 53's intake rule matched the NOUN, so "how many cars were worked on yesterday" was answered with arrivals over a week, and "how many cars are blocked" ran two tools. Arrival, activity and state are now told apart by the VERB; `get_shift_activity` takes a window; the routing measure scores the EXACT PLAN over 37 questions including the three collisions. And the retrieval benchmark turned out to have a ceiling of 53.0% - 400 repair orders share 36 complaints - against a measured 52.5% and a floor of 60%, so it now scores the question a person asks, the complaint AND the car: 83.3% |
| `quality_pass55.py` | three more NeMo Evaluator benchmarks, because the four that existed could all be satisfied by a wrong answer: `asoia_tool_calls` scores the whole call including arguments derived from the question, `asoia_accuracy` checks the stated number against direct SQL the agent never touches, and `asoia_relevance` scores whether the text answers the form asked, names what the question named, and is free of meta-commentary. They immediately found that every handover was the AFTERNOON one - the route passed no shift at all - which routing had scored correct since it was written |
| `quality_pass56.py` | asoia_accuracy scored 10 of 37 questions and reported 100%. evals/truth.py derives blocked, safety, at-risk, waiters, people and shared part holds in SQL from the raw event log with no import of `app`, lifting coverage to 89.2% - and the moment it did, answer_accuracy fell to 91.9%: "One part blocking several jobs" was a hardcoded heading in a renderer whose docstring says every figure is read from the payload. Coverage is now gated at 80%, so a question added without a truth value fails the run |
| `quality_pass57.py` | pass 56 said the handover had "no single headline figure to check". Its second line has four - 46 open, 14 with safety findings, 27 at risk, 25 blocked - and three were already derived in SQL for the list_ros questions. The accuracy scorer now takes a LIST of expected figures, so 37 rows carry 41 checked numbers; coverage 89.2% -> 94.6%, which is the ceiling, and the floor ratchets 80% -> 90% |
| `quality_pass58.py` | a NemoClaw launchable was deployed to improve this agent, and connecting it to the GPU box would not have done that: NemoClaw is a coding-agent sandbox platform, `nemoclaw-asoia` has no GPU, and its gateway's only ingress is browser SSO that a headless client cannot complete. So the loop uses GitHub as the transport and `scripts/evaluate.py` without `--with-llm` as the sandbox's model-free signal - no second scorer, because that subset already existed. `evals/harness.lock` checksums the five files that turn behaviour into a number and both verbs refuse to print a score while one differs, because an agent optimising against a scorer eventually edits the scorer. Verified by appending one comment to `evals/truth.py`: `fast` exited 2 and named the file |
| `quality_pass59.py` | latency had been measured and printed since `timings.py` was written and never *gated*, so an agent told to make the agent faster could trade correctness for milliseconds with every check still green. `timings.py` gains `--json`, `gate` reads it, and six lower-is-better numbers are gated. Thresholds measured before being chosen - three runs gave 0% spread on the model path and on both token counts, 1-2% on Python paths - so the gate allows 15%/5ms and 10% on tokens, roughly ten times the noise. Verified against ten synthetic cases: +14% passes, +16% fails, a doubled stage fails, a vanished metric fails. `timings.py` joins the lock, because a measure that feeds a gate is one an agent can edit |
| `quality_pass60.py` | **no code change.** Five attempts to shorten the narration prompt and cut generation length, all measured, all worse: a 9.4% shorter prompt produced a 27% LONGER answer and a 20% slower turn, because the verbosity removed from `SYSTEM_SEARCH` was what suppressed note-by-note listing. Changing only the sentence budget took one answer from 48 words to 83 - instructing this 8B model to be shorter makes it longer. Two gaps fell out and are worth more than the optimisation: all 19 correctness metrics stayed flat on a variant that misattributes a Kia's symptom to a Passat, so only pass 59's latency gate failed it; and `free_of_meta` scores 100% on the baseline answer opening "Notes indicate", a phrasing the prompt explicitly bans |
| `quality_pass61.py` | the two holes pass 60 found, closed. `free_of_meta` required BOTH an article and one of two verbs, so `Notes indicate ...` scored 100% on the gated baseline; the referent is now matched generally, including the existential `There are four notes about ...` the model produced the moment the first forms were closed off. Quoted spans are stripped first, because SYSTEM_SEARCH tells the model to quote technicians whose words contain `Notes on the RO.` - which is the real reason the old patterns were narrow enough to miss a violation. `traceability` asked only whether citations RESOLVE, so an answer with none scored 1.0 vacuously; `cited` is the floor, at 100% over 37. Cost: free_of_meta 100% -> 97.3%, which is not a regression but the first honest measurement of it |
| `quality_pass50.py` | the toolkit workflow now runs - one function type per tool instead of one type yielding ten, which registered the first and dropped nine; also exposed get_shift_activity, which was in TOOLS and not in the toolkit registry, and replaced the silently ignored max_iterations with the real max_tool_calls. Five of six question classes complete; free-text search exhausts the loop budget on the 8B. On retrieval: a wider rerank pool gained +7.5 points on the 40 queries it was chosen with and +0.0 on 120 held out, so it was reverted - but the same measurement showed the reranker DOES earn its latency, and the 40-query sample was what had said otherwise |
| `quality_pass49.py` | the NeMo Agent Toolkit workflow had never run - the package declared no `nat.components` entry point, so the toolkit never imported the registration that every test had verified by importing it directly; the react prompt was missing the required {tools}/{tool_names}; and no framework binding was installed, which would have downgraded openai 3.3 to 2.54 in the serving venv, so it went into .venv-nat. Three fixed, a fourth found and left: the registration yields ten FunctionInfo where NAT takes one |
| `quality_pass48.py` | the two components that were not NVIDIA but had an NVIDIA equivalent going unused: text-to-speech shelled out to `say` or `espeak` (and this box has neither, so the speech harness could not run here at all) - now Riva Magpie TTS, whose output round-trips through the project's own Parakeet ASR with the measurement intact; and Prometheus scraped the application but not the GPU - now NVIDIA DCGM, 19 series, with a GPU row on the provisioned dashboard |
| `quality_pass47.py` | row 3 had no code at all; a six-stage NeMo Curator pipeline over the real corpus, whose five heuristic stages correctly remove nothing from generated data and whose sixth quarantines notes that address the model - the injection vector - caught 1/1 with 0 false positives across 1,949 notes |

**These are historical.** Every one asserts its anchors and refuses to apply
twice, so re-running them against the current tree is a no-op or a clear failure,
never a way to change anything. Read them, don't run them.

Several were written because a *previous* pass broke something: pass 10 fixes a
regression from pass 8, and pass 15's tie-break exists because its first version
broke two of the 81 tests. That is the useful part of the record.

## A note on the skip tests

Every script here refuses to apply twice by testing for a marker of its own
change. Pass 16's fourth edit did two things — added `-u` to `docker run` and
changed the port mapping — with a skip test that only checked the port mapping. On
a tree where the port collision had already been fixed by hand, the whole edit
skipped and the `-u` was silently never added, while the script reported success.

It is now two edits, and the one for `-u` matches on a regex rather than a literal
string, because these fixes were first made interactively in a shell where
`-u $(id -u)` and `-u "$(id -u)"` are equally likely. **A skip test has to cover
everything its edit does, or it reports success for half a change.**

## Order matters, and re-running does not

Several of these exist because a *previous* pass broke something: pass 10 fixes a
regression from pass 8, pass 15's tie-break exists because its first version broke
two of the 81 tests, and pass 19 fixes a rail hole opened by pass 11.

They were also verified as a chain. Running all of passes 17-21 forwards and then
backwards changes nothing — `write()` refuses to overwrite a file a later pass has
edited, and says so, because re-running pass 18 after pass 21 once silently
deleted pass 21's `RAIL_SHADOW` counter.

## Passes 22 and 23: speech to text

Pass 22 replaced a REST endpoint that returns `404 page not found` with Riva over
gRPC through NVIDIA Cloud Functions, and fixed a UI that hid the failure — the
transcript box's placeholder was a complete, plausible update in grey, so an empty
box read as a filled-in one.

Pass 23 exists because pass 22 left no way to find out whether transcription
actually works, and its own check proved it:

    note    riva client present - transcript: '' error=None

That is what a 440 Hz sine tone transcribes to, and also what a completely broken
ASR returns. The check could not fail and could not pass. Pass 23 adds real speech
(`scripts/make_speech.py`, via whatever TTS the machine has), grades the result
(`scripts/test_asr.py`), and makes an empty transcript carry its reason instead of
`error=None`.

Its scorer had to be corrected twice before it meant anything, both times in the
same direction — a check that reports the wrong answer confidently:

  * Comparing words naively put a **perfect** transcript at 46% word error, because
    the model writes "1.8" where the script said "one point eight" and writes US
    English against a British sample. Both sides are now canonicalised.
  * The figure check scanned the reference for digits. The samples are dictated,
    so the digits are not there, and it reported a clean sweep on a transcript that
    had dropped every measurement. It canonicalises first now.

**A measurement corrupted from 1.8 to 1.4 is 1.1% word error and a silently wrong
service record.** Word error rate cannot see it; that is why the figures are graded
one at a time, and why that check is the gate rather than the WER.

## Pass 24: the evidence, opened

The project claims every answer is derived from evidence and can name it. That was
only ever checkable from the inside — `check_grounding` asserted it and you had to
trust the assertion. Pass 24 adds `app/review/store.py`, a "Data & Retrieval" tab
and `/review/*` on the API: the event log, the fold that derives state from it,
what is in the vector index, what retrieval actually did, and which chunks each
answer cited.

One layer with no UI in it, because the tab and the API must show the same numbers
rather than two implementations of "how many events are there".

The retrieval trace is the part worth having. `search_updates` returns six passages
and nothing about how they were chosen; the trace keeps the intermediate stage, so a
passage the vector search ranked seventh and the reranker promoted to third is
visible as exactly that. It mirrors `app/retrieval/index.py` rather than sharing its
code, and `scripts/test_review.py --live` asserts the two still cite the same ids —
that test is what notices if retrieval is tuned in one place and not the other.

Its own checks caught three faults in it before it shipped, all the same shape — a
confident wrong answer:

  * `overview()` reported a row of zeros for a database that did not exist. A
    missing schema and an empty shop produce the same COUNT.
  * The chunk browser pulled every 1024-float vector into Python and discarded
    them — 8 KB of churn per row to read a text field.
  * The snapshot was tested for JSON with `json.dumps(v, default=str)`, which
    serialises almost anything. The guard passed and raw dataclasses went into the
    payload. **Testing with a converter that always succeeds is not a test.**

And the generator hit the nested-escaping fault for the third time in this project
(pass 17, pass 23's skip tests, pass 24's package docstring). The rule that keeps
being broken: **never hand-write an escape in a generator — build every literal
from a real file and pass it through `repr()`.** Every literal in pass 24 now comes
from `frag/`.

One check in pass 24 failed against correct code: it asserted nine review endpoints
and there are ten. A hardcoded count is a second copy of a fact. It now asserts that
every documented path is served and that no endpoint bypasses the store.

### Pass 25 is two files, and the reason is a lie this harness tells

`quality_pass25.py` stopped on its seventeenth edit against a real tree:

    FAIL: README.md  the launch no longer exports a date:
          anchor found 0 times in README.md, expected 1.
          Run passes 1-24 first. Stopping without changes.

**That last line is false, and it is false in every pass in this project.**
`edit()` writes each change as it goes, so by the time the seventeenth edit
failed, the sixteen *code* edits had already been applied and committed to disk.
Nothing was half-written — the code was complete and correct — but the message
said the opposite of the truth at the exact moment someone most needed to know
where they stood. When adding an edit to any of these scripts, remember that the
failure message describes an all-or-nothing behaviour the harness does not have.

The anchor itself missed because a README is prose: it gets hand-edited,
reflowed, and copied between machines, and three exact four-line matches is a
bad way to find a paragraph. Documentation should never be able to stop a code
pass, so the README work moved to `quality_pass25_readme.py`, which matches on
structure — a line that *starts with* `export ASOIA_NOW`, a table row, a fenced
block — reports what it could not find instead of exiting, and prints the text to
paste by hand in that case. `--show` prints the regions it looks for.

Its own first version had the bug it exists to prevent: the detector matched one
exact spelling of `export ASOIA_NOW=`, missed a two-space variant, and then the
verification — which used the same narrow pattern — reported "no exported date is
left" about a file that still had one. **The detector and the check have to be
the same expression, and it has to be a forgiving one.**

### Pass 24 is not in this directory, and it should be

The review layer it built is present and working — `app/review/store.py`, the
review endpoints, the Data & Retrieval tab — but the script that applied it is on
neither machine. It was written, run against the tree, and never moved here, and
there is no copy to recover.

Which makes the point of this directory sharper than any of the notes in it: the
code survived because it was applied, and the *reasoning* is gone. What pass 24
found — `overview()` returning zeros for a missing database rather than an error,
the chunk browser fetching 1,949 vectors to render twenty rows of text, a
serialisability check that used `json.dumps(v, default=str)` and therefore could
never fail, a hardcoded count of nine endpoints where there are ten — survives
only because section 16 of `ENGINEERING.md` was written from the record before it
was lost. Move the script here as part of the pass, not afterwards.

### Pass 26 and the assertion that read the wrong field

Its first conftest called `build_dataset` directly and inherited the closed-cache
bug — `Cannot operate on a closed database`. Worse was the replacement assertion:
`"error" not in r` for a healthy lookup. A healthy **not-found** result carries
*both* `found: False` and an `error` describing what was not found, so the
assertion was testing something the API never promised. The discriminator is
`found`; `error` is explanatory text that can accompany a correct answer.

### Pass 27 put the audit trail in the event log, and the agent stopped working

`events` is the repair-order lifecycle log: every row is parsed through the
`EventType` enum and folded into state. Three new type strings for data
corrections took out **seven of the fourteen answer checks** and every read of an
affected repair order:

    ValueError: 'UPDATE_TEXT_EDITED' is not a valid EventType

The docstring in `app/retrieval/edit.py` had already said these were not lifecycle
events. Writing them there anyway is the mistake; `index_audit` is where they live.

Also in pass 27: `MILVUS_URI` is reserved by pymilvus and setting it changed the
library's behaviour underneath us (ours is `ASOIA_MILVUS_URI`), and an unloaded
Milvus collection reads as **empty** rather than erroring — indistinguishable from
a store that was never built.

### Pass 29: renaming a key without grepping for its readers

`stats()` returned `table`; it became `collection`; nothing else was changed, and
the far end raised `KeyError: 'table'`. The check written for it then asserted a
string that appeared in its own explanatory comment, so it passed against broken
code. **A check that matches the prose next to it is not a check** — this is the
third time in this project (pass 30's `embedEtcd.yaml` check, pass 31's `pgrep`
check) and it is always the same shape: asserting a word that the file contains
because the file talks about it.

### Pass 30 and Pass 31: three checks that could not fail

Pass 30 counted `_writes_allowed` and got 5 for four call sites, because the bare
name matches the `def` as well. Pass 31 asserted `"pgrep" not in body` on a script
whose comments explain at length why `pgrep` is wrong. Both now match a *call*
rather than a word.

Pass 31 also had a genuinely non-idempotent edit: the anchor
`*.egg-info/\n*.bak\n` **survives its own replacement**, so it applied cleanly on
every run and left three copies of `run/` in `.gitignore`. An edit whose anchor is
still present afterwards can never be idempotent, however careful its `skip_if`;
that file is written whole now.

### Pass 32 is mostly documentation, and that is the point

The code fix is small — one exit path for `retrieval_trace` so a degraded result
has the same shape as a healthy one. The rest of the pass is the engineering
record for passes 22 to 31, which had fallen ten passes behind while the table
above stopped at 21. A record that lags is a record nobody trusts, and the whole
value of these scripts is that they explain *why* rather than *what*.
