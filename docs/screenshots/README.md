# Screenshots

**Mixed vintage. Read the date column before believing one.**

`scripts/capture_screenshots.py` drives the stack and re-takes these, so they can
be refreshed rather than redrawn by hand. It captures the four non-Gradio UIs
reliably; Chromium hangs on four of the six Gradio tabs, headless or headed, so
those are still taken by hand.

| | | captured | shows |
|---|---|---|---|
| 01 | Dashboard | **2026-10-09** | 400 live ROs filtered to safety / blocked / at-risk / waiting, each row saying why |
| 02 | Repair Order | **2026-10-09** | state folded from the event log, beside the updates as written |
| 03 | Technician Update | 2026-10-07 | dictate or type an update, then the diff card |
| 04 | Shift Handover | 2026-10-07 | the changeover brief, safety first |
| 05 | Manager Assistant | 2026-10-07 | a cited answer with the tools it used |
| 06 | Data & Retrieval | 2026-10-07 | points at the store consoles rather than embedding them |
| 07 | Prometheus targets | **2026-10-09** | `asoia` **and `dcgm` both up** — real GPU telemetry |
| 08 | Prometheus tool calls | **2026-10-09** | `rate(asoia_tool_calls_total[5m])*60`, six series, `list_ros` peaking ~10/min |
| 09 | Grafana | **2026-10-09** | **88.3% composed in Python**, ungrounded 0, cut short 0, rail blocks 0, and the latency step-down when the guided-JSON fix landed |
| 10 | Attu collections | **2026-10-09** | `updates`, **Loaded**, approx count 1,690 |
| 11 | Attu schema | **2026-10-09** | **`vector` FloatVector(1024), AUTOINDEX(COSINE)**, entity count 1,690, 13 fields |
| 11b | Attu data | **2026-10-09** | real rows — `pk`, the **1024-float vectors themselves**, `update_id`, `ro_number` |
| 12 | sqlite-web | **2026-10-09** | the system of record, 8 tables, 12,266 rows |

**Eight of thirteen are from the GPU box with the local NIMs and the latency
fixes in.** 03–06 are still 2026-10-07 on hosted inference: Chromium hangs on
those four Gradio tabs — headless, headed under xvfb, with fake media devices,
on an idle box — so they are not automated. Everything else re-captures with
`scripts/capture_screenshots.py`.

## Capturing them under load, which is the whole point

**08, 09 and 10 were wrong twice before they were right.** The first re-take
showed the stack up and the application idle: `asoia_tool_calls_total` returned
*Empty query result* and every Grafana application panel read *No data*.

The reason is worth writing down. Traffic was driven by calling
`app.agent.agent.ask()` from a standalone Python process. Prometheus counters
are **per-process**, and the exporter Prometheus scrapes on :9400 belongs to the
API server — so those calls incremented counters in a process that then exited,
and the dashboard never saw them. Driving the same questions through
`POST /ask` on :8080 put 101 series on the exporter and filled every panel.

So: **exercise the app through the API, then wait for two or three scrapes, then
capture.** A screenshot taken straight after `stack.sh up` shows an idle
dashboard no matter how healthy the box is.

## What these now show

- **09** — ungrounded answers **0** and answers cut short **0** (both read
  *No data* before, see below), answer latency split by compose path, NIM
  latency per service, six tools, and the GPU tracking the semantic queries.
- **08** — `rate(asoia_tool_calls_total[5m]) * 60` as a graph over 30 minutes,
  six series: `list_ros` dominates and `search_updates` is the rare one.
- **11** — `updates (1,690)`. It replaces a shot captioned `FloatVector(2048)`,
  the hosted embedder's width; the store is 1024-d now. The Schema tab's field
  list had not loaded when the frame was taken, so the dimension itself is not
  visible — the file is named for what it shows, not what was wanted.

## Still from 2026-10-07, on a Mac with hosted inference

**03, 04, 05 and 06.** Chromium hangs on those four Gradio tabs, headless or
headed under xvfb, so they are not automated. They show the right screens, taken
against the hosted models rather than the local NIMs.

## A healthy zero is not "No data"

Four panels read *No data* no matter how well the stack was running:
**Ungrounded answers**, **Silent fallbacks**, **Answers cut short** and
**Guardrail blocks**. Prometheus returns an empty vector for a counter whose
labelled child has never been created, and `asoia_grounding_warnings_total` has
no child precisely *because* nothing was ever ungrounded. Grafana renders that
identically to the exporter being down.

The dashboard now wraps those queries in `(...) or vector(0)`, so a healthy zero
says **0**. That is a dashboard fix, not a metric change - the underlying
counters are untouched.

## What this run surfaced

Driving real load put **42 `asoia_nim_errors_total{cause="ReadTimeout",
service="llm"}`** on the exporter while the LLM NIM itself stayed healthy.

The cause was a cascade started by a retry bug, not a slow model. `_post`
retried **every** exception four times, so one `POST /updates` whose extraction
exceeded the 120s budget occupied the LLM for up to eight minutes; everything
queued behind it timed out too, and each of those was retried four times. Fixed
in `b9a80f9`: read timeouts now fail on the first attempt.

**The model itself is fast.** Measured on an idle box: 100 tokens in 1.39s, 215
in 2.99s, a real semantic question end to end in 3.52s. An earlier note here
claimed ~0.37 tok/s and blamed guided-decoding FSM compilation — that was
measured while a load generator of mine was still running, and was wrong. See
`docs/OPERATING.md`.

## Attu was never broken — the route was wrong

Three capture attempts produced an Attu frame with headers and no rows, and it
looked like an Attu or Milvus fault. It was neither. The automation navigated to

    #/databases/default/collections/updates        <- renders the shell, tabs stay empty

when the route Attu actually uses is

    #/databases/default/updates/overview           <- loads the collection into state

The first one renders the page frame and the tab bar, issues no further API
calls, and leaves every tab showing *No Data*. Opening Attu in a real browser and
clicking through is what exposed it: the link in the collections table points at
`.../updates/overview`, not `.../collections/updates`.

Everything else was healthy the whole time. Milvus reports the collection
**Loaded**, 1,690 rows, `vector` as **FloatVector dim 1024**, index AUTOINDEX /
COSINE with 1690 of 1690 indexed and 0 pending, and `query()` returning rows.
Attu's own API was returning the full schema with its fields populated —
`/collections/details` answered 200 in 349ms with `schema.fields` intact. The
frontend simply had no collection in state to render.

| | shows |
|---|---|
| `10-attu-collections.jpg` | the collections table: `updates`, **Loaded**, approx count 1,690 |
| `11-attu-schema-1024.jpg` | **`vector` FloatVector(1024)`, AUTOINDEX(COSINE)**, Loaded, replica 1, entity count 1,690, all 13 fields |
| `11b-attu-data.jpg` | real rows — `pk`, the **1024-float vectors themselves**, `update_id`, `ro_number`, `staff_id`, timestamps |

The deck also carries the rerank evidence as text, from a live query: for
*"whistling noise"*, vector-only search returns knocking and vibration passages,
and the reranker returns blowing-noise passages — a different set of repair
orders entirely.

## The Python-share stat was measuring the wrong thing

It read 87.5% in one capture and 100% in the next, and 0% while idle. All three
were "correct" for what the query said and none described the system.

    100 * sum(rate(asoia_answers_total{compose="python"}[5m]))
        / clamp_min(sum(rate(asoia_answers_total[5m])), 0.0001)

Two faults. **A 5-minute rate** reflects only the last handful of questions, so
the number swung with whatever was asked most recently, and `clamp_min` turned
an undefined ratio into a confident **0%** whenever nothing was happening -
indistinguishable from the deterministic path having collapsed.

And `compose` is the path that **finished**, not the path that was chosen. An
answer that called the model, timed out and fell back to Python was counted as
Python, so **a failing LLM pushed the number up**. With 48 `ReadTimeout`s on the
exporter at the time, that was not hypothetical.

Measured over the whole run instead: **92.5% of 80 answers finished on the
Python path; 86.25% were Python by design** once the 5 fallbacks are removed.

The panel is now titled *Composed in Python by design (%)*, computes
`increase(...[1h])` with fallbacks subtracted and no clamp, and reads a steady
94.5% instead of swinging between 0 and 100.

The Python share in the captured frame is **flattered by the timeout cascade**
that was running at the time: model calls that timed out fell back to Python and
were counted as Python. That cascade is fixed in `b9a80f9`, and the model
answers a real question in 3.52s, so a frame captured now would show a truer
split.
