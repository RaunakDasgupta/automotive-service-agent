# Technical reference

How the system is built, as it is. Every statement here was read off the code at
the commit that introduced this file; where a number was measured rather than
read, the source is named. `ENGINEERING.md` is the *history* of how it got here
and why each decision was taken; this is the *reference* — start here, go there
for the reasoning.

| | |
|---|---|
| **What it is** | An agent that turns technician shift updates (typed or spoken) into continuously derived repair-order state, a prioritised handover, and grounded answers to a service manager's questions |
| **Runs on** | One NVIDIA L40S (48 GB) on Brev: three NIM containers, Milvus standalone, the app, observability |
| **Language / runtime** | Python 3.11 or 3.12 (`pyproject.toml`: `>=3.11,<3.13`), SQLite, Gradio, FastAPI |
| **Size** | `app/` ≈ 10,000 lines in 13 packages; 81 unit tests; 7 evaluation benchmarks |

---

## 1. Design

### Two principles

**Compute deterministically, narrate with the model.** Every count, status, date
and figure is computed in Python from the event log. The model never counts,
never infers state, never does arithmetic — it reads language (extraction) and
writes prose (narration of free-text search). This is what makes figures
checkable and citations enforceable.

**Updates are events, not overwrites.** State is *folded* from an append-only
log on every read. There is no stored "current state" to drift from the record;
contradictions are surfaced as conflicts rather than silently clobbered.

### Invariants the code enforces

| invariant | enforced in |
|---|---|
| A figure in an answer appears in a tool result | `check_grounding` (`app/agent/agent.py`); re-implemented independently in `scripts/evaluate.py` and `evals/` |
| A citation resolves to a record that exists | `search_updates` checks ids against the database; `traceability` benchmark |
| Action requests are refused **before** any tool runs | `check_input` (`app/guardrails/rails.py`) at the top of `/ask` and the UI |
| A claim that something did *not* happen is flagged | `check_negations` |
| A release/approval claim in a technician note never reaches a technician | `check_output` (`_unauthorised_claim`) |
| The model does not decide the repair-order state | state is `fold()`; extraction only proposes events, `reconcile()` validates against `LEGAL` transitions |
| An index built with one embedder is not searched with another | `index_meta.json` + `/health` (§6.5) |

### What the model is used for

Exactly two things, both on the local Nemotron Nano 8B NIM:

1. **Extraction** — a technician's free text → the 3 C's JSON (`app/pipeline/extract.py`).
2. **Narration** — prose over `search_updates` results (`app/agent/agent.py`).
   Every *structured* question (state, handover, blocked, shift activity, …) is
   composed in Python and makes **no model call**.

---

## 2. System map

```
                       ┌────────────── Gradio UI :7860 ──────────────┐   ┌── FastAPI :8080 ──┐
 typed / spoken update │ Dashboard · RO · Tech Update · Handover ·   │   │ /ask /updates     │
 manager question  ───►│ Manager Assistant · Data & Retrieval        │   │ /ros /review/* …  │
                       └──────────────┬──────────────────────────────┘   └─────────┬─────────┘
                                      │  same functions, same rails                │
        ┌─────────────────────────────┴────────────────────────────────────────────┘
        │
   WRITE PATH                                              READ PATH
   asr.transcribe ─► extract (LLM) ─► resolve ─► reconcile  check_input ─► plan_for ─► tools ─► compose ─► checks
        │                                  │         │                                  │              (python | LLM)
        │                                  │         ▼                                  │
        │                                  │   events (append-only) ◄── fold() ◄───────┤  SQLite (state, updates, answer_log)
        │                                  │                                            │
        │                                  └── embed (NIM) ──► Milvus :19530 ◄── search ┘  embed → ANN → fuse → rerank (NIM)
        ▼
   diff card                                  NIMs: llm :8000 · embed :8001 · rerank :8002
```

### Ports

| port | service | bound to |
|---|---|---|
| 7860 | Gradio UI | `0.0.0.0` (share link optional) |
| 8080 | FastAPI (`/docs` for OpenAPI) | `API_HOST`, default all |
| 9400 | application `/metrics` (Prometheus client) | all |
| 9401 | NVIDIA DCGM exporter | all (host network) |
| 9090 / 3000 | Prometheus / Grafana | **127.0.0.1** |
| 8101 / 8102 | Attu (Milvus console) / sqlite-web | **127.0.0.1** |
| 19530 / 9091 | Milvus gRPC / health | all |
| 8000 / 8001 / 8002 | LLM / embedding / rerank NIMs | all |
| 8888 | Brev's JupyterLab (not this project's) | all — see `docs/BREV_RUNBOOK.md` |

---

## 3. Data model

### SQLite (`data/generated/service.sqlite`, schema in `app/state/schema.sql`)

One file, no server, WAL mode. Each thread gets its own connection to it
(`app/state/db.py`), validated with `SELECT 1` before reuse.

| table | holds | notes |
|---|---|---|
| `staff` | 50 people: role, skill, shift, team | |
| `ros` | repair orders: vehicle, VIN, pay/wait type, `promised_time`, concern, category | 400 by default |
| `events` | the **append-only log** — `event_id, ro_number, type, at, actor_id, shift, source_update_id, payload` | the source of truth |
| `updates` | technician updates **as written**, plus `ground_truth` (the structure the prose was rendered from) | what is embedded |
| `labour_ops` | 104 operations: flat-rate hours, category, min skill, `safety_critical` | the catalogue `resolve_op` matches against |
| `answer_log` | every answer: question, text, route, composed-by, grounded, tools, citations, warnings, seconds | written by `log_answer`; best-effort, never fails an answer |
| `index_audit`, `index_exclusions` | corrections, exclusions and restores applied to the vector index | written by `app/retrieval/edit.py` |

### Events

Seventeen types (`app/state/events.py`): `RO_OPENED`, `DISPATCHED`,
`UPDATE_POSTED`, `OP_COMPLETED`, `OP_RECOMMENDED`, `OP_PENDING`,
`PARTS_ORDERED`, `PARTS_RECEIVED`, `AUTH_REQUESTED`, `AUTH_GRANTED`,
`AUTH_DECLINED`, `STATE_CHANGED`, `SAFETY_FLAGGED`, `QC_FAILED`,
`MEASUREMENT_TAKEN`, `DTC_RECORDED`, `COMEBACK_LOGGED`. Every event carries
`source_update_id`, which is what makes a derived fact citable.

### Lifecycle (`app/state/transitions.py`)

Thirteen states. `LEGAL` is the transition table below; anything absent is
rejected by the engine and shown to the user rather than applied. The blocking
states are where vehicles actually sit, and where the agent earns its keep by
surfacing them.

```
CHECKED_IN             → DISPATCHED
DISPATCHED             → DIAGNOSING, ESTIMATE_PREPARED, REPAIR_IN_PROGRESS
DIAGNOSING             → ESTIMATE_PREPARED, PARTS_HOLD, REPAIR_IN_PROGRESS
ESTIMATE_PREPARED      → AWAITING_AUTHORISATION
AWAITING_AUTHORISATION → AUTHORISED, DECLINED  ◀ blocking
AUTHORISED             → PARTS_HOLD, REPAIR_IN_PROGRESS
DECLINED               → READY_FOR_DELIVERY, INVOICED
PARTS_HOLD             → AWAITING_AUTHORISATION, REPAIR_IN_PROGRESS  ◀ blocking
REPAIR_IN_PROGRESS     → AWAITING_AUTHORISATION, PARTS_HOLD, QUALITY_CONTROL
QUALITY_CONTROL        → REPAIR_IN_PROGRESS, ROAD_TEST
ROAD_TEST              → REPAIR_IN_PROGRESS, READY_FOR_DELIVERY
READY_FOR_DELIVERY     → INVOICED
INVOICED               → (terminal)
```

### The fold (`app/state/engine.py`)

`fold(events, promised_time)` is a **pure function** over one repair order's
events and returns an `ROSnapshot`: state, per-op status (`COMPLETED` /
`PENDING` / `RECOMMENDED`), parts and availability, DTCs, measurements, safety
flags, conflicts, authorisation, comebacks, and the ids of the events it used.
Derived properties — `hours_booked`, `flat_rate_total`, `proficiency`,
`blocked_on`, `has_open_safety`, `promise_risk(now)` — are computed, never stored.

### The clock (`app/state/clock.py`)

"Now" is resolved in this order: an explicit argument → `ASOIA_NOW` → **the
newest event in the log**. The default means a generated dataset never goes
stale: every time-window question ("this week", "yesterday afternoon",
"overnight") is anchored to the data. `ASOIA_CLOCK=wall` restores the wall
clock. `event_time()` is a different question — the timestamp of a *new* event —
and is not the same answer. `/health` reports which source is in use.

### The dataset (`app/data/`)

Generated by **reverse generation**: the structured record is authored first and
the prose rendered from it (`narrate.py`), so ground truth exists for every
update at no model cost. Seeded (`seed=20260924`); the window ends at "now" at
generation time, so event counts differ between machines even though the
repair-order count (400) is exact. Realism properties — structurally valid VINs
(ISO 3779 check digit), SAE J2012 DTCs, measurement-against-spec safety flags,
trade shorthand — are asserted by `scripts/verify_data.py`.

It generates itself on first start if the database is empty
(`app/state/bootstrap.py`, `ASOIA_AUTOGEN=0` to disable). It does **not** build
the vector index; that costs embedding calls (§6).

---

## 4. The read path: how a question is answered

`app/agent/agent.py: ask()` → `_ask_inner()`; the streaming UI calls the same
`plan_for`.

1. **Input rail** — `check_input` (`app/guardrails/rails.py`): out-of-scope
   vocabulary, prompt injection, and *unauthorised action* requests
   ("order the parts", "close the RO"). `ASKING_ABOUT` lets "which jobs need
   authorisation?" through while "authorise it" is refused. Blocked questions
   never reach a tool.
2. **Routing** — `plan_for`: `plan_keyword` (deterministic) decides. The LLM
   function-calling router (`plan_llm`) exists but is **off by default**
   (`ASOIA_LLM_ROUTER=1`): turning it on is a behaviour change that has never
   been evaluated. A question matching nothing falls to `search_updates`.
3. **Tools** — run in the plan order, ≤ 3 (§4.1). Each returns a dict that
   includes the ids it drew from.
4. **Composition** — `_summarise` picks a per-tool Python renderer
   (`_RENDERERS`). If one exists the answer is **composed in Python**
   (`composed = "python"`) and the model is not called. Only `search_updates`
   has no renderer by design; it goes to the model (`composed = "llm"`) with a
   prompt fitted to that payload (`SYSTEM_SEARCH`).
5. **Narration checks** (model path only): finish-reason `length` is noted; one
   *re-ask* if the answer opens by naming the records ("Notes indicate …"),
   kept only if clean **and** no less cited; a computed **Figures** block is
   appended (`ASOIA_FIGURES`).
6. **Grounding checks** — `check_grounding` (figures and RO references must
   appear in the tool payload; a Python renderer gets no free pass either),
   `check_negations` (no "nothing was reported" claims from absence in the
   records). `Answer.warnings` and `grounded` carry the result.
7. **Record** — `record_answer` (metrics) and `log_answer` (`answer_log`), both
   best-effort.
8. **Output rail — applied by the caller, not by `ask()`.** `/ask` and the UI
   run `check_output` on the returned answer. It blocks one that carries
   grounding warnings, one with no citations (unless empty by construction), and
   one asserting a release or closure nothing computed — the last is how an
   instruction planted in a technician's note is stopped.

An `Answer` carries: `text`, `route` (`keyword`|`llm`), `composed`
(`python`|`llm`), `tool_calls`, `results`, `citations`, `warnings`, `grounded`,
and `compose_notes` (retries discarded, truncation, stale index).

### 4.1 Tools (`app/agent/tools.py`)

| tool | answers |
|---|---|
| `get_ro_state(ro_number)` | derived state of one repair order, with provenance |
| `get_ro_timeline(ro_number, limit)` | updates as written + the events they produced |
| `list_ros(filter, limit)` | `active` · `blocked` · `at_risk` · `safety` · `waiter` · `all` · a state |
| `get_technician_activity(staff_id, days)` | what one person completed, with proficiency |
| `generate_handover(shift)` | safety first, then breached, at-risk, blocked, in-flight |
| `detect_anomalies(days)` | shared part holds, stalled work, comebacks across ROs |
| `diff_ro(ro_number, since_hours)` | what changed on a repair order in a window |
| `search_updates(query, k, ro_number)` | semantic search over update text — the only narrated path |
| `get_op_code_info(op_code)` | a labour operation: hours, category, skill |
| `get_shift_activity(day_offset, shift, view, days, brief)` | who worked / what was worked on, over a day or window |
| `get_intake(days)` | how many vehicles *came in*, and what became of them |

Eleven. The same eleven are registered with the NeMo Agent Toolkit, one function
type each (`app/agent/nat_functions.py`, `app/agent/workflow.yml`), because one
type cannot expose several tools.

### 4.2 Why routing tells arrival, activity and state apart by the *verb*

"How many cars came in this week" (arrival → `get_intake`), "what cars were
worked on yesterday" (activity → `get_shift_activity`) and "how many cars are
blocked" (state → `list_ros`) share the noun. Keying on the noun answered the
first with the wrong tool and ran two tools for the third. The router keys on the
verb and the window; the routing benchmark scores the **exact plan** over 37
questions including those collisions. History: `ENGINEERING.md` §43–44.

---

## 5. The write path: how an update is ingested

`app/pipeline/run.py: run()` — audio **or** text in, applied state change and a
diff card out.

| stage | module | does | model? |
|---|---|---|---|
| ASR | `asr.transcribe` | Parakeet over Riva gRPC (hosted) → editable transcript; never raises, a failure leaves the technician able to type | hosted ASR |
| Extract | `extract.extract` | text → 3 C's JSON (concern / cause / correction, parts, DTCs, measurements, state hint) | LLM |
| Validate | `extract.validate` | every field checked against the catalogue; DTCs not in the SAE set dropped; hours outside (0, 24] rejected; out-of-spec measurement ⇒ `SAFETY_RELATED` | no |
| Resolve | `resolve.resolve_ro`, `resolve_op` | RO from partials / spoken digits; free text → op code, lexical first, embeddings if available; **an ambiguous match becomes a question, not a guess** | embed (optional) |
| Dialog rail | `rails.check_dialog` | force a clarifying question when the update is unclear | no |
| Reconcile | `reconcile.reconcile` | fold current state, detect conflicts — `REPEAT_OP`, `PARTS_CONFLICT`, and the blocking `AUTH_CONFLICT` and `ILLEGAL_TRANSITION` — then emit events | no |
| Diff card | `diffcard.render` | what changed, for the technician to confirm | no |

A dry run reconciles against a copy of the database, so the diff card and
conflict detection run with nothing written (`scripts/test_voice_update.py`).

---

## 6. Retrieval

### 6.1 Store (`app/retrieval/backend.py`)

Milvus, behind one small `MilvusBackend` (`exists`, `create`, `upsert`, `flush`,
`scan`, `get`, `search`, `delete`, `sample_vectors`, `count`, `dim`, `stats`). `scan()` returns rows **without**
vectors and `get()` returns one row **with** its vector — a 1024-float vector is
~8 KB, so listing chunks to read their text used to move megabytes nobody read.

`ASOIA_MILVUS_URI` selects the mode: a file path → embedded Milvus Lite (one
process, exclusive file lock — a **decoy** on a deployed box, see §6.5);
`http://host:19530` → standalone, which is the deployment. Not `MILVUS_URI` —
pymilvus reads that name itself at import and rejects anything but a URL.

### 6.2 Index (`app/retrieval/index.py`)

- **Build** — `build()` joins `updates` with `ros` and `staff`, embeds
  `"{vehicle} | {category} | concern: {concern} | update: {text}"` (so the vector
  carries the job, not just the sentence), batches of 64, one chunk per update.
  Run via **`scripts/build_index.py`**, never a bare `python -c` (§6.5).
- **Search** — embed the query (cached) → ANN top *wide* → optional
  `ro_number` / category filter → **lexical fusion** → rerank to `k`.
- **Lexical fusion** (`ASOIA_HYBRID=1`) — IDF-weighted overlap over the top
  `ASOIA_HYBRID_POOL` (50), combined with the dense order by reciprocal-rank
  fusion (k=60), cut to `ASOIA_RERANK_POOL` (18) before the reranker.
- **Rerank** — `nv-rerankqa-mistral-4b-v3`. If it is unreachable the result is
  the vector order with `rerank_error` set — the same *shape* either way.
- `search_updates()` returns passages + citations, with every cited id checked
  against the database before it leaves.

### 6.3 Editing a store that is derived (`app/retrieval/edit.py`)

`edit_text`, `reindex_one`, `exclude`, `restore`: correct an update's wording and
re-embed its chunk, take a chunk out of the index without deleting the record,
and put it back. Each writes an audit row (`index_audit`). Exposed on the API as
`PATCH/POST /review/chunks/{id}…` and in the Data & Retrieval tab;
`ASOIA_REVIEW_WRITES=0` makes the four endpoints return 403.

### 6.4 Measured quality

From `evals/baseline.json` and the benchmark definitions — not from the code:

| measure | value | note |
|---|---|---|
| recall@6, the question a person asks (complaint **and** car) | **83.3%** | `ENGINEERING.md` §44 |
| recall@6, complaint alone | 49–55% | **ceiling 53.0%**: 400 ROs share 36 complaint texts, so one complaint names ~12 jobs |
| reranker contribution | 41.7% → 49.2% recall@6 over 120 held-out queries | it earns its latency; an earlier 40-query verdict that it did not was a sample artefact |
| wider rerank pool (50) | +7.5 on the tuning set, +0.0 held out | reverted |

### 6.5 The embedder is part of the index

`nv-embedqa-e5-v5` (local) is **1024**-d; `nemotron-3-embed-1b` (hosted) is
**2048**-d. `build()` writes `data/generated/index_meta.json` (`dim`, `rows`,
`embed_model`, `nim_mode`, `built_at`). `/health` and the staleness check
compare it with the embedder the process is configured for and fail with both
model ids and the rebuild command. Row counts and update ids match perfectly
after a mode switch, so this is the only check that catches it. An absent file
is "unknown", never "mismatched".

Two traps the index builder exists to avoid: the application does **not** read
`.env` (`scripts/stack.sh` does), so a bare `python -c` runs with `NIM_MODE` and
`ASOIA_MILVUS_URI` unset and silently builds the embedded decoy with the hosted
embedder; and `NIM_MODE=hosted` skips the local probe entirely, so healthy
containers can sit idle with nothing routed to them.

---

## 7. Model access (`app/nim/client.py`)

One client over three services × two homes. `resolve(service)` →
`(base_url, model_id, mode)`, cached.

| service | local (`NIM_MODE=local`) | hosted |
|---|---|---|
| llm | `nvidia/llama-3.1-nemotron-nano-8b-v1` @ :8000 | `nvidia/nemotron-3-super-120b-a12b` |
| embed | `nvidia/nv-embedqa-e5-v5` @ :8001 (1024-d) | `nvidia/nemotron-3-embed-1b` (2048-d) |
| rerank | `nvidia/nv-rerankqa-mistral-4b-v3` @ :8002 | none exists — vector-only |

- **Mode** — `NIM_MODE` (`local` \| `hosted` \| `auto`, default `auto`), with
  per-service `NIM_MODE_LLM|EMBED|RERANK`. `auto` probes the local NIM and falls
  back. `hosted` **skips the probe**. Model ids are overridable with
  `NIM_MODEL_<SERVICE>_<LOCAL|HOSTED>`; the hosted catalogue retires models on
  its own schedule (two were retired underneath this project), so ids are
  configuration, not code.
- **Rate limit** — token bucket, `NIM_RPM` (38/min; the hosted free tier is ~40).
- **Timeouts** — `ASOIA_NIM_TIMEOUT` (120 s read budget). A **read timeout is not
  retried** — the server already has the request, and four retries once turned
  one slow question into eight minutes. Connect errors are retried with backoff.
- **Guided JSON decoding is off** (`ASOIA_NIM_GUIDED_JSON=0`). `response_format:
  json_object` made one router call take 37.5 s and return malformed JSON where
  the same prompt without it took 0.2 s and was usable. Both JSON consumers
  already tolerate prose around the object.
- **Switchyard** (`app/routing/switchyard.py`, `ASOIA_SWITCHYARD=on`, default
  off) — a loopback routing proxy in front of the LLM: nano local, the 120B
  hosted on escalation (`configs/switchyard.toml`). If its config is broken it
  disables itself and the NIM is used directly.

---

## 8. Guardrails (`app/guardrails/`)

Two layers, deliberately.

**Python rails (always on)** — `rails.py`: `check_input` (out-of-scope,
injection, unauthorised action), `check_dialog`, `check_output`. These are
regexes, kept narrow on purpose: each broadening was driven by an attack the
evaluator found getting through, and each is paired with a legitimate set that
must still pass — a refusal rail that blocks real work is worse than none.

**NeMo Guardrails** (`nemo.py`, `ASOIA_NEMO_RAILS=off|shadow|on`, default `off`)
— prompt-based `self check input` / `self check output` rails evaluated by the
local nano NIM (`config/config.yml`, `prompts.yml`; `rails.co` documents the
domain policy). `shadow` runs them beside the patterns after the answer has gone
and counts agreement in `asoia_rail_shadow_total` — `nemo_only_block` is the
case the patterns let through. `on` makes the colang verdict authoritative.
There is intentionally **no grounding flow**: grounding is checked
deterministically, and a model judging its own grounding would be weaker.

**Known limit**: an instruction arriving *inside a technician's note* is never
seen by an input rail — the note is data, not a question. It is caught on the way
**out** (`check_output` blocks a release claim relayed from a note), not on the
way in, and a note can still steer what the model *says*, only not what a
technician is allowed to be told. `scripts/test_injection.py` demonstrates both
halves and says which is the model and which is the rail.

---

## 9. HTTP API (`app/api/server.py`)

FastAPI on `:8080`; `/docs` serves OpenAPI. Same functions and same rails as the UI.

| method & path | does |
|---|---|
| `GET /health` | database, NIM endpoints, clock source, index staleness; `status: degraded` when any is wrong. Does not need the NIMs up |
| `POST /ask` | answer a question (input rail → agent → output rail) |
| `POST /updates` | one technician update through extraction → resolution → reconciliation |
| `GET /ros`, `/ros/{ro}`, `/ros/{ro}/timeline`, `/ros/{ro}/diff` | the shop floor, one RO, its history, what changed |
| `GET /handover`, `/anomalies`, `/shift`, `/staff/{id}` | handover, patterns, a day's activity, one technician |
| `GET /tools` | the tool specs |
| `GET /review/overview` · `events` · `event-types` · `ros/{ro}/fold` · `updates` | the evidence: counts, the log, a fold beside its inputs |
| `GET /review/index` · `chunks` · `chunks/{id}` · `retrieval` · `answers` | the vector store, a real two-stage search trace, answers and what they cited |
| `PATCH /review/chunks/{id}` · `POST …/reindex` · `…/exclude` · `…/restore` | the four edit operations (403 when `ASOIA_REVIEW_WRITES=0`) |
| `GET /review/chunks/{id}/history` · `GET /review/edits` | the edit audit trail |

The API and the UI are separate processes, so Prometheus counters are
**per-process**: traffic must go through the API on :8080 for the exporter on
:9400 to see it.

---

## 10. User interface (`app/ui/gradio_app.py`)

Six tabs, each with a stable id (`dashboard`, `ro`, `update`, `handover`,
`assistant`, `data`).

| tab | what it does |
|---|---|
| Dashboard | KPI tiles; the "needs a decision" table, each row saying why; cross-RO patterns; per-technician activity |
| Repair Order | derived state **beside** the update history as written |
| Technician Update | structured logging, and voice / free text → extraction → diff card; shows what the RO already says first, so nothing is logged twice |
| Shift Handover | MORNING / AFTERNOON brief, safety first |
| Manager Assistant | grounded Q&A with citations; guardrails both ways; streams the narrated path |
| Data & Retrieval | seven panes — overview, event log, fold, updates & corrections, edit log, retrieval trace, answers. Only *updates & corrections* writes |

`ASOIA_UI_TAB=<id>` opens the app on a chosen tab. **Switching tabs in the
browser** puts Gradio 6.15's frontend into a Svelte reactive loop
(`effect_update_depth_exceeded`, ~15/s, never stops) that pins a core and
stops the page answering automation; a fresh load on any tab is clean. It is
not fixable from this repo, so treat a switched-to tab as one that may need a
reload, and see `docs/OPERATING.md`. `scripts/capture_screenshots.py` never
switches — it starts a second copy of the app already open on each tab.

`SHARE=1` publishes a `gradio.live` URL with **no login** — by decision
(`ENGINEERING.md` §30). The module does not read `GRADIO_AUTH`.

---

## 11. Observability

### Metrics (`app/obs/metrics.py`) — thirteen series

Each exists because something it would have caught was once shipped.

| series | type | labels | catches |
|---|---|---|---|
| `asoia_answers_total` | counter | compose, route, grounded | the share composed in Python, and how |
| `asoia_answer_seconds` | histogram | compose | end-to-end latency, buckets fitted to 2 ms–10 s |
| `asoia_tool_calls_total` | counter | tool | which tools actually ran |
| `asoia_llm_calls_total` | counter | purpose | the headline claim — structured questions make **zero** model calls — as a graph |
| `asoia_compose_fallbacks_total` | counter | reason | compose notes: discarded retries, errors (the panel is titled *Compose notes (retries discarded)*; non-zero is the citation guard working) |
| `asoia_grounding_warnings_total` | counter | kind | a renderer deriving a figure |
| `asoia_rail_blocks_total` | counter | rail | a correct answer the rail blocks is still a failed answer |
| `asoia_answers_truncated_total` | counter | — | narrations cut at `max_tokens` |
| `asoia_nim_seconds` | histogram | service | NIM latency |
| `asoia_nim_errors_total` | counter | service, cause | failed NIM calls |
| `asoia_rail_shadow_total` | counter | agreement | colang vs patterns |
| `asoia_updates_total` | counter | outcome | ingestion outcomes |
| `asoia_build_info` | gauge | component | 1 when running |

A labelled counter is emitted only once incremented, so a healthy zero is
*absent*, not `0` — the Grafana panels wrap those queries in `or vector(0)`.
`compose` records the path that **finished**: an answer that called the model,
timed out and fell back to Python counts as Python, so a failing LLM pushes the
Python share *up*.

### Stack

`scripts/start_observability.sh up` runs Prometheus (scrape 10 s; jobs `asoia`
:9400 and `dcgm` :9401), Grafana with the provisioned dashboard
`configs/grafana/dashboards/asoia-dashboard.json` (11 panels, uid `asoia`) and
the **NVIDIA DCGM exporter** (19 GPU series) — all CPU/host-network containers
costing no VRAM, Prometheus and Grafana bound to loopback. Grafana runs with
anonymous admin *because* it is loopback-only.

### Traces and store consoles

`ASOIA_TRACE=file` writes ATOF spans of every tool and model call through NeMo
Relay (`app/obs/trace.py`, off by default). `scripts/stores.sh` runs **Attu**
(:8101) and **sqlite-web** (:8102), loopback only, read-write, outside the
agent's own UI. `scripts/stack.sh stores` prints which store is actually
serving and the `ssh -L` command.

---

## 12. Configuration

The application does **not** read `.env`; `scripts/stack.sh` and `scripts/_env.py`
do. Anything that touches the app from a shell must load it first.

| variable | default | effect |
|---|---|---|
| **Models** | | |
| `NVIDIA_API_KEY` (`NGC_API_KEY`) | — | required for hosted calls and NGC pulls; `.env`, never committed |
| `NIM_MODE` | `auto` (`.env.example`: `local`) | `local` \| `hosted` \| `auto`; changing it changes the embedder |
| `NIM_MODE_LLM` `_EMBED` `_RERANK` | `NIM_MODE` | per-service override |
| `NIM_MODEL_<SVC>_<LOCAL\|HOSTED>` | per table in §7 | model id override |
| `NIM_RPM` | `38` | hosted rate limit |
| `ASOIA_NIM_TIMEOUT` | `120` | read budget, seconds |
| `ASOIA_NIM_GUIDED_JSON` | `0` | `1` restores `response_format: json_object` |
| `ASOIA_SWITCHYARD` | `off` | `on` routes the LLM through the proxy |
| `ASOIA_SWITCHYARD_CONFIG` / `_ROUTE` | `configs/switchyard.toml` / default route | |
| `ASR_GRPC_SERVER` `ASR_FUNCTION_ID` `ASR_USE_SSL` `ASR_LANGUAGE` `ASR_BASE_URL` | NVCF Parakeet, `en-US` | hosted speech-to-text |
| `TTS_ENGINE` `TTS_VOICE` `TTS_FUNCTION_ID` `TTS_GRPC_SERVER` `TTS_USE_SSL` `PIPER_MODEL` | `auto`, Magpie EN-US | test-speech synthesis only |
| **Data and clock** | | |
| `ASOIA_DB` | `data/generated/service.sqlite` | |
| `ASOIA_NOW` | newest event | pin "now" |
| `ASOIA_CLOCK` | — | `wall` uses the wall clock |
| `ASOIA_AUTOGEN` | `1` | `0` never generates a dataset on start |
| `ASOIA_GEN_ROS` / `ASOIA_GEN_DAYS` | `400` / `14` | generated dataset size |
| **Retrieval** | | |
| `ASOIA_MILVUS_URI` | `data/generated/milvus.db` (embedded) | `.env.example`: `http://localhost:19530` |
| `ASOIA_MILVUS_COLLECTION` | `updates` | |
| `ASOIA_INDEX_META` | `data/generated/index_meta.json` | build sidecar |
| `ASOIA_RERANK` | `on` | `off` takes the vector top-k |
| `ASOIA_RERANK_POOL` | `18` | |
| `ASOIA_HYBRID` / `ASOIA_HYBRID_POOL` | `1` / `50` | lexical fusion |
| **Answering** | | |
| `ASOIA_DETERMINISTIC` | `1` | `0` forces the model to narrate everything (the A/B) |
| `ASOIA_LLM_ROUTER` | `0` | `1` lets the model route when keywords match nothing |
| `ASOIA_NARRATION_MAX_TOKENS` | `1600` | |
| `ASOIA_META_RETRY` | `1` | the single re-ask (§4) |
| `ASOIA_FIGURES` | `1` | append the computed Figures block |
| `ASOIA_NEGATION_RAIL` | `1` | |
| `ASOIA_STREAM` | `1` | `0` renders only rail-gated text |
| `ASOIA_NEMO_RAILS` | `off` | `off` \| `shadow` \| `on` |
| `ASOIA_LOG_ANSWERS` | `1` | `0` stops recording what each answer cited |
| `ASOIA_REVIEW_WRITES` | `1` | `0` makes the edit endpoints 403 |
| **Process and ports** | | |
| `PORT` / `API_PORT` / `API_HOST` | `7860` / `8080` / — | UI / API |
| `SHARE` | `0` | `1` publishes a `gradio.live` link, no login |
| `ASOIA_UI_TAB` | `dashboard` | tab the UI opens on |
| `ASOIA_METRICS` / `ASOIA_METRICS_PORT` | `1` / `9400` | |
| `ASOIA_TRACE` / `ASOIA_TRACE_DIR` | `off` / default dir | `file` writes ATOF spans |
| `PROM_PORT` `GRAF_PORT` `DCGM_PORT` `DCGM_IMAGE` | `9090` `3000` `9401` | observability |
| `ASOIA_ATTU_PORT` / `ASOIA_SQLITEWEB_PORT` | `8101` / `8102` | store consoles |
| `ASOIA_SSH_ALIAS` | — | fills in the `ssh -L` line |
| **Tooling** | | |
| `ASOIA_TEST_DB` | — | `keep` makes the tests use the real database |
| `ASOIA_CAPTURE_UI_PORT` `ASOIA_PROM_URL` `ASOIA_GRAF_URL` `ASOIA_ATTU_URL` `ASOIA_SQLW_URL` | `7869`, loopback | `scripts/capture_screenshots.py` |
| `OPENSHELL_GATEWAY` | — | `scripts/openshell_gateway.py` |

---

## 13. Evaluation and testing

| layer | command | needs | what it establishes |
|---|---|---|---|
| unit | `pytest tests/ -q` | nothing — 81 tests, no GPU, no network, a throwaway database | state engine (folding, illegal transitions, conflicts), pipeline (JSON tolerance, resolution, validation), routing, grounding, the rails |
| gate | `scripts/verify_answers.py` | the database | per question: composed by the expected path; **no** LLM call on a deterministic path (proved by passing `ask()` a chat function that raises); every number in the text is in the payload; every citation is in the payload; no negation claims; actions refused before tools. Exits non-zero |
| score | `scripts/evaluate.py` | nothing (`--with-llm` adds retrieval + narration) | routing over **37** labelled questions, grounding over 35 deterministic paths, traceability, refusal over 4 attacks and the legitimate set |
| benchmarks | `scripts/eval_standard.py` | the agent's answers | **seven NeMo Evaluator BYOB benchmarks** (`evals/asoia_byob.py`): routing, grounding, traceability, refusal, tool calls (including derived arguments), accuracy (stated number vs. SQL in `evals/truth.py`, which never imports `app`), relevance |
| loop | `scripts/agent_loop.py status \| fast \| gate \| accept \| relock` | `fast`: nothing; `gate`: the GPU box | scores against `evals/baseline.json`; refuses to print a score if a measure file changed; `accept` adopts a run as the baseline |
| speech | `scripts/test_asr.py`, `test_voice_update.py` | Riva, key | real words in, graded transcript out; figures graded one at a time |
| other | `test_review.py`, `test_injection.py`, `test_trace.py`, `test_switchyard.py`, `audit_stack.py` | varies | review layer, indirect injection, traces, router, declared-vs-installed |

Two things keep the evaluation honest:

- **Two implementations of the shared measures.** The benchmarks and
  `scripts/evaluate.py` are written independently so that a disagreement is
  reported rather than averaged; `cross_check` fails the run on one.
- **The measure is locked.** `evals/harness.lock` checksums six files that turn
  behaviour into a number — `evals/asoia_byob.py`, `evals/truth.py`,
  `scripts/evaluate.py`, `scripts/eval_standard.py`,
  `scripts/make_eval_dataset.py`, `scripts/timings.py`. `agent_loop.py` refuses to
  score while one differs, because an agent optimising against a scorer
  eventually edits the scorer. Changing one is a deliberate act for a human
  (`agent_loop.py relock`).

**Committed baseline** (`evals/baseline.json`, taken 2026-10-06 on the GPU box
against the local NIMs): routing 100% · plan exact 100% · grounding 100% ·
traceability 100% (26.2 citations/answer) · refusal-before-tools 100% ·
answer accuracy 100% with **94.6% of rows scored** (the other two are free-text
searches with no correct number to check — the ceiling) · relevance 100% ·
latency: worst Python path 64 ms, narrated path 3.7 s with 3 model calls.

**Floors** the loop enforces: routing 90%, grounding / traceability / refusal
100%, accuracy coverage 90%.

---

## 14. Deployment and operations

| | |
|---|---|
| Bring a box up, in order, with a gate per phase | `docs/BREV_RUNBOOK.md` |
| Restart, refresh after code or data change, reboot behaviour, logs | `docs/OPERATING.md` |
| One command up/down | `scripts/stack.sh up \| status \| stores \| logs \| restart \| down` (`--share`, `--nims`) |
| NIM containers | `scripts/start_nims.sh pull \| run \| health \| logs \| stop` — 12 + 5 + 24 GB budget; **29,963 MiB measured resident** of 46,068 MiB on the L40S |
| Vector store | `scripts/start_milvus.sh up` (`--restart unless-stopped`) |
| Pack for a box without GitHub | `scripts/make_tarball.sh` (refuses an archive containing `.env`, `*.bak` or AppleDouble entries) |
| Public URLs for the UIs | `scripts/publish.sh up \| urls \| down` (cloudflared quick tunnels, **no auth**) |

After a reboot the containers return (`--restart unless-stopped`); the API, UI
and sqlite-web are `setsid` processes and do not — run `stack.sh up`.

`scripts/` is the operating surface; `scripts/make_notebooks.py` regenerates the
eight notebooks (deterministic; the committed ones match its output), and
`scripts/make_architecture_diagram.py` / `make_architecture_deck.js` regenerate
`docs/architecture.drawio` and `docs/architecture-deck.pptx`.

---

## 15. Security model

- **Secrets** — `.env` is gitignored (with `.env.*` and `*.bak*`, because dated
  backups once carried real key material). `make_tarball.sh` refuses to pack
  one. The key is never printed. `docker login nvcr.io` leaves a second
  plaintext copy in `~/.docker/config.json`.
- **Network** — Prometheus, Grafana, Attu and sqlite-web bind loopback. The UI,
  API, Milvus and the NIMs bind all interfaces: on Brev, keep those ports off
  the public internet, and note Brev's own JupyterLab on :8888 runs with an
  **empty token and password**.
- **No authentication** on the UI, API, share link or `publish.sh` tunnels. By
  decision, recorded in `ENGINEERING.md` §30: anyone with a URL can use every
  tab, including Technician Update, which **writes** to the event log, and every
  model call spends the box's NVIDIA key. Treat a published link as published;
  take it down and rotate the key afterwards.
- **Write surface** — event log (`/updates`, Technician Update), the vector
  index (`/review/chunks/*`), and sqlite-web / Attu, which can run arbitrary SQL
  and drop a collection.

---

## 16. Known limitations

Stated because each is measured, not because they are comfortable.

- **Retrieval recall is not high.** 83.3% recall@6 on the realistic query,
  against a 60% floor that is met; on the complaint alone the ceiling is 53%.
  A wrong repair order can be the top hit.
- **The Agent Toolkit workflow selects and executes all eleven tools but
  composes badly** — correct tool 18/18, executed 18/18, a good answer 3/18. The
  native path (`app/agent/agent.py`) is the one that answers.
- **Speech-to-text is hosted** and the only remaining hosted dependency in the
  answer path; there is no Riva container in this deployment.
- **Hosted inference is not equivalent.** No reranker exists; the chat models
  are reasoning models whose output is not reproducible at `temperature=0`; the
  baselines are local-NIM baselines, so a hosted evaluation run is indicative,
  not comparable.
- **Gradio tab switching** (§10).
- **`compose` flatters a failing model** (§11): the Python share rises when the
  LLM times out.
- **The UI's streaming path repeats the answer sequence instead of calling it.**
  `_ask_streaming` re-implements plan → tools → compose → checks from
  `agent._ask_inner`, with no meta re-ask (text already streamed cannot be
  retracted). It has drifted once — a hard-coded 400-token budget against
  `ASOIA_NARRATION_MAX_TOKENS` — and `verify_answers.py` and the benchmarks
  exercise `ask()`, not the streaming path.
- **Not verifiable off the GPU box:** NeMo Guardrails, the Agent Toolkit
  workflow, traces and Switchyard need packages (`nvidia`, `flywheel` extras)
  that the CPU environment does not install.
- **NemoClaw / OpenShell** — a sandbox gateway whose only ingress is browser
  SSO a headless client cannot complete. Listed as blocked, not claimed.

---

## 17. Extending

**Add a tool.** (1) Implement the query in `app/analytics/queries.py` taking
`(con, …, now)`; (2) add the typed wrapper to `app/agent/tools.py` and to
`TOOLS` and `SPECS`; (3) give it a Python renderer in `agent._RENDERERS` — or it
will be narrated by the model; (4) teach `plan_keyword` the phrasing and add the
question to `scripts/evaluate.py: ROUTING` with its SQL truth in
`scripts/make_eval_dataset.py` / `evals/truth.py` (the coverage floor fails a
run otherwise); (5) register a function type in `app/agent/nat_functions.py` and
`workflow.yml`; (6) re-lock the measure files (`agent_loop.py relock`), because
you changed them on purpose.

**Add an event type.** `EventType` → handle it in `engine.fold` → emit it in
`reconcile` and the generator → add the transition to `LEGAL` if it moves state.

**Add a rail.** Pattern in `rails.py` **plus** a legitimate-question set in
`scripts/evaluate.py` that must still pass — the second half is what stops a
rail from becoming a refusal machine.

**Change the embedder.** Set `NIM_MODE`/`NIM_MODEL_EMBED_*`, then rebuild with
`scripts/build_index.py`; `/health` fails until you do.

**Change the schema.** Edit `app/state/schema.sql`; regenerate the dataset
(`python -m app.data.generate`) and rebuild the index. There are no migrations:
the data is derived, not precious.

---

## 18. Document map

| document | read it for |
|---|---|
| `README.md` | what this is, how to run it |
| **`docs/TECHNICAL.md`** | this file — how it is built |
| `docs/BREV_RUNBOOK.md` | bringing up a GPU box, in order, with a gate per phase |
| `docs/OPERATING.md` | day to day: restart, refresh, reboot, the model's real speed |
| `docs/EXAMPLES.md` | what it actually answers, from a live run, with timings |
| `docs/screenshots/README.md` | what each captured frame shows, and how it was taken |
| `docs/VOICE-UPDATE-FORMAT.md` | what to say so an update is captured accurately |
| `docs/PASS_INDEX.md` | the 61 numbered passes: what each addressed, and where it is recorded |
| `docs/architecture.drawio`, `docs/architecture-deck.pptx` | the architecture as seven diagrams / nine slides, generated |
| `ENGINEERING.md` | the history: each defect, how it was found, what the measurement said |
| `AGENT_LOOP.md` | the brief for a coding agent working on this repository |
