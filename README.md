# Automotive Service Operations Intelligence Agent

Voice and text shift updates → continuously derived repair-order state, a
prioritised shift handover, and a grounded agent that answers a service manager's
questions about the shop.

Built on the NVIDIA stack and **designed to run on one NVIDIA Brev L40S (48 GB)**:
three self-hosted NIMs — **Nemotron Nano 8B**, **`nv-embedqa-e5-v5`** (1024-d) and
**`nv-rerankqa-mistral-4b-v3`** — with **Milvus** standalone for the vector store,
**Parakeet ASR** over Riva gRPC, **NeMo Agent Toolkit**, **NeMo Guardrails**, and
Prometheus / Grafana / **DCGM** for observability.

**With `NIM_MODE=local` nothing in the answer path calls a hosted model**, and
that is deliberate. Two hosted models this project depended on were retired
underneath it — the embedder, then `llama-3.1-nemotron-nano-8b-v1`, which has
answered `HTTP 410 Gone` since 2026-08-26 and took every narrated answer with it
while the deterministic ones carried on passing. A pinned container does not
expire. Speech-to-text is the one hosted dependency left; there is no Riva
container in this deployment.

> **Where to read next.** How it is built: [`docs/TECHNICAL.md`](docs/TECHNICAL.md).
> Bringing a box up: [`docs/BREV_RUNBOOK.md`](docs/BREV_RUNBOOK.md). Day to day:
> [`docs/OPERATING.md`](docs/OPERATING.md). What it answers:
> [`docs/EXAMPLES.md`](docs/EXAMPLES.md). The full list is [at the end](#documentation).

## Two principles

**Compute deterministically, narrate with the LLM.** Every count, status, date and
figure is computed in Python from the event log. The model reads language
(extraction) and writes prose (narration of free-text search); it never counts,
never infers state, never does arithmetic. That is what makes figures checkable
and citations enforceable.

**Updates are events, not overwrites.** State is folded from an append-only log,
so there is a complete audit trail and contradictions are surfaced rather than
silently clobbered.

## What it does

| | |
|---|---|
| **Ingest** | A technician types or *speaks* an update. ASR → extraction to the 3 C's (Concern / Cause / Correction) → resolution to real repair orders and operation codes → reconciliation against the lifecycle → a **diff card** of exactly what changed. Ambiguity becomes a question, not a guess |
| **Derive** | Repair-order state is *folded* from events on every read: blocked, at risk, safety-critical, promise breached, hours against flat rate |
| **Hand over** | A MORNING / AFTERNOON brief, safety first, then breached, at-risk, blocked — each with a next action |
| **Answer** | A manager asks in plain English. Structured questions are composed in Python in tens of milliseconds with **no model call** (0.00–0.11 s in `docs/EXAMPLES.md`); free-text search and an RO's timeline are the paths that reach the model. Every figure and citation is checked against the tool payload; action requests are refused before any tool runs |
| **Show its evidence** | The Data & Retrieval tab and `/review/*` expose the event log, the fold beside its inputs, the vector index, a real two-stage retrieval trace, and every answer with what it cited |

## Architecture

Fourteen NVIDIA components: thirteen built and running, and the fourteenth —
the NemoClaw / OpenShell sandbox gateway — blocked by a platform fault, listed as
blocked rather than claimed (`ENGINEERING.md` §34). In
[`docs/architecture.drawio`](docs/architecture.drawio) the colour carries that
argument: filled green is a served NVIDIA model or NVIDIA infrastructure, an
outline is an NVIDIA framework, plain is this project's own code and the
datastores, and a dashed outline is present but not integrated.

| Component | What it does here | Status |
|---|---|---|
| **NIM — LLM** | Nemotron Nano 8B. Extraction (prose → JSON) and narration of search results. Nothing else | local, `:8000` |
| **NIM — Embedding** | `nv-embedqa-e5-v5`, 1024-d: updates, and op-code resolution | local, `:8001` |
| **NIM — Reranking** | `nv-rerankqa-mistral-4b-v3` reorders Milvus candidates | local, `:8002` |
| **Riva — Parakeet ASR** | Speech to text for spoken shift updates, over gRPC | hosted |
| **Riva — Magpie TTS** | Synthesises the spoken updates the ASR leg is tested with | hosted |
| **NeMo Agent Toolkit** | The agent as a toolkit workflow over the same 11 tools, one function type each; this NIM writes tool calls as text, so a provider shim lifts them into `tool_calls` | runs — tools execute 18/18, answers 3/18 (`ENGINEERING.md` §42) |
| **NeMo Guardrails** | Prompt-based `self check input` / `self check output` rails, evaluated by the local nano NIM | `ASOIA_NEMO_RAILS` (`off` \| `shadow` \| `on`) |
| **NeMo Curator** | Six-stage curation; the sixth quarantines the injection vector before indexing | `scripts/curate.py` |
| **NeMo Evaluator** | Seven BYOB benchmarks in Evaluator's own result schema — routing, grounding, traceability, refusal, tool calls, accuracy, relevance | `evals/asoia_byob.py` |
| **NeMo Relay** | Per-stage trace spans — which tool, which model, how long | `ASOIA_TRACE` |
| **NeMo Switchyard** | Loopback routing proxy: nano local, `nemotron-3-super-120b` hosted on escalation | off by default |
| **NVIDIA DCGM** | GPU telemetry: utilisation, framebuffer, power, temperature, clocks (19 series) | `:9401` |
| **Milvus** | The vector store, standalone on the box | `:19530` |
| **NemoClaw / OpenShell** | Would add a containment boundary and a sandboxed `compute` tool | **blocked** — `ENGINEERING.md` §34 |

Prometheus and Grafana (13 application series, an 11-panel provisioned dashboard)
are the glue around these and are not counted as NVIDIA components.

The architecture is drawn in two generated artefacts, so a wrong port or count is
a one-line fix and a re-run:

```bash
python3 scripts/make_architecture_diagram.py                 # docs/architecture.drawio, stdlib only
node scripts/make_architecture_deck.js docs/architecture-deck.pptx   # needs: npm install pptxgenjs
```

[`docs/architecture.drawio`](docs/architecture.drawio) is seven pages (system map,
write path, read path, component inventory, deployment, data model, lifecycle),
uncompressed XML so it diffs. [`docs/architecture-deck.pptx`](docs/architecture-deck.pptx)
is ten slides: the process in business terms (animated, builds itself on entry), seven of architecture and two of usage built from
[`docs/screenshots/`](docs/screenshots/README.md).

## Deploy on NVIDIA Brev

Target: **one L40S, 48 GB.** The three NIMs are budgeted at ~41 GB (12 + 5 + 24);
**29,963 MiB** was measured resident of 46,068 MiB.

**The authority is [`docs/BREV_RUNBOOK.md`](docs/BREV_RUNBOOK.md)** — ordered,
copy-pasteable, a gate at the end of each phase. This is the shape of it. The
code goes across as a **tarball**, not a clone:

```bash
# on your machine
bash scripts/make_tarball.sh ~/asoia.tar.gz       # refuses to pack .env, *.bak or macOS metadata
scp ~/asoia.tar.gz <instance>:/home/ubuntu/

# on the box
cd /home/ubuntu && tar -xzf asoia.tar.gz && cd automotive-service-agent
cp .env.example .env && chmod 600 .env && $EDITOR .env    # key; NIM_MODE=local

bash scripts/brev_bootstrap.sh            # 1. pulls FIRST - 30-90 min

curl -LsSf https://astral.sh/uv/install.sh | sh          # 2. while it downloads
uv venv --python 3.11 .venv && uv pip install --python .venv -e ".[dev]"
.venv/bin/python -m app.data.generate
.venv/bin/python -m pytest tests/ -q

bash scripts/start_nims.sh run            # 3. when the pulls finish
bash scripts/start_nims.sh health         #    gate: all three OK

bash scripts/start_milvus.sh up           # 4. the index, at the right width
.venv/bin/python scripts/build_index.py --check
.venv/bin/python scripts/build_index.py

bash scripts/stack.sh up                  # 5. API, UI, stores, observability
.venv/bin/python scripts/verify_answers.py --with-llm
```

The notebooks in `notebooks/` cover the same ground and are the intended route
through it; the runbook says which Jupyter kernel to pick (Brev's JupyterLab runs
from `~/.venv`, not this project's, and listens on `0.0.0.0:8888` with an empty
token).

Three things in that order are load-bearing, and each has gone wrong here:

**`NIM_MODE` must be `local`, and `.env.example` ships that.** `hosted` does not
merely prefer the hosted endpoints — it **skips the local probe entirely**, so all
three containers can be healthy while every request still leaves the box. You pay
for the GPU and use none of it. Nothing fails; `stack.sh status` notes it as
*"3 local NIM container(s) up and NOTHING routes to them."*

**Set it before building the index, not after.** The embedder changes width with
the mode — 1024 local, 2048 hosted — so switching later means building twice. If
you do switch, `/health` fails naming both model ids and the rebuild command
rather than letting every search break on a dimension error.

**Anything that touches the app must load `.env` first.** The application does
not read it — `scripts/stack.sh` does. A bare
`python -c 'from app.retrieval.index import build; …'` runs with `NIM_MODE` and
`ASOIA_MILVUS_URI` unset and can silently build the *embedded* Milvus Lite decoy
with the *hosted* embedder and report success. Use `scripts/build_index.py`, which
loads `.env` and prints the store and embedder it used; a script of your own does
`sys.path[:0]=['.','scripts']; import _env`.

### State that looks after itself

- **The clock follows the data.** "Now" defaults to the newest event in the log,
  so a generated dataset never goes stale and time-window questions ("this week",
  "overnight") keep working. `ASOIA_NOW` pins it; `ASOIA_CLOCK=wall` restores the
  wall clock.
- **The dataset generates itself if there is none** — 400 repair orders, ~10k
  events and ~1.9k updates in about 0.1 s. The repair-order count is exact; the
  others are not (the window ends at generation time), and a fresh box will
  differ from the last one without anything being wrong. It does **not** build the
  vector index; that embeds every update through a NIM and is run once, above.
- **A stale index says so.** `build()` records the embedder it used in
  `data/generated/index_meta.json`; `/health`, the review Overview and any
  affected answer report a mismatch or a data/index disagreement, because
  otherwise it produces confident, well-formed answers citing records that no
  longer exist.

## Running it

```bash
bash scripts/stack.sh up                 # Milvus + API :8080 + UI :7860 + stores + observability
bash scripts/stack.sh up --nims          # ... and the three local NIMs
bash scripts/stack.sh up --share         # ... and a public gradio.live link (NO login)
bash scripts/stack.sh status             # what is up, and is it answering
bash scripts/stack.sh stores             # which store is serving, and its admin UIs
bash scripts/stack.sh logs ui            # ui | api | milvus
bash scripts/stack.sh restart            # down, then up with the same options
bash scripts/stack.sh down [--nims]      # stop what it started
```

| port | | port | |
|---|---|---|---|
| 7860 | Gradio UI | 9090 / 3000 | Prometheus / Grafana (loopback) |
| 8080 | HTTP API, `/docs` | 8101 / 8102 | Attu / sqlite-web (loopback) |
| 9400 / 9401 | app metrics / DCGM | 19530 | Milvus |

Each service is waited for rather than slept at, and `status` reads the store as
well as the ports. After a reboot the containers come back (`--restart
unless-stopped`); the API, UI and sqlite-web do not — run `stack.sh up`.

**`--share` publishes a `gradio.live` URL with no login**, by decision
(`ENGINEERING.md` §30). The URL is world-reachable, the Technician Update tab
writes to the event log, and every model call spends this box's NVIDIA key; a
random subdomain is not a credential. Take it down with `stack.sh down` and
rotate the key afterwards.

Other entry points: `scripts/start_api.sh --detach`, `scripts/start_observability.sh
up`, `scripts/start_milvus.sh up`, `scripts/publish.sh up` (cloudflared tunnels to
the UIs, also with no auth).

## Using it

### The UI — six tabs

| Tab | What it does |
|---|---|
| Dashboard | KPI tiles, a "needs a decision" table with the reason on every row, cross-RO patterns, per-technician activity |
| Repair Order | Derived state beside the update history as written |
| Technician Update | Structured logging, **plus voice / free text → extraction → diff card**; shows what the RO already says first, so nothing is logged twice |
| Shift Handover | Prioritised: safety, breached, at-risk, blocked, each with a next action |
| Manager Assistant | Grounded Q&A with citations; guardrails on input and output; the narrated path streams |
| Data & Retrieval | Seven panes: overview, event log, fold, updates & corrections, edit log, retrieval trace, answers. Six are read-only; *updates & corrections* writes — editing an update re-embeds its chunk so the record and the index stay in step. Store statistics live in Attu (`:8101`) and sqlite-web (`:8102`), not here |

`ASOIA_UI_TAB` (`dashboard`, `ro`, `update`, `handover`, `assistant` or `data`)
opens the app on a given tab. Switching tabs in the browser puts Gradio 6.15's frontend into a
reactive loop that pins a core — see `docs/OPERATING.md`.

### The API

`/health`, `/ask`, `/updates`, `/ros…`, `/handover`, `/anomalies`, `/shift`,
`/staff/{id}`, `/tools` and a `/review/*` family (the evidence and the four edit
operations). `/ask` runs the input rail before any tool and the output rail
before returning. The full table is in [`docs/TECHNICAL.md`](docs/TECHNICAL.md#9-http-api-appapiserverpy).

### The notebooks — one per application segment

Each is independently runnable, in the shape **Purpose → Prerequisites → Config →
Execute → What you should see**. All logic lives in `app/`; notebooks orchestrate
and narrate. They are generated by `scripts/make_notebooks.py`.

| Notebook | Segment | GPU |
|---|---|---|
| `00_setup` | Key check, NIM containers, health, VRAM report | pulls |
| `01_data` | Generate the dataset; VIN / op-code / DTC realism checks | No |
| `02_state_engine` | RO lifecycle, event folding, illegal transitions, safety flags | No |
| `03_ingest_pipeline` | **Centrepiece.** Audio → transcript → 3 C's extraction → reconcile → diff card | Yes |
| `04_retrieval` | Milvus index, vector search vs reranked | Yes |
| `05_agent` | Tools, routing, grounded answers with citations | Yes |
| `06_guardrails` | The input, grounding and output rails firing | No |
| `07_app` | Launch Gradio for the live demo | No |

## Data realism

Modelled on how service departments actually work, not on a toy schema: work keyed
to **repair orders** (`RO-26-08871`); **structurally valid VINs** (17 characters,
correct check digit, I/O/Q excluded); the real lifecycle — check-in → dispatch →
diagnosis → estimate → **awaiting authorisation** → **parts hold** → repair → QC →
road test → delivery → invoiced; technician notes in the **3 C's**; genuine SAE
J2012 DTCs; measurements against spec (a rotor at 22.8 mm against a 23.0 minimum
drives the safety flag); trade shorthand (`C/S`, `R&R`, `LF/RF/LR/RR`, `NLA`,
`TSB`); proficiency as flat-rate earned ÷ actual hours.

Generated by **reverse generation** — the structured record is authored first and
the prose rendered from it, so ground truth exists for every update at zero model
cost.

## Tests and verification

```bash
.venv/bin/python -m pytest tests/ -q              # 81 tests, no GPU, no network
.venv/bin/python scripts/verify_answers.py        # 14 checks against the real data; non-zero on failure
.venv/bin/python scripts/evaluate.py              # scores: routing, grounding, traceability, refusal
.venv/bin/python scripts/agent_loop.py fast       # the model-free subset against the committed baseline
.venv/bin/python scripts/timings.py --repeat 3    # latency per stage, per question
.venv/bin/python scripts/test_voice_update.py     # the voice pipeline, stage by stage
```

The 81 tests cover the state engine (folding, illegal transitions, conflicts), the
pipeline (JSON tolerance, resolution, validation), the agent (routing, grounding)
and the rails. `verify_answers.py` is the one that matters before a demo: per
question it asserts the answer was composed by the expected path, that a
deterministic path made **no** model call (proved by handing `ask()` a chat
function that raises), that every number and citation is in the tool payload
(re-implemented independently of the rail, so a bug in one cannot hide a bug in the
other), that nothing claims something did *not* happen, and that action requests
are refused before any tool runs. Run it with `--with-llm` on the box — without
it the one check that exercises retrieval, reranking and narration together is
`skipped` and still counts as a pass.

`evaluate.py` is the scores rather than the gate: routing over **37** labelled
questions, grounding re-implemented independently over 35 deterministic paths,
refusal against 4 attacks *and* the legitimate set (a rail that blocks real work
is worse than none) and, with `--with-llm`, retrieval recall@k, MRR and the rerank
gain. The seven NeMo Evaluator benchmarks are run by `scripts/eval_standard.py`;
`evals/harness.lock` checksums the files that turn behaviour into a number.
The measured baseline is in `evals/baseline.json` and summarised in
[`docs/TECHNICAL.md`](docs/TECHNICAL.md#13-evaluation-and-testing).

## Configuration

`NIM_MODE`, `NVIDIA_API_KEY` and `ASOIA_MILVUS_URI` are the three that matter;
`.env.example` ships a working set. The full reference — every variable, its
default and what it does — is [`docs/TECHNICAL.md` §12](docs/TECHNICAL.md#12-configuration).

| variable | default | |
|---|---|---|
| `NVIDIA_API_KEY` | — | required; `.env`, never committed |
| `NIM_MODE` | `auto` (`local` as shipped) | `local` requires the containers; `hosted` **skips the probe**; changing it changes the embedder, so rebuild the index |
| `NIM_MODE_{LLM,EMBED,RERANK}` | `NIM_MODE` | per-service override; `NIM_MODE_RERANK=local` is the useful one — there is no hosted reranking model |
| `ASOIA_MILVUS_URI` | embedded file | `http://localhost:19530` for standalone; unset locks the store to one process |
| `ASOIA_NOW` / `ASOIA_CLOCK` | newest event / — | pin "now" / `wall` |
| `ASOIA_DETERMINISTIC` | `1` | `0` forces the model to narrate everything — the A/B for a demo |
| `ASOIA_NEMO_RAILS` | `off` | `shadow` runs the NeMo rails beside the patterns and counts disagreement |
| `ASOIA_NIM_TIMEOUT` | `120` | read budget, seconds; a read timeout is not retried |
| `ASOIA_UI_TAB` | `dashboard` | the tab the UI opens on |

## Without a GPU — a degraded fallback

**This is not how the project is meant to run.** It is what you fall back to when
there is no box, and it exists because that happened: both GPU instances were
deleted mid-project and this was the only way to keep the stack serving.

Everything except the models is containers, so the sequence above still applies
with three changes: `NIM_MODE=hosted`, skip the NIM pull and run, and build the
index at **2048-d** (the hosted embedder's width).

| | local NIMs | hosted |
|---|---|---|
| Reranking | `nv-rerankqa-mistral-4b-v3` | **none exists** — vector-only retrieval |
| Embedding | `nv-embedqa-e5-v5`, 1024-d | `nemotron-3-embed-1b`, **2048-d** |
| Chat model | `llama-3.1-nemotron-nano-8b-v1`, pinned container | `nemotron-3-super-120b-a12b`, a **reasoning** model |
| Narrated answer | 3–4 s end to end (`docs/EXAMPLES.md`) | 28–46 s (measured 2026-10-07) |
| Same question twice | identical | **not reproducible** |

The last row matters most: the hosted endpoint does not return identical output at
`temperature=0` the way a pinned container does, so the baselines in
`evals/baseline.json` — taken against the local NIMs — make a hosted evaluation
run **indicative, not comparable**. Do not record one as a regression or an
improvement.

## Repository layout

```
app/
  agent/       typed tools, router, composition, grounding; NeMo Agent Toolkit registration
  analytics/   deterministic queries over the event log, and cross-RO insights
  api/         FastAPI service: the agent, ingestion, analytics and the review layer
  data/        catalog, scenarios, VIN, prose renderer, generator
  guardrails/  Python rails + NeMo Guardrails config (config.yml, prompts.yml, rails.co)
  nim/         one client over local NIMs and build.nvidia.com; limiter, timeouts
  obs/         Prometheus metrics; ATOF traces through NeMo Relay
  pipeline/    ASR, extraction, resolution, reconciliation, diff card
  retrieval/   Milvus backend, index build and search (fusion + rerank), edit operations
  review/      read-only views of everything an answer stands on, plus the answer log
  routing/     Switchyard routing proxy
  state/       event log, lifecycle, fold engine, clock, SQLite, bootstrap
  ui/          Gradio app
configs/       prometheus scrape config, provisioned Grafana dashboard, Milvus, Switchyard
docs/          technical reference, runbook, operating notes, examples, screenshots, diagrams
evals/         NeMo Evaluator benchmarks, SQL ground truth, committed baseline, harness lock
notebooks/     one per application segment (generated)
scripts/       stack and NIM lifecycle, index builder, verification, evaluation, the
               improvement loop, capture and packaging tools
tests/         81 unit tests - no GPU, no network
AGENT_LOOP.md  the brief for a coding agent working on this repository
ENGINEERING.md the record: each defect, how it was found, what the measurement said
```

## Known limits

Stated up front because each is measured.

- **Retrieval is the weakest link.** Recall@6 is 83.3% on the question a person
  asks (complaint *and* car) and is capped near 53% on the complaint alone,
  because 400 repair orders share 36 complaint texts.
- **The Agent Toolkit workflow picks and executes the right tool every time but
  composes poorly** (3/18 good answers). The native path in `app/agent/agent.py`
  is what answers.
- **No authentication** on the UI, the API, the share link or the publish
  tunnels, by decision — keep the box's ports off the public internet.
- **Gradio tab switching** pins a core in the browser (`docs/OPERATING.md`).

## Documentation

| | |
|---|---|
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | the technical reference: design, data model, read and write paths, retrieval, API, observability, configuration, evaluation, security, limits |
| [`docs/BREV_RUNBOOK.md`](docs/BREV_RUNBOOK.md) | bringing up a GPU box, in order, with a gate per phase |
| [`docs/OPERATING.md`](docs/OPERATING.md) | restart, refresh, reboot behaviour, the model's real speed |
| [`docs/EXAMPLES.md`](docs/EXAMPLES.md) | what it actually answers, captured from a live run on an L40S |
| [`docs/screenshots/`](docs/screenshots/README.md) | the running stack, and how each frame was taken |
| [`docs/VOICE-UPDATE-FORMAT.md`](docs/VOICE-UPDATE-FORMAT.md) | what to say so a spoken update is captured accurately |
| [`docs/PASS_INDEX.md`](docs/PASS_INDEX.md) | the 61 numbered passes: what each addressed, and where it is recorded |
| [`ENGINEERING.md`](ENGINEERING.md) | the history behind every decision |
| [`AGENT_LOOP.md`](AGENT_LOOP.md) | the improvement-loop brief |
