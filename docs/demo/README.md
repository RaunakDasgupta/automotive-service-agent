# Demo video — preview

Two files to judge **pacing, layout and wording** before the real recording on the Brev box. They are
previews, not the client cut.

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~10 s), as the deck builds it |
| `demo-preview.mp4` | The whole demo (~2:04): 33 voiced beats across six scenes from `docs/DEMO_VIDEO.md` |

## How it is edited

The script is a table of short beats, each voiced on its own and trimmed to a brisk tempo, so the **audio
length of a beat sets the length of its shot** and the picture can never drift from the words. Inside every
shot the camera is always moving (push-in, pan, or pull-back), a keyword callout lands as the word is spoken,
a ring pulses on the thing being described, and a subtitle runs along the bottom. Nothing sits still for much
over a second. Hard cuts between scenes; no music is mixed in (a quiet royalty-free bed is recommended in
`docs/DEMO_VIDEO.md` §6).

## What is real, and what is stand-in

| scene | in this preview | on the real recording |
|---|---|---|
| A Hook | **live** local app, Dashboard (a local dataset, so the counts differ from the GPU box) | same, from Brev |
| B Process | the slide **rendered from the deck's own XML**, stage by stage as each is spoken — not PowerPoint, so fonts differ slightly | present deck slide 2 in PowerPoint |
| C Ingest | **live** local app, measurement entered through the structured form | dictated audio through Parakeet and Nemotron (needs the GPU box) |
| D Ask | **live** local app, the structured safety question; local answers are slower than the L40S's measured 0.11 s | both questions, with the real timings |
| E NVIDIA components | animated chips plus **stills** captured on the L40S on 2026-10-09 (Grafana + DCGM, Attu), labelled as such | live Grafana and Attu |
| F Advantages | animated cards and an end card with a placeholder for your name and contact | final contact details |

Every app scene runs against a **copy** of the local dataset, so the real database is untouched.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's
key, sped up 6% with beats padded by 0.12 s. Results are cached in `~/.cache/asoia-demo-tts`. The narration is
read straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video. Whether
this voice is good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Rebuild

The tools are deliberately not project dependencies. In a throwaway venv:

```bash
python -m venv /tmp/demoenv
/tmp/demoenv/bin/pip install playwright imageio-ffmpeg nvidia-riva-client
/tmp/demoenv/bin/python -m playwright install chromium
/tmp/demoenv/bin/python scripts/make_demo_preview.py              # both videos (~4 min)
/tmp/demoenv/bin/python scripts/make_demo_preview.py --slide-only # just the slide clip
/tmp/demoenv/bin/python scripts/make_demo_preview.py --scene D    # one scene, for iteration
```
