# Running it day to day

Every command here is typed in the **Brev instance terminal**, from the repo:

```bash
cd ~/automotive-service-agent
```

## What survives a reboot and what does not

This is the thing worth knowing before anything else, because half the stack
comes back by itself and half does not.

| | survives | why |
|---|---|---|
| Milvus, Prometheus, Grafana, DCGM, Attu | **yes** | `--restart unless-stopped` |
| the three NIM containers | **yes** | same, though the TRT engines reload |
| the public tunnels | **yes, with NEW URLs** | the containers restart; trycloudflare hands out a different hostname each time |
| the API and the UI | **no** | `setsid` processes, not containers |
| sqlite-web | **no** | a process, not a container |

So after a reboot the data and the models are there, and nothing is serving.

## Cold start, after the box has been stopped and started

```bash
bash scripts/start_nims.sh health
```

Gate: all three `OK`. If the containers did not come back, `bash
scripts/start_nims.sh run` and wait — a restart reloads the engines rather than
rebuilding them, so it is minutes, not the first-run 10–20.

```bash
bash scripts/start_milvus.sh up
bash scripts/stack.sh up
bash scripts/stores.sh up
bash scripts/publish.sh up
```

`stack.sh up` brings up the API, the UI, Prometheus and Grafana and prints the
store report. `stores.sh up` adds Attu and sqlite-web. `publish.sh up` starts
the tunnels and prints the new public URLs.

## Refresh the app after changing code

```bash
bash scripts/stack.sh restart
```

That stops and restarts the API and the UI only. It is what you want for any
change under `app/`, and it is also what you want after editing `.env` —
`app/nim/client.py` caches the resolved endpoint per process, so a mode change
does nothing until the process restarts.

The tunnels keep pointing at the same ports, so **the public URLs do not change**
across a `stack.sh restart`.

## Refresh after the data changes

Regenerating the dataset leaves the vector index describing rows that no longer
exist, and a stale index produces confident, well-formed answers citing records
that are gone. So rebuild it, then restart:

```bash
.venv/bin/python scripts/build_index.py --check
.venv/bin/python scripts/build_index.py
bash scripts/stack.sh restart
```

`--check` prints the store and the embedder before it commits the minutes. It
must say `(server)` and `(local)`; if it says `(embedded)` the process did not
read `.env`, and if it says `(hosted)` the NIMs are not up or `NIM_MODE` is not
`local`.

## Restart the whole thing

```bash
bash scripts/publish.sh down
bash scripts/stack.sh down --all
```

`--all` takes the NIM containers down too, which frees the VRAM and costs a
reload on the way back up. Leave it off to keep them warm. Then do the cold
start above.

## Is it actually working?

```bash
bash scripts/stack.sh status
```

Reads the real index and the resolved models, not the configuration. Then:

```bash
curl -s localhost:8080/health | .venv/bin/python -m json.tool
```

The two fields that matter are `index_embed_model` and
`configured_embed_model` — they must name the same model, or every search fails
on a dimension mismatch. `clock.source` should be `data`.

```bash
.venv/bin/python scripts/verify_answers.py --with-llm
```

Fourteen checks. `--with-llm` matters: without it the one check that exercises
retrieval, reranking and narration together reports `skipped` and still counts
as a pass.

## The public links

```bash
bash scripts/publish.sh urls
```

**The URLs change every time a tunnel container restarts**, so read them rather
than writing them down. There is no authentication in front of any of them — see
the note at the top of `scripts/publish.sh` for exactly what that exposes.

## Logs

```bash
tail -f /tmp/asoia-ui.log            # the UI
tail -f /tmp/asoia-api.log           # the API
bash scripts/start_nims.sh logs llm  # one NIM: llm | embed | rerank
bash scripts/stack.sh logs milvus
```

## One trap, since it has cost time three times

Do not `pkill -f <pattern>` when your own command line contains that pattern —
it matches the shell you are typing in and kills your session. Use the exact
process name, or bracket a letter: `pgrep -f "captu[r]e_screenshots"`.

## The model is not slow — a note on how that was got wrong

An earlier version of this section claimed the LLM NIM managed ~0.37 tokens/sec,
stalled with the GPU idle for 35 seconds, and blamed per-request FSM compilation
from guided decoding. **All of that was wrong, and it is left here because the
mistake is more useful than the conclusion was.**

Measured on an idle box:

| | |
|---|---|
| 16 tokens | **0.22 s** |
| 100 tokens | **1.39 s** |
| 215 tokens | **2.99 s** (~72 tok/s) |
| a real semantic question, end to end through `/ask` | **3.52 s** |

That is what an 8B FP8 engine on an L40S should do.

The 43-second figures were taken **while a six-round load generator was still
running in the background** — my own. I was measuring contention against a
single LLM NIM and reporting it as a model fault. The GPU showing 0% was real
and meant the request was queued, not that compute had stalled. And a plain
request triggers **zero** FSM compiles: `grep -c "Compiling FSM"` on the
container log was unchanged across one, so guided decoding was never in that
path. Only `app/pipeline/extract.py` and one call in `app/agent/agent.py` ask
for `json_mode`.

**Before blaming a component, check nothing of yours is still hammering it.**
`pgrep -f` for your own load scripts first.

### Where the ReadTimeouts actually came from

A cascade, and the retry bug started it. A vague `POST /updates` runs an
extraction through the model. Under load that call exceeded the 120s budget,
and `_post` then retried it **four times** — occupying the LLM for up to eight
minutes for one request. Everything queued behind that timed out too, each of
those retried four times. Hence 48 timeouts from 12 questions.

### What was fixed

`_post` in `app/nim/client.py` retried **every** exception four times, including
read timeouts. A read timeout means the server already has the request and is
working on it, so a retry does not replace that work — it queues a second
generation behind it, and the caller pays `4 × timeout`. At the 120s default
that is **eight minutes for one question**, which is why `POST /updates` looked
like it hung at 240s: it was on its third attempt.

Read, write and pool timeouts now fail on the first attempt with a message
naming the budget and the override. Connect errors are still retried, because
there the request never landed and another attempt is free. Verified: a call
against a 5s budget fails in 5.0s rather than 20s, and records **one**
`asoia_nim_errors_total` instead of four.

`ASOIA_NIM_TIMEOUT` sets the budget (default 120s). With the model answering in
seconds, 120 is generous — the point of the fix is that exceeding it now costs
one timeout instead of four and eight minutes.


## The 40-second question: guided JSON decoding

One question in eight took ~41 seconds while the rest took 0.05s, reproducibly,
every round. Tracing the model calls showed the cost was not narration:

```
"whistling noise"      3.9s   2 calls   2.0s + 1.2s, both max_tokens=1600
"battery flat"        40.8s   3 calls  37.4s + 1.4s + 1.6s
                                       ^^^^^ max_tokens=300, the LLM ROUTER
```

The 300-token call is `plan_llm`, the only thing in the system that passes
`json_mode=True`. Timed directly, same prompt:

| | time | output |
|---|---|---|
| `response_format: json_object` | **37.5 s** | `{ "tools]:[{"` — malformed |
| no `response_format` | **0.2 s** | `{"tools":[{"name": …}]}` — usable |

**187× slower, and the mechanism whose only purpose is to guarantee well-formed
JSON produced the only broken JSON of the two.** The cost is the NIM compiling a
finite-state machine per request, on the CPU, which is why the GPU reads 0%
while a request is in flight. Keyword routing matched the other questions, so
only the fallthrough ever paid for it.

Guided decoding is now off by default — `ASOIA_NIM_GUIDED_JSON=1` restores it.
That question now answers in **3.4s with the same 8 citations**.

### Two things that fix uncovered

**The router emitted argument names the tools do not have.** It returned
`search_updates(q=...)` where the parameter is `query`, so the search ran with
no query, returned nothing, and the answer became "there were no matching
notes" with zero citations. `plan_llm` now validates every planned call against
the tool's own spec — unknown or missing-required args reject the plan, and
keyword routing takes over. The prompt also lists the real parameter names now.

**That router had never run.** Guided decoding made it fail every single time,
so `plan_llm` always returned `None` and keyword routing always won. Every
measurement in this repo, `evals/baseline.json` included, was taken with the
LLM router inert. Fixing the latency switched it on for the first time, and the
first thing it did was route a battery-history question to
`detect_anomalies(days=1)`.

So it is **off by default** (`ASOIA_LLM_ROUTER=1` enables it). Turning it on is
a behaviour change that has never been evaluated, and it should not ride in on
the back of a latency fix. Run `scripts/agent_loop.py gate` first.


## Switching a tab in the browser pins a core

Clicking from one tab to another in the Gradio UI throws
`effect_update_depth_exceeded` — a Svelte reactive loop — about **fifteen times
a second, and it does not stop**. The renderer sits at 102% of a core, the page
answers no further automation (an `evaluate` never returns, and its own timeout
does not fire either), and `Page.screenshot` times out at 60s. Gradio is 6.15.1.

It is the **switch** that does it, not any one tab: a fresh page load on any tab
is clean, with zero page errors. Reproductions of the components involved — the
400-row dataframes, the 200-item filterable dropdowns, the KPI flex strip, the
whole Repair Order tab rebuilt in a toy app — all stay clean, so the trigger
needs the full page and is not something this repo can fix.

What it means in practice:

- **Treat a switched-to tab as a page that needs reloading.** Everything that
  needs the renderer's main thread stops: a scripted click, an `evaluate`, a
  screenshot. A person's clicks need that same thread, so assume the tab is
  unresponsive rather than slow — this was not measured directly, because the
  harness that would measure it cannot reach the page either. A reload is clean.
- **`ASOIA_UI_TAB` opens the app on a chosen tab** (`dashboard`, `ro`, `update`,
  `handover`, `assistant`, `data`), which avoids the switch entirely. Useful on
  a fixed screen — a changeover display wants `handover` — and it is how
  `scripts/capture_screenshots.py` photographs a tab at all: it starts a second
  copy of the app on :7869 already open on that tab and leaves :7860 alone.

```bash
ASOIA_UI_TAB=handover PORT=7861 .venv/bin/python -m app.ui.gradio_app
```
