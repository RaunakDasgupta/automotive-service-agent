# Screenshots

Captured 2026-10-07 on a Mac with the stack running locally: Milvus, Prometheus,
Grafana, Attu and sqlite-web in containers, inference on the **hosted** NVIDIA
endpoints. The GPU box these were previously taken on no longer exists.

| | |
|---|---|
| 01 | Dashboard — 41 open ROs, 12 safety, and the action list |
| 02 | Repair Order — state folded from events: ops, parts, safety, promise risk |
| 03 | Technician Update — logging work against an RO |
| 04 | Shift Handover — generated brief, worst first |
| 05 | Manager Assistant — a cited answer with its tools and sources |
| 06 | Data & Retrieval — note the store consoles are pointed to, not embedded |
| 07 | Prometheus targets — `asoia` up; `dcgm` down because a Mac has no GPU |
| 08 | Prometheus — `asoia_tool_calls_total`, one series per tool actually called |
| 09 | Grafana — compose path, latency p50/p95, NIM latency, tool usage |
| 10 | Attu — the `updates` collection, loaded, 1,857 entities |
| 11 | Attu — schema showing `FloatVector(2048)`, the hosted embedder's width |
| 12 | sqlite-web — 9 tables, 4.5 MB |

Two things are honestly different from the GPU-box runs: there is **no hosted
reranker**, so retrieval is vector-only here; and the hosted chat model is a
reasoning model, which makes narrated answers take tens of seconds rather than
under two.
