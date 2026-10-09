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
| 09 | Grafana — **87.5% composed in Python**, latency by path, NIM latency, tool usage, GPU to 100% | **2026-10-09** | GPU box, under load |
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

- **09** — *Answers composed in Python 87.5%*, answer latency split by compose
  path (llm ~4–5s against python ~0s), NIM latency per service, five tools in
  `Tool usage`, GPU utilisation spiking to 100% on the semantic queries, and
  zero ungrounded answers.
- **08** — one `asoia_tool_calls_total` series per tool actually called.
- **11** — `updates (1,690)`. It replaces a shot captioned `FloatVector(2048)`,
  the hosted embedder's width; the store is 1024-d now. The Schema tab's field
  list had not loaded when the frame was taken, so the dimension itself is not
  visible — the file is named for what it shows, not what was wanted.

## Still from 2026-10-07, on a Mac with hosted inference

**03, 04, 05 and 06.** Chromium hangs on those four Gradio tabs, headless or
headed under xvfb, so they are not automated. They show the right screens, taken
against the hosted models rather than the local NIMs.
