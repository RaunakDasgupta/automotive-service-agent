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

## When the model is slow — read this before raising the timeout

Measured on `capstone-asoia`, 2026-10-09: the LLM NIM took **~43 seconds to
generate 16 tokens**, three times running, and a 400-token generation did not
finish in 300 seconds. That is about 0.37 tokens/sec from an 8B FP8 engine on an
L40S that should manage 50–100.

Sampling `nvidia-smi` every 3s during one of those calls:

```
t+ 3s … t+33s   0 %, 29963 MiB, 2520 MHz
t+36s           9 %
```

**The GPU is idle for the first ~35 seconds.** So this is not slow generation,
it is a stall before any compute starts. The NIM's own log says what is
happening in that window:

```
Compiling FSM index for all state transitions:   0%|  | 0/23 [00:00<?, ?it/s]
```

That is guided/structured decoding building a finite-state machine, on the CPU,
per request. The profile selected is correct — `tensorrt_llm-l40s-fp8-tp1-pp1-
throughput` — so this is not a CPU fallback or a wrong engine.

**Not yet fixed, and not yet root-caused past this point.** Worth checking
before anything else: whether the app is asking for JSON/guided decoding on
calls that do not need it, and whether the NIM can cache a compiled FSM between
requests.

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

`ASOIA_NIM_TIMEOUT` sets the budget (default 120s). On a box where the model is
in the state described above, a lower value — say 45 — makes narration fail fast
and fall back to the deterministic composer, which keeps the app responsive. It
treats the symptom; the FSM stall is the disease.
