# Capstone summary: Service Operations Intelligence Agent

An NVIDIA-stack agent that turns field updates (typed or spoken) into continuously derived job state, a prioritised handover and grounded, cited answers for a supervisor. Built for service operations across sectors, demonstrated in automotive service, on one NVIDIA Brev L40S with three self-hosted NIMs.

Every figure below is from this repo (`README.md`, `docs/TECHNICAL.md`, `ENGINEERING.md`, `evals/baseline.json`, `docs/architecture-deck.pptx`) or from the last live run on an L40S. Where a number differs between runs it says so.

---

## 1. Area of deployment

**Built for service operations: any operation where work is handed over between people, and delays, rework or safety matter.**

| sector | what the work looks like |
|---|---|
| **Automotive service** (the showcase) | Workshop repair orders, technician updates, safety checks before a vehicle is released |
| Equipment maintenance | Planned and breakdown work on plant and machinery, parts and spares |
| Facilities management | Maintenance jobs, contractors, building and compliance checks |
| Utilities and energy | Field work orders, crews, inspections |
| Healthcare equipment | Servicing and calibration of medical devices, compliance records |
| Aviation maintenance | Task cards, defects, parts and sign-off |

- **Users in every sector:** the people doing the work **feed updates in** (voice or text, in their own words); supervisors and managers **look up the state of operations and ask questions**.
- **What is generic and what is per sector:** the event log, state fold, grounding checks and agent are generic. Only the catalogue (operations, spec limits) and the lifecycle table are domain data, so moving to a new sector means swapping those.
- **Status:** automotive service is built and demonstrated end to end. The other sectors are the intended area of deployment, not yet built.
- **Where it runs:** one NVIDIA Brev L40S (48 GB), three local NIMs, self-hosted. Nothing in the answer path calls a hosted model; speech-to-text is the one hosted dependency.
- **Showcase data:** a synthetic automotive dataset modelled on real workshop practice (400 repair orders, 50 staff, 104 labour operations, about 1.7 to 1.9 thousand updates, about 10 thousand events).

## 2. Business problem

In any service operation, job status lives in notes, calls, messages, spreadsheets and people's memory. The challenge is **moving that information accurately, and finding it again when it matters.**

| symptom | cost |
|---|---|
| Updates arrive as free text and speech, from many people, and never become a record anyone can query | **Time lost**: people ask again, search and re-type the same update |
| Nobody sees one current picture of every job | Supervisors find out late, when someone calls |
| Related work is invisible across jobs (one part wanted by several jobs) | **Over-committed resources**: parts ordered twice, crews double-booked |
| The finding that matters most is one line in one note | **Critical items missed**: delays, rework, safety incidents |
| AI answers are not checkable or traceable, and hosted models change underneath you | Answers nobody can trust; a system you do not control |

**The agent's answer:** capture an update once, in the worker's own words; check every fact against the record; derive state instead of storing it; let a supervisor ask in plain language and get a cited answer. **The model reads and writes language; Python computes everything that counts.**

Note on scope: the agent surfaces state, contradictions and shared part holds so a supervisor can avoid double-booking and duplicate orders. It does not schedule, assign or order anything, and it has no double-booking detector.

## 3. NVIDIA stack

Fourteen components: **thirteen built and running, one blocked** (listed as blocked, not claimed).

| component | role here | status |
|---|---|---|
| **NIM: Nemotron Nano 8B** (`llama-3.1-nemotron-nano-8b-v1`) | Reads updates into structured JSON; narrates free-text search results. Nothing else | local, `:8000` |
| **NIM: `nv-embedqa-e5-v5`** (1024-d) | Embeds updates and matches operation codes | local, `:8001` |
| **NIM: `nv-rerankqa-mistral-4b-v3`** | Reorders search candidates before they are cited | local, `:8002` |
| **Riva Parakeet ASR** | Speech to text for spoken updates (gRPC) | hosted |
| **Riva Magpie TTS** | Voices the spoken updates the ASR leg is tested with | hosted |
| **NeMo Agent Toolkit** | The agent as a workflow over the same 11 typed tools | runs: tools execute 18/18, composed answers 3/18 |
| **NeMo Guardrails** | Input and output rails judged by the local model | `ASOIA_NEMO_RAILS` (off, shadow, on) |
| **NeMo Curator** | Six-stage curation; the last stage quarantines the prompt-injection vector before indexing | `scripts/curate.py` |
| **NeMo Evaluator** | Seven custom (BYOB) benchmarks: routing, grounding, traceability, refusal, tool calls, accuracy, relevance | `evals/asoia_byob.py` |
| **NeMo Relay** | Per-stage trace spans: which tool, which model, how long | `ASOIA_TRACE` |
| **NeMo Switchyard** | Routing proxy: nano local, a larger model hosted on escalation | off by default |
| **NVIDIA DCGM** | GPU telemetry: utilisation, memory, power, temperature (19 series) | running, `:9401` |
| **NVIDIA Brev, L40S 48 GB** | The deployment target carrying all three NIMs | running |
| **NemoClaw / OpenShell** | Would add a containment boundary and a sandboxed compute tool | **blocked**: platform fault (`ENGINEERING.md` section 34) |

Around it, not counted as NVIDIA: Milvus (vectors), SQLite (system of record), FastAPI, Gradio, Prometheus and Grafana.

## 4. Results and progress

**Delivered and running on the L40S:** the full write path (speech, extraction, validation, reconciliation, diff card), the read path (routing, 11 tools, grounded composition, rails), a six-tab operations console, an HTTP API, a seven-pane evidence workbench, observability, a ten-slide architecture deck, eight notebooks, a Brev runbook, and a 2:34 client demo video.

| measure | result | source |
|---|---|---|
| Unit tests | **81 pass**, no GPU or network | `pytest tests/` |
| Answer verification | **14 of 14 checks pass** on the live box, including two action requests refused before any tool runs | `scripts/verify_answers.py --with-llm` |
| Routing | **100%** (37 labelled questions) | `evals/baseline.json` |
| Grounding | **100%**: every figure in an answer appears in a tool result | baseline |
| Traceability | **100%**: every citation resolves (905 of 905 at baseline; 1,042 of 1,042 on the latest run) | baseline, latest run |
| Refusal | **100%** on four attacks and the legitimate set | baseline |
| Full benchmark | answer accuracy 100%, relevance 100%, unsupported figures 0 | baseline |
| Latency, structured questions | about **0.05 to 0.11 s**, no model call; five of six question classes need none | `docs/EXAMPLES.md`, latest run |
| Latency, free-text search | **3 to 4 s** end to end on local NIMs, against 28 to 46 s hosted | README |
| GPU memory | about **32 of 46 GB** with all three NIMs resident | measured on the latest run |
| Retrieval | recall@6 **83.3%** on the question as a person asks it; reranker lifts recall@6 from 41.7% to 49.2% | `docs/TECHNICAL.md` |

**Known limits** (stated up front, each measured):
- Retrieval is the weakest link: recall@6 is capped near 53% on the complaint alone, because 400 repair orders share 36 complaint texts.
- The Agent Toolkit workflow picks and runs the right tool every time but composes poorly (3 of 18 good answers). The native path in `app/agent/agent.py` is what answers.
- NemoClaw / OpenShell is blocked by a platform fault, so there is no containment boundary or sandboxed compute tool.
- No authentication on the UI, API or share link, by decision.
- Speech-to-text is hosted; there is no local Riva container in this deployment.

## 5. Next steps

| step | why |
|---|---|
| Build the second sector and pilot with a real operation | Tests the cross-sector claim, which is not yet built |
| Connect real sources (work orders, parts, scheduling) | Moves from visible conflicts to flagged ones |
| Improve retrieval recall and agent answer quality | Recall@6 is 83.3%; only 3 of 18 Agent Toolkit answers are good |
| Unblock NemoClaw; add local Riva speech-to-text | Closes the blocked component and the last hosted dependency |
| Add authentication | Needed before any pilot with real data |

Steps are *proposed*, drawn from the measured limits; confirm priorities before presenting them as a plan.
