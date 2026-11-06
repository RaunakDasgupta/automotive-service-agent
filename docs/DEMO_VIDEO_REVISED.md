# Revised demo video: script

This is the script the revised video is built from (`scripts/make_demo_preview.py` reads the beat table below). The old final demo is archived in `docs/demo/v1-final/` (git tag `demo-final-v1`) and is not touched; the revised video is `docs/demo/demo-revised.mp4`, and further edits are made to this script and that file.

## 1. The idea the video is centred on

> In service operations, **accurate transfer and retrieval of information** is the challenge when it lives in many sources. When it fails, **time is lost** (asking again, searching, re-keying) and **resources are over-committed** (a job double-booked, the same part ordered twice). It is avoidable if **updates from any kind of operation can be fed in easily**, and **supervisors can look up the state of operations and ask questions** and get answers.

Everything else in the video either sets this up or proves it. "Transfer" is the write path (an update goes in once, in the technician's own words). "Retrieval" is the read path (the live state, and questions in plain language).

## 2. What the repo does about it

| the challenge | what the repo does | where | on the footage? |
|---|---|---|---|
| **Transfer.** Updates are spoken or typed in shorthand by different people | speech to text, extraction into Concern / Cause / Correction, validation against a catalogue; an ambiguous match becomes a question, not a guess | `app/pipeline/*` | yes (C) |
| **Transfer, accurately.** A new update can contradict what is already known | `reconcile` checks it against the record and flags: work already recorded complete (rework or a duplicate?), a part fitted that the log says is not there, work started without authorisation, an illegal state move. Contradictions are surfaced, not overwritten. The Technician Update tab shows what the repair order already says before you log anything | `app/pipeline/reconcile.py` | partly: the check is not shown firing |
| **Retrieval.** What is the state of operations right now? | state is folded from an append-only log on every read, so it cannot drift from the record: blocked, at risk, promise already missed, who did what, hours | `app/state/engine.py` | yes (A) |
| **Retrieval by question.** A supervisor needs an answer, not a search | structured questions answered in about a tenth of a second with no model call, every figure and citation checked; open questions by search, rerank and a cited narration | `app/agent/agent.py` | yes (D) |
| **Over-commitment.** The same part is wanted by several jobs | cross-job patterns: a part on hold for more than one repair order, repeat visits, stalled work | `app/analytics/insights.py` | **no** |
| **Any domain.** Different operations, same pattern | the catalogue, specification limits and lifecycle table are data; the event log, the fold and the checks are generic | `app/data/catalog.py`, `app/state/transitions.py` | positioning, automotive only |

**What not to claim.** The repo does not schedule, assign or order anything, and it has no double-booking or duplicate-order detector. What it does is make the state and the contradictions visible and askable, so a supervisor can avoid them. The narration is worded that way ("resources get over-committed" as the cost of not having the information, not "the agent stops double-booking").

## 3. The problem statement

| part | statement |
|---|---|
| Who | supervisors who run a service operation, and the people who do the work |
| What goes wrong | information moves between many sources (notes, calls, messages, systems) and is not transferred accurately or found again when needed |
| Cost, time | people ask again, search, and re-key the same update |
| Cost, resources | jobs are double-booked, the same part is ordered twice |
| Avoidable if | updates from any kind of operation are fed in easily, and supervisors can look up the state of operations and ask questions |

No statistic is claimed.

## 4. The script

Each row is `| id | narration | what is on screen |`. The first letter is the scene (P problem and sector map, H brand, A dashboard, B process, C ingest, D assistant, E architecture, G observability, V business value, F summary, K outro); `{safety}` and `{ask_n}` are read from the live capture. The business-value cards were cut to bring the video under 2:35; the summary carries the same figures.

| id | narration | picture |
|---|---|---|
| P1 | Every service operation runs on updates from many different sources. | **Title card, the first frame and the thumbnail.** After about 2 s it dissolves to a dark board; five source cards land one by one and stay scattered: **Notes, Calls, Messages, Spreadsheets, Systems** |
| P2 | The challenge is moving that information accurately, and finding it again when it matters. | **The focal beat, held a moment.** Two large columns in green, **Transfer** (updates running between sources and a person, one arriving garbled, one missing) and **Retrieval** (a person reaching out to all five sources and coming back with half an answer) |
| P3 | When that fails, time is lost asking again, searching, and re-keying. | The same update in three places, each marked *asked again*, *searched*, *re-typed*, with a clock turning beside them; callout **Time lost** |
| P4 | Resources get over-committed: a job double-booked, a part ordered twice. | Two panels: **Schedule**, with two names on one job slot, overlapping in red; **Inventory**, with two purchase orders for the same part, marked *x2*; callout **Over-committed** |
| P5 | It need not be. Feed updates in easily, from any operation, into one place. | A vehicle, a machine, a building and an aircraft each send an update along a line into one shared record |
| P6 | Then supervisors can look up the state of operations, ask a question, and get an answer. | A supervisor figure with a question typed into a search box and an answer card under it. Dissolves to the brand card |
| H1 | Our answer: the Service Operations Agent, powered by Deloitte and NVIDIA. | **Brand card:** the Deloitte and NVIDIA logos side by side, *Service Operations Agent* below |
| P7 | Built for any service operation, shown here in automotive. | **Sector map:** six sectors around *The same problem*, automotive lifts and the others dim; line under it *One agent for any service operation. Starting with automotive service.* |
| A1 | Everyone sees the same live state of operations. | A soft dissolve to the **live dashboard**: a slow push-in on the whole screen; callout **Service Operations Agent** |
| A2 | Every job, with the reason it needs attention. | Camera on the first table row and its *why it needs attention* column, ring on it; callout **Automotive showcase** |
| A4 | Like the {safety} vehicles flagged unsafe to release. | Zoom on the *Safety - do not release* tile, ring pulses; callout **{safety} flagged**; held a moment |
| B1 | Updates go in once, by voice or text, in the technician's own words. | Dissolve to the process slide: stage 1 builds, camera on it; callout **Capture** |
| B2 | NVIDIA Riva transcribes it, and Nemotron extracts the facts. | Stage 2, arrow wipes in; callout **Understand** |
| B3 | Code checks every fact against the record and keeps an audit trail. | Stages 3 and 4 build together, camera on both; callout **Verify** |
| B5 | Supervisors simply ask, and receive cited answers. | Stage 5, then the camera pulls back to the whole five-stage flow; callout **Decide** |
| C1 | Follow one update. A technician dictates it from the bay. | Dissolve to Technician Update, camera drops to the voice panel; the recording is uploaded and its waveform appears; callout **Voice in** |
| C2 | NVIDIA Riva turns the speech into text. | Transcribe is clicked; the transcript fills; callout **Riva ASR** |
| C3 | Nemotron extracts the facts: the measurement and the spec. | Extract and apply is clicked; the extracted JSON lands; callout **Nemotron 8B** |
| C4 | Code verifies it and flags the repair order unsafe to release, instantly. | Zoom on the *What changed* card and the out-of-spec line, ring; callout **Flagged unsafe**; held |
| D2 | A supervisor asks: which vehicles cannot be released on safety grounds? | Manager Assistant (a soft dissolve from the form), camera on the question box; the question types out at speaking pace, then is asked |
| D3 | {ask_n} vehicles, each one cited, in a tenth of a second. | Zoom on the answer; callout **Cited · no model call**; held |
| D7 | Another question: which parts are holding up more than one job? | The third question types out and is asked |
| D8 | Order once, and clear several jobs, in a tenth of a second. | Zoom on the answer, the parts that each hold more than one repair order; callout **Order once**; held |
| D5 | An open question: has anyone seen a whistling noise on a Passat? | The fourth question types out and is asked |
| D6 | Search, reranking and a cited answer, in seconds, on one GPU. | Camera on the answer and its update citations; callout **Search + rerank**; held |
| E1 | Behind it, the architecture: three NVIDIA NIMs on one L40S. | **Deployed architecture:** a layered diagram in one frame; the camera drops to the GPU layer, the three NIM tiles and the memory bar |
| E3 | Riva handles speech. NeMo Guardrails stops unsafe requests. | The speech-and-safety layer appears above the GPU layer, with arrows for the transcript and the checked question and answer |
| E5 | NeMo Evaluator scores every release: the whole stack. | The quality layer appears on top; then the camera pulls all the way out to the whole architecture |
| G1 | All observable: DCGM and app metrics, live in Grafana. | **Infographic with the live dashboard inset:** the DCGM exporter and the app feed Prometheus, which feeds Grafana |
| F1 | In summary: updates in once, one shared state. | Title *Summary* and card 1 fly in |
| F2 | Answers in a tenth of a second, every one traced to a record. | Cards 2, 3 and 4 fly in one after another |
| F4 | Fast. Grounded. Yours to run. | Large type, with *Service Operations Agent* beneath it |
| K1 | Service Operations Agent, powered by Deloitte and NVIDIA. | **Closing:** the supplied Deloitte outro clip (`~/.cache/asoia-demo-outro/outro.<ext>`); this line is only the fallback when the clip is missing |

## 5. Problem to proof

| problem beat | answered by |
|---|---|
| P1 many sources | P7: one place for updates, for any kind of operation |
| **P2 transfer and retrieval** | **B1 to B4 and C1 to C4 (transfer, checked against the record); A1 to A4 and D2 to D8 (retrieval, by view and by question)** |
| P3 time lost | D3, D8: an answer in a tenth of a second instead of a chase; A2: the reason is already on the row |
| P4 over-committed resources | **D8: the parts that each hold more than one job, so one order clears several**; B3 flags contradictions with the record; A1 gives everyone the same state |
| P5 updates in easily, any operation | B1, C1, P7 |
| P6 look up and ask | A1, D2, D7, D5 |

## 6. Files

| | |
|---|---|
| `docs/demo/demo-revised.mp4` | this version of the video; further edits go to this file |
| `docs/demo/demo-revised.srt`, `docs/demo/edit-sheet-revised.md` | its subtitles and edit sheet |
| `docs/demo/v1-final/` | the old final demo, untouched |
