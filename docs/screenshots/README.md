# Screenshots

**Mixed vintage. Read the date column before believing one.**

`scripts/capture_screenshots.py` drives the stack and re-takes these, so they can
be refreshed rather than redrawn by hand. It captures the four non-Gradio UIs
reliably; Chromium hangs on four of the six Gradio tabs, headless or headed, so
those are still taken by hand.

| | | captured | against |
|---|---|---|---|
| 01 | Dashboard — open ROs, safety, and the action list | **2026-10-09** | GPU box, local NIMs |
| 02 | Repair Order — state folded from events | **2026-10-09** | GPU box, local NIMs |
| 03 | Technician Update — logging work against an RO | 2026-10-07 | Mac, hosted |
| 04 | Shift Handover — generated brief, worst first | 2026-10-07 | Mac, hosted |
| 05 | Manager Assistant — a cited answer with its tools | 2026-10-07 | Mac, hosted |
| 06 | Data & Retrieval — the store consoles are pointed at, not embedded | 2026-10-07 | Mac, hosted |
| 07 | Prometheus targets — `asoia` **and `dcgm` both up** | **2026-10-09** | GPU box |
| 08 | Prometheus — `asoia_tool_calls_total`, one series per tool actually called | **2026-10-09** | GPU box, under load |
| 09 | Grafana — ungrounded 0, latency by path, NIM latency, six tools, GPU tracking the semantic queries | **2026-10-09** | GPU box, under load |
| 10 | Attu — connected to Milvus 2.5.4 standalone, 1 database | **2026-10-09** | GPU box |
| 11 | Attu — the `updates` collection, **1,690 entities** | **2026-10-09** | GPU box |
| 12 | sqlite-web — the system of record | **2026-10-09** | GPU box |

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
service="llm"}`** on the exporter while the LLM NIM itself stayed healthy on
`/v1/health/ready` with nothing in its own log. The client gives up before the
model answers. It also explains the 49.8s outlier in `docs/EXAMPLES.md`, the
fallbacks recorded as *"the retry was uncited"*, and `POST /updates` hanging
past 240s without logging a request line. Not fixed here, and recorded so it is
not rediscovered from scratch.

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
