# Client demo video — plan, script and tooling

**Target length 2:00–2:15** (288 spoken words ≈ 1:55 at 150 wpm, plus ~15 s of silent live action; set the voice to ~160 wpm so each scene fits its window). **Audience:** a prospective client evaluating an
AI assistant for a service department. **One idea:** *fast, grounded answers, running on your own GPU.*

## 1. Script (narration for AI voice)

Bracketed `[N]` values are read off the live run, never invented. Every other number is already measured in the repo
(source in §4).

| # | Time | Narration | On screen (live unless noted) |
|---|---|---|---|
| 1 | 0:00–0:18 | In a busy service department, the truth lives in shift updates nobody has time to read. Safety findings, parts holds and missed promises stay buried until a customer complains. This is the Automotive Service Operations Intelligence Agent: voice and text updates in, a live picture of every repair order out. | **Dashboard** with the KPI tiles (open ROs, safety, promise missed, blocked) and the "needs a decision" table |
| 2 | 0:18–0:36 | A technician speaks or types an update. NVIDIA Riva Parakeet transcribes it. A Nemotron model extracts the facts. Python checks every one against the catalogue, folds it into an event log, and derives the state of the repair order. Nothing is guessed, and every answer cites its records. | **Animated flow strip** (slide 8's strip): Voice → Parakeet → Nemotron → validate → event log → state → cited answer. Pre-rendered graphic |
| 3 | 0:36–0:58 | Live: a technician dictates that the front pads measure one point eight millimetres against a three millimetre minimum. The system matches the repair order, flags it unsafe to release, and shows exactly what changed. | **Technician Update** tab: upload/play the dictation → transcript → "Extract and apply" → diff card with the safety flag |
| 4 | 0:58–1:22 | Now the manager asks which vehicles cannot be released on safety grounds. [N] repair orders, each cited, in a tenth of a second, with no model call. A free-text question, like a whistling noise on a Passat, searches by meaning and is written up by the model in about three and a half seconds. | **Manager Assistant**: the safety question (answer + `Tools: … Sources: RO-…` footer), then the whistling question. Keep the 3.5 s wait **in real time** — it is the proof |
| 5 | 1:22–1:46 | Three NVIDIA NIM microservices run on a single L40S: Nemotron for language, an embedding model and a reranker for search. NVIDIA-hosted Riva handles speech. NeMo Guardrails stops unsafe requests before any tool runs. NeMo Evaluator scores every release, and DCGM streams live GPU telemetry into Grafana. | Component strip lighting up in order, then **Grafana** (GPU util spiking on the semantic query) and **Attu** (`FloatVector(1024)`, 1,690 entities) |
| 6 | 1:46–2:12 | Why it matters. The models run on your own GPU, so the answer path never depends on a hosted endpoint that can be retired. One card carries the whole stack. Answers are reproducible, every figure is checked against the records, and every call is measured. Fast, grounded, and yours to run. Let's talk about your shop. | Four proof cards (see §4), then end card: title, contact, "NVIDIA NIM · Riva · NeMo · DCGM" |

```bash
# word count of the narration column (currently 288)
python3 - <<'EOF'
import re
for l in open("docs/DEMO_VIDEO.md"):
    m = re.match(r"\| (\d) \| [\d:–]+ \| (.+?) \| ", l)
    if m: print(m.group(1), len(m.group(2).split()))
EOF
```

## 2. Production workflow

1. **Lock the script, generate the voice first.** Timing then follows the audio, not the other way round.
2. **Pre-flight the box** (§3), then record **one clip per row** — not one long take.
3. **Assemble** the clips against the voiceover; hold each live action on screen until its result lands.
4. **Captions burned in** (clients often watch muted), low music bed, end card.
5. **Review against §5 before anything leaves your machine.**

## 3. Live-capture pre-flight (the part that makes or breaks it)

- `bash scripts/stack.sh status` shows the three NIMs **routed** (not idle); `verify_answers.py --with-llm` passes.
- **Warm the dashboards.** Prometheus counters are per-process: send ~10 minutes of questions through
  `POST /ask` on :8080, or Grafana reads *No data*. Record the Grafana clip afterwards.
- **Do not click between Gradio tabs on camera** — it pins a CPU core and freezes the page. Start one UI per tab
  (`ASOIA_UI_TAB=update PORT=7861 …`, `handover` 7862, `assistant` 7863) and cut between pre-opened windows.
- Technician Update **writes**: use a demo repair order, and have the dictation audio ready to upload as the
  fallback if the live microphone/hosted ASR hiccups.
- Open everything through an `ssh -L` tunnel on `127.0.0.1`. No `gradio.live` link, no tunnel URL, no `.env`, no key.
- 1920×1080, 100 % browser zoom, hide bookmarks and notifications.

## 4. Claims ledger — every claim is backed

| claim in the script | evidence |
|---|---|
| answer in ~0.1 s, no model call | `docs/EXAMPLES.md` (0.00–0.11 s), `verify_answers.py` proves no LLM call |
| ~3.5 s narrated answer | `docs/EXAMPLES.md` (3.43–3.87 s) |
| three NIMs on one L40S, "one card carries the stack" | measured 29,963 MiB resident of 46,068 MiB |
| never depends on a retired hosted endpoint | the hosted LLM and embedder were both retired (HTTP 410); local containers were not |
| reproducible | pinned container at temperature 0 (`README` hosted-vs-local table) |
| every figure checked | `check_grounding`; baseline grounding 100 %, traceability 905/905, routing 37/37 |
| DCGM → Grafana | 19 GPU series, `docs/screenshots/09` |
| **not claimed** | retrieval accuracy (83.3 % recall@6), cost savings, speed against any competitor — none measured |

Honest caveat to keep in the script: **speech-to-text is NVIDIA-hosted**, not on the box (scene 5 says so).

## 5. Pre-publish checklist

No API key, `.env`, tunnel URL or Brev hostname visible · share link off · dataset is the demo dataset ·
numbers in scene 4 match the live screen · captions proofread · audio ≈ −16 LUFS, music ≥ 18 dB under voice.

## 6. AI tools (researched 2026-10-30; sources conflict on features and prices — verify before buying)

| job | recommendation | why / caveat |
|---|---|---|
| **Narration** | **Two candidates; A/B them blind.** (a) **ElevenLabs** — the realism leader in most comparisons; a *Commercial License* starts at the Starter tier ([pricing](https://elevenlabs.io/pricing); confirm the free tier is not enough for client use). (b) **NVIDIA Riva Magpie TTS** through the code already in `scripts/make_speech.py` — on-brand ("narrated by Riva") and free with your key | The repo pins Magpie to **16 kHz** for ASR testing; narration wants 22.05/44.1 kHz — *untested*, try `sample_rate_hz` first. Murf is the usual third option for video voiceover |
| **Screen capture** | **Screen Studio** (Mac) — auto-zoom on clicks, smoothed cursor; no voiceover feature | Reviews quote $29–$89 one-time; check the vendor page. Alternatives with auto-zoom: FocuSee, Cap |
| **Assembly, captions, AI voice in the timeline** | **Descript** — edit video by editing the transcript, AI narration, auto-captions | Auto-zoom is weaker than Screen Studio (sources disagree), hence capture there and assemble here |
| **Flow graphic** | Reuse `docs/architecture-deck.pptx` slide 8 strip; export as PNG/MP4 from PowerPoint or Keynote | Already on-brand and font-checked |
| **Manual alternative** | Camtasia — most control, least automation | Its AI voice features are disputed across sources |

**Recommended stack:** Screen Studio (capture) → ElevenLabs *or* Magpie (voice) → Descript (assemble + captions).

Sources: [ElevenLabs pricing](https://elevenlabs.io/pricing) ·
[TTS roundup](https://www.guideflow.com/blog/best-text-to-speech-software) ·
[AI screen recorders](https://www.screenify.studio/blog/2026-04-16-best-ai-screen-recorder) ·
[Screen Studio vs Camtasia](https://screencharm.com/blog/screen-studio-vs-camtasia) ·
[Magpie TTS on build.nvidia.com](https://build.nvidia.com/nvidia/magpie-tts-multilingual/api)
