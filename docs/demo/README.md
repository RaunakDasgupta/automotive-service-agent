# Demo video

Two files, both recorded from the real application:

| file | what it is |
|---|---|
| `process-slide-preview.mp4` | The animated process slide on its own (~7.5 s): the five stages only, with no business figures |
| `demo-preview.mp4` | The whole demo (2:37): 35 voiced beats from `docs/DEMO_VIDEO.md`, at the voice's natural pace |
| `footage/` | The live application as recorded on the L40S box, **raw**: `raw/{A,C,D,G}.mp4` (3840x2160, nothing drawn on it) and `timeline.json` (time windows, clicks, and where every target is on screen). The video is edited from these alone, so **the box is not needed again until the app's screen changes** |

## What is on screen

| scene | what you see |
|---|---|
| Title and problem | the first frame is a title card, the **Deloitte logo** above the title *Service Operations Agent* and the line *From first update to final answer: one connected view of service operations* (it is the thumbnail). Then the problem in three pictures: a shift handover that loses the detail, a manager chasing answers across notes, calls and screens, and the time that goes on it. It ends on shift notes flying onto a moving grid, one stamped SAFETY, and a soft dissolve into the live dashboard |
| H Brand preface | a soft dissolve from the stamped notes to a white panel with the **Deloitte** and **NVIDIA** logos side by side, *The solution, powered by* above and *Service Operations Agent* below (*Here is the solution, powered by Deloitte and NVIDIA.*) |
| A Solution: the live view | the **live** dashboard, introduced as part of the solution (*This is where the Service Operations Agent comes in*) and shown as one live view built from every update, with the flagged-vehicles tile ringed; entered by a soft dissolve from the stamped notes |
| B Process | a soft dissolve from the dashboard, then the process slide, **rendered from the deck's own XML** and built stage by stage as each is spoken, ending on the whole five-stage flow (not PowerPoint, so fonts differ slightly). The deck slide itself is process only now (no business figures); they have their own segment |
| C Ingest | **live**, entered by a soft dissolve from the process slide: a spoken update is uploaded, Riva transcribes it, Nemotron extracts the measurement, the rules flag the repair order `SAFETY_RELATED` |
| D Ask | **live**: a soft dissolve from the form, then a structured question answered with no model call and a free-text question answered by search + rerank + narration on the local NIMs |
| V Business value | four cards: unsafe vehicles surfaced (read from the live dashboard), `0.1 s` answers, `905 / 905` traced answers, one update feeding the whole shop. No cost or speed-up claim is made |
| E Deployed architecture | a layered diagram in one frame: the L40S chip with the three NIM tiles and a memory bar (about 30 of 46 GB), speech (Riva) and safety (NeMo Guardrails) above it, quality (NeMo Evaluator) on top. Row names sit in a left gutter and the part being shown glows (no ring on its own border). Each layer is shown in turn with arrows for its data flow (the transcript to the language model, a checked question in and a checked answer out through the rails, test questions in and scored answers back for the evaluator), then shrinks back, dimmed but still on screen, as the next is shown; at the end the camera pulls out to the whole frame |
| G Observability | an infographic, the DCGM exporter (19 GPU series) and the app (13 series) feeding Prometheus and Grafana, with the **live** Grafana dashboard playing small in a frame beside it (after real traffic through `/ask`). Rings light up its primary figures, then the two DCGM graphs (GPU load and power), each with a legend chip |
| F Summary | the application's strengths as four cards (*Safety first*, *Instant answers*, *Grounded in records*, *Yours to run*), each with one supporting figure, ending on *Fast. Grounded. Yours to run.* with the product name beneath it |
| K Closing card | after the summary, a soft dissolve to the product name over the same Deloitte and NVIDIA panel with *Powered by Deloitte and NVIDIA* beneath, held a moment (the video ends here) |

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
what is described, and no captions are burned in (`demo-preview.srt` carries them as a separate file). Hard cuts between scenes. No music is mixed in; a quiet
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
   The camera is a sub-pixel zoom and pan (ffmpeg `perspective`, evaluated per frame) and the ring pulse is a smooth blend, so
   nothing steps or shimmers; scale-and-overlay snapped to even pixels and did.

A box is needed again **only when what the app puts on screen changes**. Each scene is stamped with a fingerprint of the app
code, the Grafana dashboard and the inputs typed into it. `python scripts/demo_footage.py --check` (the edit prints the
same verdict) says whether the footage still matches; if code changed but the screen did not, `--restamp` accepts it.

## The voice

Narrated by **NVIDIA Riva Magpie TTS** (voice `Magpie-Multilingual.EN-US.Sofia`) at 44.1 kHz, using the project's key,
at natural speed with beats padded by 0.3 s. Results are cached in `~/.cache/asoia-demo-tts`. The narration is read
straight from `docs/DEMO_VIDEO.md`, so editing the script and re-running regenerates the video. Whether this voice is
good enough for clients is a judgement for your ears; the alternative in the plan is ElevenLabs.

## Editing it by hand

`docs/EDITING_GUIDE.md` is a **generic** guide to editing a narrated product demo in this format (it names no product, tool or repository, and is written to be handed to an
AI together with a filled-in brief and the footage). This section is the kit for **this** video.

| asset | how to get it |
|---|---|
| Clean 4K recordings, nothing drawn on them | `docs/demo/footage/raw/{A,C,D,G}.mp4` (`C` is a 3000 px tall page) |
| Every beat: start, length, narration, camera (zoom and page offset), highlight, callout, hold | `docs/demo/edit-sheet.md` (generated; the guide's edit decision list in table form) |
| Subtitles, one per beat | `docs/demo/demo-preview.srt` |
| Narration, one file per beat and one spaced file | `python scripts/export_edit_sheet.py --audio DIR` (`DIR/beats/<id>.wav`, `DIR/narration.wav`) |
| The animated scenes as clips (title and problem, process, value, architecture, observability, recap) | `python scripts/make_demo_preview.py --keep DIR` (`DIR/piece_<X>.mp4`) |

Regenerate the sheet and subtitles with `python scripts/export_edit_sheet.py` after any change to the script or timings; they come from the same camera plan the build uses.

To redo it in an editor: put `narration.wav` on the audio track first and mark each beat's start from `edit-sheet.md`; place the `piece_<X>.mp4` clips for the animated scenes (muting their own
audio); for the live scenes (A dashboard, C ingest, D assistant) place `footage/raw/<scene>.mp4`, trim to the beat, and apply each move of the sheet as Scale and Position keyframes (the
guide's sections 6.3 and 6.4 turn a zoom and page offset into editor numbers); add the rings, callouts and badges at the listed times, the holds, a 0.5 s dissolve before every scene after the opening (the `BRIDGE_BEFORE` pieces in `scripts/make_demo_preview.py`; `edit-sheet.md` shows each as a half-second gap),
and import the SRT if you want captions. The observability shot is the Grafana recording (`G.mp4`) as a picture-in-picture (guide 6.5) inside its diagram piece.

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
from their public brand assets into `~/.cache/asoia-demo-logos` and are not committed. The Deloitte logo comes from Wikimedia Commons, which has the older blue wordmark; it is recoloured to the current black with Deloitte green on first fetch. To use the official file instead, put it at `~/.cache/asoia-demo-logos/deloitte.svg` before building.

The captions keep the real spelling; where the voice gets a word wrong it is given a respelling (`SPOKEN` in the script): *read* in the present tense, and *DCGM* spelled out letter by letter.
