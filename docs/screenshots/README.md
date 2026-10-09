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
| 08 | Prometheus — `asoia_tool_calls_total` | 2026-10-07 | Mac, hosted |
| 09 | Grafana — compose path, latency, NIM latency, tool usage | 2026-10-07 | Mac, hosted |
| 10 | Attu — the `updates` collection | 2026-10-07 | Mac, hosted |
| 11 | Attu — schema showing `FloatVector(2048)` | 2026-10-07 | Mac, hosted |
| 12 | sqlite-web — the system of record | **2026-10-09** | GPU box |

## What is out of date, specifically

**11 is wrong now.** It shows `FloatVector(2048)`, the hosted embedder's width.
The store on the GPU box holds **1,690 rows at 1024** — `nv-embedqa-e5-v5`, the
local NIM. 10's entity count is stale for the same reason.

**07 replaced a shot captioned "dcgm down because a Mac has no GPU".** It now
shows `asoia (1/1 up)` and `dcgm (1/1 up)`: the DCGM exporter is live and the
Grafana GPU panels have real data for the first time.

**08, 09 and 10 were re-taken on 2026-10-09 and then discarded**, because they
showed the stack up and the application idle — `asoia_tool_calls_total` returned
*Empty query result*, every Grafana application panel read *No data*, and Attu
was sitting on its connect screen. A screenshot of an idle dashboard does not
show the application working. They need re-taking **after** traffic has gone
through the app, not just after it has started.
