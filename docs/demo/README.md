# Demo video — preview

Two files to judge **pacing, layout and wording** before the real recording on the Brev box. They are
previews, not the client cut.

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~10 s), as the deck builds it |
| `demo-preview.mp4` | The whole 2:08 demo: voiced, captioned, six scenes from `docs/DEMO_VIDEO.md` |

## What is real, and what is stand-in

| scene | in this preview | on the real recording |
|---|---|---|
| 1 Business case | **live** local app, Dashboard (a local dataset, so the counts differ from the GPU box) | same, from Brev |
| 2 Process flow | the slide **rendered from the deck's own XML** (positions, text, colours, animation timing) — not PowerPoint, so fonts and the wipe effect differ slightly | present deck slide 2 in PowerPoint |
| 3 Ingest | **live** local app, but the measurement is entered through the structured form | dictated audio through Parakeet and Nemotron (needs the GPU box) |
| 4 Ask | **live** local app, the structured safety question; the semantic question is cut from the narration | both questions, with the real 3.5 s semantic answer |
| 5 NVIDIA components | **stills** captured on the L40S on 2026-10-09 (Attu, Grafana + DCGM), labelled as such | live Grafana and Attu |
| 6 Advantages | animated cards and an end card with a placeholder for your name and contact | final contact details |

Every app scene runs against a **copy** of the local dataset, so the real database is untouched.
The orange tag top-right on every scene says what is stand-in; the final cut drops it.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's key.
The narration is read straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video.
Whether this voice is good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Rebuild

The tools are deliberately not project dependencies. In a throwaway venv:

```bash
python -m venv /tmp/demoenv
/tmp/demoenv/bin/pip install playwright imageio-ffmpeg nvidia-riva-client
/tmp/demoenv/bin/python -m playwright install chromium
/tmp/demoenv/bin/python scripts/make_demo_preview.py              # both videos (~4 min)
/tmp/demoenv/bin/python scripts/make_demo_preview.py --slide-only # just the slide clip
```
