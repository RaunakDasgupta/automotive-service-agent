# Bringing up a fresh Brev box, at full capacity

Target: **one L40S 48GB**. Everything below is manual and in order. Each phase
ends in a **gate** — a command whose output tells you whether to continue. The
gates matter more than the commands: three of the four ways this deployment has
gone wrong produced a stack that looked healthy and answered questions badly.

What "full capacity" means here, against the laptop fallback:

| | on the box | on a laptop (hosted) |
|---|---|---|
| chat model | `llama-3.1-nemotron-nano-8b-v1`, local container | `nemotron-3-super-120b-a12b` — a **reasoning** model, spends tokens before answering |
| embedder | `nv-embedqa-e5-v5`, **1024-d** | `nemotron-3-embed-1b`, **2048-d** |
| reranker | `nv-rerankqa-mistral-4b-v3` | **none exists** — hosted has no reranking model, so stage two is skipped |
| GPU telemetry | DCGM exporter → Grafana | nothing to export |
| reproducible | yes, pinned container at temperature 0 | no |
| `evals/baseline.json` | **comparable again** | indicative only |

Last verified **2026-10-08**: all five container images below are still
pullable from `nvcr.io`, including the LLM — its *hosted* endpoint was retired
2026-08-26, but the container image was not withdrawn with it.

---

## 0. Connect

```bash
brev shell <instance-name>      # or the ssh alias Brev prints
nvidia-smi                      # gate: one L40S, 48GB, nothing else using it
docker ps                       # gate: docker answers without sudo
```

If `docker ps` needs sudo, stop here and fix that first — every script below
runs docker unprivileged.

---

## 1. Clone, and write `.env`

```bash
git clone https://github.com/RaunakDasgupta/automotive-service-agent.git
cd automotive-service-agent
cp .env.example .env
```

Now edit `.env`. **Three lines, and the second one is the whole point of the
box:**

```bash
NVIDIA_API_KEY=nvapi-...
NIM_MODE=local                              # .env.example ships `hosted` — change it
ASOIA_MILVUS_URI=http://localhost:19530
```

`NIM_MODE=hosted` does not merely prefer hosted, it **skips the local probe
entirely**. Leave it as shipped and all three containers can be running and
healthy while every request still goes to the hosted endpoints — you pay for the
GPU and use none of it. `stack.sh status` is the only thing that will tell you,
and only as a note: *"3 local NIM container(s) up and NOTHING routes to them."*

Setting it to `local` now, before anything is built, is deliberate: it means the
index gets built once, at the right width. See phase 4.

```bash
chmod 600 .env
grep -c . .env                  # gate: the file has the lines you just wrote
```

---

## 2. Start the pulls FIRST — this is the long pole

```bash
bash scripts/brev_bootstrap.sh          # == scripts/start_nims.sh pull
```

30–90 minutes including TRT engine builds. It pulls three images and **reads
each exit code**; a failure now fails the command and prints the last lines of
each log, rather than reporting success and leaving you a container that crashes
twenty minutes later.

```
nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1:latest
nvcr.io/nim/nvidia/nv-embedqa-e5-v5:latest
nvcr.io/nim/nvidia/nv-rerankqa-mistral-4b-v3:1.0.2      <- NOT :latest
```

That last pin is load-bearing. That repository publishes only versioned tags —
its tag list is `1.0.0`, `1.0.1`, `1.0.2` and nothing else — so `:latest` fails
with `manifest unknown`. Only one of the three pulls was ever affected, which is
why it survived as long as it did.

Watch it: `tail -f /tmp/pull_*.log`

**Gate:** the command exits 0 and prints `Pulls complete`.

---

## 3. While that downloads — everything that needs no GPU

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.11 .venv
uv pip install --python .venv -e ".[dev,nvidia,flywheel,voice,admin]"
```

`requires-python` is `>=3.11,<3.13`; 3.11 and 3.12 both work. The extras are
independent and each is worth having on this box:

| extra | what it turns on |
|---|---|
| `dev` | pytest, ruff, jupyterlab — **`pytest` is in here**, not in the base install |
| `nvidia` | NeMo Guardrails + NeMo Agent Toolkit + `ChatNVIDIA` |
| `flywheel` | NeMo Relay, Evaluator, Switchyard |
| `voice` | `nvidia-riva-client`, spoken updates |
| `admin` | sqlite-web, for the store admin UI |

NeMo Curator is **not** here on purpose — it installs into its own
`.venv-curator` because it pulls ray and torch, 6 GB you do not want in the
serving environment. `uv` does not put `pip` inside the venv, so add anything
later the same way: `uv pip install --python .venv <pkg>`.

Build the dataset and run the tests — neither needs a model:

```bash
.venv/bin/python -m app.data.generate
.venv/bin/python -m pytest tests/ -q
bash scripts/stack.sh stores provision        # one-time: attu image + sqlite-web
```

`data/generated/` is gitignored in full, so a fresh clone has **no corpus** —
this step is not optional. The generator is seeded: 400 repair orders, ~10.9k
events, ~1.9k updates in about 0.1s, in a window ending now. The clock follows
the newest event in the log, so the dataset never goes stale and there is no
date to pin.

**Gate:** pytest is green, and
`.venv/bin/python -c "import sqlite3;print(sqlite3.connect('data/generated/service.sqlite').execute('select count(*) from ros').fetchone())"`
returns 400.

---

## 4. When the pulls finish — run the NIMs

```bash
bash scripts/start_nims.sh run
bash scripts/start_nims.sh logs llm      # first start builds TRT engines: 10-20 min
bash scripts/start_nims.sh health
```

The reranker starts first, deliberately: it is the largest and the most likely
to fail on a crowded GPU. The LLM is capped — both `NIM_GPU_MEMORY_UTILIZATION`
(vLLM) and `NIM_KVCACHE_PERCENT` (TRT-LLM) are set to `0.25`, because which one
applies depends on the profile the container picks, and on an L40S it picks
TRT-LLM FP8 — so the vLLM variable alone was silently doing nothing. Budget,
carried forward from the previous box rather than re-measured: LLM ~12GB + embed
~5GB + rerank ~24GB ≈ 41GB of 48.

If the LLM refuses to start, raise `LLM_GPU_FRAC` to `0.30`; if the **reranker**
fails, lower it to `0.20`, or switch to the 1B reranker (`~4GB`, one commented
line in `scripts/start_nims.sh`).

**Gate — all three, no exceptions:**

```
  OK      llm     :8000
  OK      embed   :8001
  OK      rerank  :8002
```

A NIM answering `/v1/health/ready` with 200 before its engine build finishes is
normal; `health` is the authority, not the log.

---

## 5. The vector store, and the index at the right width

```bash
bash scripts/start_milvus.sh up
.venv/bin/python scripts/build_index.py --check
```

`--check` prints the store and the embedder it would use, and compares them
against what the index on disk was built with. **Read it before building.** On a
fresh box it should say:

```
  store     http://localhost:19530   (server)
  embedder  nvidia/nv-embedqa-e5-v5   (local)
  on disk   nothing recorded - no index, or one built before this was tracked
```

If `store` says `(embedded)`, this process did not read `.env` — it is about to
build into the Milvus Lite decoy at `data/generated/milvus.db` while the API
serves from the standalone server. If `embedder` says `hosted`, `NIM_MODE` did
not take effect, or the containers are not up yet and `auto` fell back.

Then build:

```bash
.venv/bin/python scripts/build_index.py
```

**Do not use a bare `python -c`.** The application does not read `.env` —
`stack.sh` does — so `python -c 'from app.retrieval.index import build; ...'`
runs with `ASOIA_MILVUS_URI` and `NIM_MODE` unset and silently builds the wrong
store with the wrong embedder, reporting success either way. That one-liner used
to be printed in seven places, including the dimension-mismatch error itself.
`scripts/build_index.py` loads `.env` first and prints what it used.

**Gate:** the recorded line says `nv-embedqa-e5-v5` and `"dim": 1024`.

---

## 6. The stack

```bash
bash scripts/stack.sh up          # NIMs already running - no --nims needed
bash scripts/stack.sh status
bash scripts/stack.sh stores
```

One command brings up Milvus, the API, the UI, Attu, sqlite-web, Prometheus,
Grafana and — because `nvidia-smi` exists on this box and did not on the laptop
— the **DCGM exporter**, so the GPU panels fill in for the first time.

`up` deliberately does **not** touch `NIM_MODE`, and `--nims` does not point the
app at the containers it starts. That is a dimension, not an oversight: see
phase 1.

| | port | |
|---|---|---|
| UI | 7860 | Gradio |
| API | 8080 | `/health`, `/metrics` on 9400 |
| Grafana | 3000 | anonymous, dashboard `asoia` |
| Prometheus | 9090 | scrapes 9400 (app) and 9401 (DCGM) |
| Attu | 8101 | Milvus admin |
| sqlite-web | 8102 | system of record, read-write |
| Milvus | 19530 | 9091 is its own web UI |
| NIMs | 8000/8001/8002 | llm / embed / rerank |

**Everything binds `127.0.0.1`.** Grafana runs anonymous with no login form,
sqlite-web is read-write, and both are reachable only over the forward below.
Do not publish these ports.

---

## 7. Prove it

```bash
curl -s localhost:8080/health | python3 -m json.tool
.venv/bin/python scripts/verify_answers.py --with-llm   # 14 checks, non-zero on failure
.venv/bin/python scripts/audit_stack.py           # declared vs actually installed
.venv/bin/python scripts/timings.py --json /tmp/profile.json   # latency + tokens
```

`--with-llm` matters here. Without it one of the fourteen checks — the semantic
one, *"has anyone seen a whistling noise on a Passat"* — reports
`skipped (needs --with-llm and the NIMs up)` and **still counts as a PASS**. It
is the only check that exercises retrieval, reranking and narration together, so
on this box it is the one you came for. The other thirteen are deterministic
Python paths and two refusals, and they pass on a laptop too.

In `/health`, the two fields to read are `index_embed_model` and
`configured_embed_model`. They must name the same model. If they differ,
every search fails on a dimension mismatch and `health` says so with the fix —
row counts and update ids match perfectly after a mode switch, so nothing else
notices.

`audit_stack.py` measures rather than infers, which matters for the three
components that are imported behind `try/except` and are therefore absent in a
way that looks like working software: NeMo Agent Toolkit, NeMo Guardrails,
Parakeet ASR.

### The improvement loop is live again

`evals/baseline.json` was taken against the **local** NIMs. Hosted inference is
not reproducible at temperature 0; a pinned container is. So on this box, and
only on this box, eval numbers are comparable to the baseline and a regression
means something:

```bash
.venv/bin/python scripts/agent_loop.py status
.venv/bin/python scripts/agent_loop.py fast        # quick measure
.venv/bin/python scripts/agent_loop.py gate        # the three agreements
```

`gate` passes only on all three: suite exit 0, cross-check `agree`, and no
regression against the baseline — where a **missing** metric counts as a
regression. `evals/harness.lock` checksums the six measure files and `fast`/
`gate` refuse to print a score while one differs, so the loop cannot improve its
score by editing the scorer. Full brief: `AGENT_LOOP.md`.

---

## 8. Reach it from your laptop

One forward for everything:

```bash
ssh -N \
  -L 7860:127.0.0.1:7860 -L 8080:127.0.0.1:8080 \
  -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 \
  -L 8101:127.0.0.1:8101 -L 8102:127.0.0.1:8102 \
  <your-brev-alias>
```

Then open the `http://127.0.0.1:...` links directly. Set `ASOIA_SSH_ALIAS` in
`.env` on the box and `scripts/stack.sh stores` prints this command for you,
filled in.

A public `gradio.live` link instead — note that the Technician Update tab
**writes** to the event log, so this needs `GRADIO_AUTH` in `.env` first:

```bash
bash scripts/stack.sh restart --share
```

A share tunnel cannot be added to a process that is already serving, which is
why this is `restart` and not `up`.

---

## When it goes wrong

| symptom | cause | fix |
|---|---|---|
| `manifest unknown` on one pull | reranker pinned to `:latest`, which does not exist | already fixed; `start_nims.sh` pins `1.0.2` |
| all three NIMs healthy, GPU idle | `NIM_MODE=hosted` — the probe is skipped | `NIM_MODE=local` in `.env`, then **restart the stack**; `resolve()` is cached per process |
| every search fails, index looks fine | embedder changed width; rows and ids still match | `.venv/bin/python scripts/build_index.py` |
| index built but API sees nothing | built into Milvus Lite, not the server | `build_index.py --check` — if it says `(embedded)`, `.env` was not read |
| row count 0 on a freshly built index | Milvus counts only sealed segments | harmless; `build()` flushes, and `query` returns rows regardless |
| reranker won't start | VRAM | `LLM_GPU_FRAC=0.20`, or the 1B reranker |
| `No module named pytest` | base install only | `uv pip install --python .venv -e ".[dev]"` |
| Grafana GPU panels empty | DCGM exporter didn't start | `bash scripts/start_observability.sh status` |
| time-window questions return nothing | the clock was pinned to a stale moment | unset `ASOIA_NOW`; the clock follows the newest event by default |

## Shutting it down

```bash
bash scripts/stack.sh down --all      # stack, stores, observability, and the NIMs
```

Without `--all` the NIM containers are left running on purpose — they cache TRT
engines, and rebuilding those costs 10–20 minutes. `data/milvus/` survives too;
delete it by hand to start the store clean.
