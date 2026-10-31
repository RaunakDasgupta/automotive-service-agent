# Demo video

Two files, both recorded from the real application:

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~7.5 s): the five stages only, with no business figures |
| `demo-preview.mp4` | The whole demo (2:13): 33 voiced beats from `docs/DEMO_VIDEO.md`, at the voice's natural pace |
| `footage/` | The live application as recorded on the L40S box, **raw**: `raw/{A,C,D,G}.mp4` (3840x2160, nothing drawn on it) and `timeline.json` (time windows, clicks, and where every target is on screen). The video is edited from these alone, so **the box is not needed again until the app's screen changes** |

## What is on screen

| scene | what you see |
|---|---|
| Opening | an animated visual from the first frame: shift notes fly onto a moving grid and one is stamped SAFETY |
| A Hook | the **live** Dashboard on the L40S box |
| B Process | a soft dissolve from the dashboard, then the process slide, **rendered from the deck's own XML** and built stage by stage as each is spoken, ending on the whole five-stage flow (not PowerPoint, so fonts differ slightly). The deck slide itself is process only now (no business figures); they have their own segment |
| C Ingest | **live**, entered by a soft dissolve from the process slide: a spoken update is uploaded, Riva transcribes it, Nemotron extracts the measurement, the rules flag the repair order `SAFETY_RELATED` |
| D Ask | **live**: a soft dissolve from the form, then a structured question answered with no model call and a free-text question answered by search + rerank + narration on the local NIMs |
| V Business value | four cards: unsafe vehicles surfaced (`13 of 50`, read from the live dashboard), `0.1 s` answers, `905 / 905` traced answers, one update feeding the whole shop. No cost or speed-up claim is made |
| E Components | an infographic: an L40S chip holding the three NIM tiles with a memory bar (about 30 of 46 GB), then NVIDIA-logo cards with pictograms for Riva, Guardrails and Evaluator |
| G Telemetry | **live** Grafana with DCGM GPU telemetry, after real traffic through `/ask` |
| F Advantages | animated cards ending on *Fast. Grounded. Yours to run.* |

Logo badges (NVIDIA, Grafana) are laid over the live shots as each product is named. There is no cursor on screen except
for the four clicks that start something (Transcribe, Extract and apply, and Ask twice).

The spoken update in scene C is itself synthesised (a second TTS voice) so it can be uploaded; Riva then transcribes
it for real. The app scenes run in extra UIs on the box against a **copy** of the database, so nothing the demo logs
touches the real data.

## How it is edited

The script is a table of short beats, each voiced on its own at the voice's natural pace with a short breath after it
(`TEMPO`, `GAP` in the script), so the **audio length of a beat sets the length of its shot** and the picture cannot
drift from the words. Key visuals are **held still for a moment after they are spoken** (the `HOLD` table), so they can
be read. Inside every other shot the camera is moving, a keyword callout lands as the word is spoken, a ring pulses on
what is described, and a subtitle runs along the bottom. Hard cuts between scenes. No music is mixed in; a quiet
royalty-free bed is recommended in `docs/DEMO_VIDEO.md` section 6.

## Capture once, edit as often as you like

The live scenes are produced in two stages (`scripts/demo_footage.py`, then `scripts/make_demo_preview.py`):

1. **Capture, on a box.** The real app is driven once and recorded as a 2x screenshot loop, so a camera zoom is still
   sharp. Nothing is drawn on it: no camera, ring, caption, callout or cursor. `timeline.json` records, for each step
   (`A`, `C1`-`C4`, `D1`-`D6`, `G1`), its time window, the clicks, the moment its result appeared, and the rectangle of
   every element the camera may aim at.
2. **Edit, offline.** Each beat takes its step from the footage, re-times it to the narration (only the wait for a slow
   model is ever cut), and adds the camera, ring, callout, badge, caption and cursor. Changing the script, pacing, zoom,
   callouts or cursor is a re-run of the edit and needs no GPU.

A box is needed again **only when what the app puts on screen changes**. Each scene is stamped with a fingerprint of the app
code, the Grafana dashboard and the inputs typed into it. `python scripts/demo_footage.py --check` (the edit prints the
same verdict) says whether the footage still matches; if code changed but the screen did not, `--restamp` accepts it.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's key,
at natural speed with beats padded by 0.3 s. Results are cached in `~/.cache/asoia-demo-tts`. The narration is read
straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video. Whether this voice is
good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Rebuild

The tools are deliberately not project dependencies; use a throwaway venv:

```bash
python -m venv /tmp/demoenv
/tmp/demoenv/bin/pip install playwright websockets imageio-ffmpeg nvidia-riva-client
/tmp/demoenv/bin/python -m playwright install chromium
/tmp/demoenv/bin/python scripts/demo_footage.py --check                    # is the footage still current? (no box)
/tmp/demoenv/bin/python scripts/make_demo_preview.py                       # the whole video, edited from footage/
/tmp/demoenv/bin/python scripts/make_demo_preview.py --scene OE            # only some pieces, for iteration
/tmp/demoenv/bin/python scripts/make_demo_preview.py --slide-only          # just the slide clip
```

Only if `--check` says the footage is stale, bring up a box per `docs/BREV_RUNBOOK.md` and capture, then delete the box:

```bash
/tmp/demoenv/bin/python scripts/demo_footage.py --box <ssh-alias>          # all four live scenes (add --scene C for one)
```

`--box` starts its own recording UIs on a copy of the database, sends 100 s of questions through `/ask` so Grafana has
data, captures, and stops them again (`--no-traffic` skips the warm-up). The NVIDIA and Grafana logos are fetched once
from their public brand assets into `~/.cache/asoia-demo-logos` and are not committed.

The captions keep the real spelling; where the voice gets a word wrong it is given a respelling (`SPOKEN` in the script): *read* in the present tense, and *DCGM* spelled out letter by letter.
