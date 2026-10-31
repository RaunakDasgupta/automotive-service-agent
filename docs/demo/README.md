# Demo video

Two files, both recorded from the real application:

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~10 s), as the deck builds it |
| `demo-preview.mp4` | The whole demo (2:12): 33 voiced beats from `docs/DEMO_VIDEO.md`, at the voice's natural pace |
| `footage/` | The raw live-app shots (`A C D G`, video only, with their captions burned in) and their original beat timings (`beats.json`), recorded on the L40S box |

## What is on screen

| scene | what you see |
|---|---|
| Opening | an animated visual from the first frame: shift notes fly onto a moving grid and one is stamped SAFETY |
| A Hook | the **live** Dashboard on the L40S box |
| B Process | the process slide, **rendered from the deck's own XML** and built stage by stage as each is spoken (not PowerPoint, so fonts differ slightly) |
| C Ingest | **live**: a spoken update is uploaded, Riva transcribes it, Nemotron extracts the measurement, the rules flag the repair order `SAFETY_RELATED` |
| D Ask | **live**: a soft dissolve from the form, then a structured question answered with no model call and a free-text question answered by search + rerank + narration on the local NIMs |
| V Business value | four cards: unsafe vehicles surfaced (`13 of 50`, read from the live dashboard), `0.1 s` answers, `905 / 905` traced answers, one update feeding the whole shop. No cost or speed-up claim is made |
| E Components | an infographic: an L40S chip holding the three NIM tiles with a memory bar (about 30 of 46 GB), then NVIDIA-logo cards with pictograms for Riva, Guardrails and Evaluator |
| G Telemetry | **live** Grafana with DCGM GPU telemetry, after real traffic through `/ask` |
| F Advantages | animated cards ending on *Fast. Grounded. Yours to run.* |

Logo badges (NVIDIA, Grafana) are laid over the live shots as each product is named.
| F Advantages | animated cards and an end card with a placeholder for your name and contact |

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

Without a box, the live scenes are **re-timed from `footage/`**: each beat's recorded shot is stretched a little to its
new length and its last frame is held. With a box (`--box`) they are recorded afresh at the new timings.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's key,
at natural speed with beats padded by 0.3 s. Results are cached in `~/.cache/asoia-demo-tts`. The narration is read
straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video. Whether this voice is
good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Rebuild

The tools are deliberately not project dependencies; use a throwaway venv:

```bash
python -m venv /tmp/demoenv
/tmp/demoenv/bin/pip install playwright imageio-ffmpeg nvidia-riva-client
/tmp/demoenv/bin/python -m playwright install chromium
/tmp/demoenv/bin/python scripts/make_demo_preview.py                        # whole video, live scenes re-timed from footage/
/tmp/demoenv/bin/python scripts/make_demo_preview.py --scene OE             # only some pieces, for iteration
/tmp/demoenv/bin/python scripts/make_demo_preview.py --slide-only           # just the slide clip
/tmp/demoenv/bin/python scripts/make_demo_preview.py --box <ssh-alias>      # record the live scenes afresh on a running box
```

The NVIDIA and Grafana logos are fetched once from their public brand assets into
`~/.cache/asoia-demo-logos` and are not committed. `--box` needs the stack up (`docs/BREV_RUNBOOK.md`); the script starts
its own recording UIs on a copy of the database, sends 100 s of questions through `/ask` so Grafana has data, records,
and stops them again (`--no-traffic` skips the warm-up).
