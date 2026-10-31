# Demo video

Two files, both recorded from the real application:

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~10 s), as the deck builds it |
| `demo-preview.mp4` | The whole demo (~2:10): 34 voiced beats across eight scenes from `docs/DEMO_VIDEO.md` |

## What is on screen

| scene | what you see |
|---|---|
| A Hook | the **live** Dashboard on the L40S box |
| B Process | the process slide, **rendered from the deck's own XML** and built stage by stage as each is spoken (not PowerPoint, so fonts differ slightly) |
| C Ingest | **live**: a spoken update is uploaded, Riva transcribes it, Nemotron extracts the measurement, the rules flag the repair order `SAFETY_RELATED` |
| D Ask | **live**: a structured question answered with no model call, then a free-text question answered by search + rerank + narration on the local NIMs |
| E Components | animated cards for the NIMs, Riva, Guardrails and Evaluator |
| G Telemetry | **live** Grafana with DCGM GPU telemetry, after real traffic through `/ask` |
| H Vectors | **live** Attu: collection `updates`, 1,897 vectors, `FloatVector(1024)` |
| F Advantages | animated cards and an end card with a placeholder for your name and contact |

The spoken update in scene C is itself synthesised (a second TTS voice) so it can be uploaded; Riva then transcribes
it for real. The app scenes run in extra UIs on the box against a **copy** of the database, so nothing the demo logs
touches the real data.

## How it is edited

The script is a table of short beats, each voiced on its own and sped up a little, so the **audio length of a beat
sets the length of its shot** and the picture cannot drift from the words. Inside every shot the camera is always
moving (push-in, pan, or pull-back), a keyword callout lands as the word is spoken, a ring pulses on what is being
described, and a subtitle runs along the bottom. Hard cuts between scenes.

Real models take a variable time to answer, so each beat's shot is cut from the instant its action actually started,
for exactly its voiced length. Time a slow call spent working between two beats is dropped, never shown late. No music
is mixed in; a quiet royalty-free bed is recommended in `docs/DEMO_VIDEO.md` section 6.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's key,
sped up 10% with beats padded by 0.12 s. Results are cached in `~/.cache/asoia-demo-tts`. The narration is read
straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video. Whether this voice is
good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Rebuild

It needs a running box (see `docs/BREV_RUNBOOK.md`: NIMs, Milvus, API, Grafana, Attu) and an ssh alias for it. The
recording tools are deliberately not project dependencies; use a throwaway venv:

```bash
python -m venv /tmp/demoenv
/tmp/demoenv/bin/pip install playwright imageio-ffmpeg nvidia-riva-client
/tmp/demoenv/bin/python -m playwright install chromium
/tmp/demoenv/bin/python scripts/make_demo_preview.py --box <ssh-alias>              # both videos (~8 min)
/tmp/demoenv/bin/python scripts/make_demo_preview.py --box <ssh-alias> --scene C    # one scene, for iteration
/tmp/demoenv/bin/python scripts/make_demo_preview.py --slide-only                   # just the slide clip (no box)
```

The script starts its recording UIs on the box, forwards the ports it needs, sends 100 s of mixed questions through
`/ask` so the Grafana panels have data, records, and stops its UIs again. `--no-traffic` skips the warm-up.
