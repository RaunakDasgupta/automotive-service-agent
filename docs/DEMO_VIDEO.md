# Client demo video — plan, script and tooling

**Target length 2:00–2:15.** **Audience:** a prospective client evaluating an
AI assistant for a service department. **One idea:** *fast, grounded answers, running on your own GPU.*

## 1. Script — written to be cut, not read

**Target 2:15.** ~330 spoken words at the voice's natural pace, each beat followed by a short breath, and key visuals **held still for a moment after they are spoken** so they can be read (the `HOLD` table in `scripts/make_demo_preview.py`). **The picture
changes on every beat and something on screen is always moving**, except during those holds. Each beat is one short sentence; the
generator voices it, then drives the camera, the keyword callout and the highlight from that sentence's exact
length, so words and pictures cannot drift apart. `{safety}` and `{ask_n}` are read from the live run.

What the reference video (Deloitte's 62-second FastForward EX preview) teaches, and this script copies:
a cut about every 2.7 s (22 cuts in 62 s); a **keyword callout that lands on the word being spoken**
("Cloud-based", "Quick to implement"); subtitles burned into every shot; camera drift on every shot; a persona
or product shot at the open and the close; nothing held still. Narration there runs ~150 wpm *without gaps*.

| beat | narration (read aloud) | on screen |
|---|---|---|
| A1 | In every service department, the risk hides between shifts. | **Opening visual, in motion from the first frame:** handwritten shift notes fly onto a moving grid and one is stamped SAFETY |
| A2 | A safety finding sits in a technician's note that nobody has time to read. | Live dashboard: camera snaps to the first table row, ring on the out-of-spec measurement; callout **Safety findings** |
| A4 | Right now, {safety} vehicles on this floor are unsafe to release. | Zoom on the *Safety - do not release* tile, ring pulses; callout **{safety} unsafe**; held a moment |
| A5 | This is the Automotive Service Operations Intelligence Agent. | Pull back to the full dashboard; callout **NVIDIA stack** |
| B1 | Here is how it works. A technician speaks or types an update. | Dissolve from the dashboard to the process slide: stage 1 builds, camera on it; callout **Capture** |
| B2 | NVIDIA Riva transcribes it, and Nemotron extracts the facts. | Stage 2, arrow wipes in; callout **Understand** |
| B3 | Code checks every fact. Nothing is guessed. | Stage 3; callout **Verify** |
| B4 | Each update joins an audit trail. | Stage 4; callout **Record** |
| B5 | So a manager simply asks, and gets a cited answer. Now, the real thing. | Stage 5, then the camera pulls back to the whole five-stage flow; callout **Decide** |
| C1 | Watch. A technician dictates an update from the bay. | Dissolve from the process slide to Technician Update, camera drops to the voice panel; the recording is uploaded and its waveform appears; callout **Voice in** |
| C2 | NVIDIA Riva turns the speech into text. | Transcribe is clicked; the transcript fills; callout **Riva ASR** |
| C3 | Nemotron pulls out the facts: the measurement, and the spec. | Extract and apply is clicked; the extracted JSON lands; callout **Nemotron 8B** |
| C4 | Code checks it, and flags the repair order unsafe to release, instantly. | Zoom on the *What changed* card and the out-of-spec line, ring; callout **Flagged unsafe**; held |
| D1 | Now the manager asks the question that matters. | Manager Assistant (a soft dissolve from the form), camera on the question box |
| D2 | Which vehicles cannot be released on safety grounds? | The question types out at speaking pace, then is asked |
| D3 | {ask_n} vehicles. Every one cited. Answered in a tenth of a second, with no model call. | Zoom on the answer; callout **Cited · no model call**; held |
| D5 | Now an open question: has anyone seen a whistling noise on a Passat? | The second question types out and is asked |
| D6 | Search, rerank and a cited answer, in seconds, on the same GPU. | Camera on the answer and its update citations; callout **Search + rerank**; held |
| V1 | What does that change? Unsafe vehicles surface at once. | **Business value:** four cards; card 1 *{safety} of {open}* unsafe vehicles found at once |
| V2 | Managers get answers in a tenth of a second. | Card 2: *0.1 s* to answer a manager's question |
| V3 | Every figure traces back to a real record. | Card 3: *905 / 905* answers traced to a real record |
| V4 | And one update feeds the record, handover and dashboard. | Card 4: *1 update* feeds the whole shop; pull back to all four cards; footnote |
| E1 | Three NVIDIA NIM microservices run on one L40S: language, embedding and reranking. | Infographic: an L40S chip with three tiles (chat, search, rank icons) that pulse in turn, then a memory bar fills to about 30 of 46 GB; callout **1 GPU**; held |
| E3 | Riva handles speech. NeMo Guardrails stops unsafe requests. | Two white cards with the NVIDIA logo and pictograms (waveform, shield) fly in |
| E4 | Only speech recognition uses NVIDIA's hosted service. | Ring on the Riva card, tagged *hosted* |
| E5 | NeMo Evaluator scores every release. | Evaluator card (gauge pictogram), ring; held |
| G1 | And DCGM streams live GPU telemetry into Grafana. | **Live Grafana** on the L40S: camera to the GPU utilisation and framebuffer panels, then the power panel, ring; held |
| F1 | Your models, on your GPU. No hosted endpoint to retire. | Title and card 1 fly in |
| F2 | About thirty gigabytes of a forty-six gigabyte card, pinned and reproducible. | Cards 2, 3 and 4 fly in one after another |
| F4 | Fast. Grounded. Yours to run. | Large type; the video ends here |

```bash
# beats, words, and the speaking time they imply at 190 wpm
python3 - <<'EOF'
import re
t = 0
for l in open("docs/DEMO_VIDEO.md"):
    m = re.match(r"\| ([A-V]\d) \| (.+?) \| ", l)
    if m: t += len(m.group(2).split())
print(t, "words =", round(t / 190 * 60), "s of speech at 190 wpm")
EOF
```

## 2. Production workflow

1. **Lock the script, generate the voice first.** Timing then follows the audio, not the other way round.
2. **Pre-flight the box** (§3), then record **one clip per row** — not one long take.
3. **Assemble** the clips against the voiceover; hold each live action on screen until its result lands.
4. **Captions burned in** (clients often watch muted), low music bed, end card.
5. **Review against §5 before anything leaves your machine.**

## 3. Live-capture pre-flight (the part that makes or breaks it)

**The capture is a one-off.** `scripts/demo_footage.py` records the app raw (4K, nothing drawn on it) and
`scripts/make_demo_preview.py` does the rest offline, so rewording the script, changing the pacing, the zoom, the callouts or the
cursor needs **no box**. Run `python scripts/demo_footage.py --check` first: it says whether what the app puts on screen has
changed since the footage was recorded. Only if it has, use the checklist below on a fresh box and delete the box afterwards.

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
| business value, card 1: *{safety} of {open}* | read from the running dashboard (`Safety - do not release` over `Open repair orders`) on the demo dataset |
| business value, cards 2 and 3: *0.1 s*, *905 / 905* | the 0.1 s and traceability rows above |
| business value, card 4: *1 update feeds the record, handover and dashboard* | state is folded from one event log (`docs/TECHNICAL.md`); the handover and dashboard are derived from it |
| **not claimed** | retrieval accuracy (83.3 % recall@6), cost savings, speed against any competitor — none measured |

Honest caveat to keep in the script: **speech-to-text is NVIDIA-hosted**, not on the box (scene 5 says so).

## 5. Pre-publish checklist

No API key, `.env`, tunnel URL or Brev hostname visible · share link off · dataset is the demo dataset ·
numbers in scene 4 match the live screen · captions proofread · audio ≈ −16 LUFS, music ≥ 18 dB under voice.

## 6. AI tools (researched 2026-10-30; sources conflict on features and prices — verify before buying)

| job | recommendation | why / caveat |
|---|---|---|
| **Narration** | **Two candidates; A/B them blind.** (a) **ElevenLabs** — the realism leader in most comparisons; a *Commercial License* starts at the Starter tier ([pricing](https://elevenlabs.io/pricing); confirm the free tier is not enough for client use). (b) **NVIDIA Riva Magpie TTS** through the code already in `scripts/make_speech.py` — on-brand ("narrated by Riva") and free with your key | The repo pins Magpie to **16 kHz** for ASR testing, but the same endpoint returns **44.1 kHz and 22.05 kHz** audio (tested 2026-10-30): set `sample_rate_hz` for narration. Voice quality is a judgement for your ears — the preview in `docs/demo/` uses it. Murf is the usual third option for video voiceover |
| **Screen capture** | **Screen Studio** (Mac) — auto-zoom on clicks, smoothed cursor; no voiceover feature | Reviews quote $29–$89 one-time; check the vendor page. Alternatives with auto-zoom: FocuSee, Cap |
| **Assembly, captions, AI voice in the timeline** | **Descript** — edit video by editing the transcript, AI narration, auto-captions | Auto-zoom is weaker than Screen Studio (sources disagree), hence capture there and assemble here |
| **Flow graphic** | Deck slide 2 (`docs/architecture-deck.pptx`), animated. Capture it by presenting in **PowerPoint** (Slide Show, or File → Export → Video, which plays the animation) | Animations are written into the file's XML and schema-validated, but **not yet seen playing** — preview in PowerPoint before relying on them; Keynote and Google Slides import animations unreliably |
| **Manual alternative** | Camtasia — most control, least automation | Its AI voice features are disputed across sources |

**Recommended stack:** Screen Studio (capture) → ElevenLabs *or* Magpie (voice) → Descript (assemble + captions).

Sources: [ElevenLabs pricing](https://elevenlabs.io/pricing) ·
[TTS roundup](https://www.guideflow.com/blog/best-text-to-speech-software) ·
[AI screen recorders](https://www.screenify.studio/blog/2026-04-16-best-ai-screen-recorder) ·
[Screen Studio vs Camtasia](https://screencharm.com/blog/screen-studio-vs-camtasia) ·
[Magpie TTS on build.nvidia.com](https://build.nvidia.com/nvidia/magpie-tts-multilingual/api)
