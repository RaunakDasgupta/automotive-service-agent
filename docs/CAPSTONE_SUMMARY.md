# Capstone summary: Service Operations Intelligence Agent

An NVIDIA-stack agent that turns field updates (typed or spoken) into live job state, a prioritised handover and cited answers for a supervisor. Built for service operations across sectors, demonstrated in automotive service, on one NVIDIA Brev L40S with three self-hosted NIMs.

## 1. Area of deployment

**Built for service operations: any operation where work is handed over between people and delays, rework or safety matter.**

| sector | the work |
|---|---|
| **Automotive service** (showcase) | repair orders, technician updates, pre-release safety checks |
| Equipment maintenance | breakdown and planned work, parts and spares |
| Facilities management | maintenance jobs, contractors, compliance checks |
| Utilities and energy | field work orders, crews, inspections |
| Healthcare equipment | servicing, calibration, compliance records |
| Aviation maintenance | task cards, defects, parts, sign-off |

- **Users:** the people doing the work feed updates in (voice or text); supervisors look up the state of operations and ask questions.
- **Per sector:** only the catalogue (operations, spec limits) and the lifecycle are domain data; the rest is generic.
- **Status:** automotive is built and demonstrated end to end; the other sectors are the intended area, not yet built.
- **Runs on:** one Brev L40S (48 GB), three local NIMs. Speech-to-text is the one hosted dependency.

## 2. Business problem

Job status lives in notes, calls, messages and systems. The challenge is **moving that information accurately, and finding it again when it matters.**

| symptom | cost |
|---|---|
| Updates scattered, never queryable | **Time lost** re-asking, searching and re-typing |
| Related work invisible across jobs | **Over-committed resources**: parts ordered twice, crews double-booked |
| The finding that matters is one line in a note | **Missed**: delays, rework, safety incidents |
| AI answers not checkable or traceable | Answers nobody can trust |

**The answer:** capture an update once, check every fact against the record, derive state instead of storing it, and let a supervisor ask in plain language and get a cited answer. The model reads and writes language; Python computes everything that counts.

The agent surfaces state, contradictions and shared part holds. It does not schedule, assign or order, and has no double-booking detector.

## 3. NVIDIA stack (13 components, all running)

| component | role |
|---|---|
| NIMs: Nemotron Nano 8B, NV-EmbedQA E5, NV-RerankQA 4B | read and narrate, embed, rerank (local) |
| Riva Parakeet, Magpie | speech-to-text, text-to-speech (hosted) |
| NeMo Guardrails | input and output rails |
| NeMo Curator | curation; quarantines prompt injection |
| NeMo Evaluator | seven benchmarks |
| NeMo Relay | per-stage traces |
| NeMo Agent Toolkit | the agent as a workflow over 11 tools |
| NeMo Switchyard | local or hosted routing (off by default) |
| DCGM | GPU telemetry (19 series) |
| Brev L40S 48 GB | deployment |

Not counted as NVIDIA: Milvus, SQLite, FastAPI, Gradio, Prometheus, Grafana.

## 4. Results and progress

Built, deployed and demoed end to end in automotive service: write path, read path, six-tab console, HTTP API, evidence workbench, observability, architecture deck, notebooks, Brev runbook, and a 2:34 client demo video.

| measure | result |
|---|---|
| Unit tests | 81 pass |
| Live answer checks | 14 of 14 pass |
| Routing, grounding, refusal, traceability | 100% (traceability: 905 of 905 at baseline, 1,042 of 1,042 on the latest run) |
| Structured answers | about 0.05 to 0.11 s, no model call |
| Free-text answers | 3 to 4 s on local NIMs, against 28 to 46 s hosted |
| GPU memory | about 32 of 46 GB, all three NIMs resident |
| Retrieval recall@6 | 83.3% (weakest area) |

**Known limits:** retrieval recall is capped near 53% on the complaint alone; the Agent Toolkit composes only 3 of 18 answers well (the native path answers); no authentication, by decision; speech-to-text is hosted.

## 5. Next steps

| step | why |
|---|---|
| Build the second sector and pilot | tests the cross-sector claim |
| Connect real sources (work orders, parts, scheduling) | moves from visible conflicts to flagged ones |
| Improve retrieval recall and agent answer quality | recall@6 83.3%; 3 of 18 Toolkit answers good |
| Add local Riva speech-to-text | removes the last hosted dependency |
| Add authentication | needed before any pilot |

Steps are proposed, drawn from the measured limits; confirm priorities before presenting them as a plan.
