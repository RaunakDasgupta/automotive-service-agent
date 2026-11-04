# How to edit a narrated product demo: a format guide for people and AIs

A self-contained specification for turning **screen recordings plus a use case** into a polished, voice-led product demo of about 2 to 3
minutes. It depends on no particular product, repository, tool or footage. Give it to an editor, a person or an AI agent, together with your
own footage and a filled-in brief (section 2), and they can produce the same kind of video: a problem hook, a live walk-through where every
feature is named, zoomed and highlighted as it is spoken, the impact in numbers, and a summary of strengths.

Nothing here assumes a particular editor. Section 11 maps the steps onto a browser editor (OpenReel) as an example.

---

## 0. How to hand this to an AI (read this first)

Give the AI three things: **this document**, **your brief** (section 2, filled in), and **your recordings** (or screenshots of them with timestamps).
Then use this prompt:

> Edit a demo video following the attached guide exactly. Inputs: the brief, and my recordings. Work in this order and show me each result before the next:
> (1) check the brief for gaps and ask me about any claim you cannot back; (2) write the beat script (section 4); (3) measure each target on screen and compute the
> camera for every beat with the framing function (section 6); (4) output the **edit decision list** in the exact schema of section 10; (5) only then build the video
> in the editor, and run the checklist in section 12. Do not add any claim, number or feature that is not in the brief.

An AI works best when it follows these rules, which the guide repeats where they matter:
- **Output the edit decision list (section 10) before editing.** It is the contract: a person can review it, and any tool can execute it.
- **Measure, do not guess.** Each target's box comes from the recording itself (a screenshot, or the page's layout), never from memory.
- **One source of truth for every number.** A figure in a caption, a callout and the narration comes from one place in the brief, and must match the screen.
- **If a rule and your taste disagree, follow the rule** and note the disagreement. Consistency is what makes it look professional.

---

## 1. What this kind of video is

A **voice-led screen demo**. The narration is a list of short sentences, called **beats**. Each beat is one idea with one picture. Three rules produce the style:

1. **The voice sets the clock.** A beat's picture lasts as long as its sentence plus a short breath (0.3 s). Never stretch the picture to fit a move and never speed up the voice.
2. **Something changes on every beat:** a new picture, a camera move, a callout, a highlight. The only still moments are deliberate **holds** (section 8).
3. **Show it as it is said.** The callout lands on the keyword, the highlight appears when the camera arrives, a figure counts up as it is read out. Nothing appears before it is mentioned.

### 1.1 The shape of the video (the same for any product)

| # | section | what the viewer sees | typical share |
|---|---|---|---|
| 1 | **Title card**, the first frame and the thumbnail | the sponsor or company logo above the product's short name, plus one line on the use case in general terms | 3 s |
| 2 | **The problem** | three or four simple pictures: where knowledge is lost, who is chasing answers, where the time goes, what risk hides in it | 10 to 15 s |
| 3 | **The hook** | the product is introduced as the answer ("That is where *<name>* comes in"), with a dissolve into the real product | 5 s |
| 4 | **How it works** | a process diagram built one stage at a time, each stage named as it appears | 15 to 20 s |
| 5 | **The real thing, live** | screen recordings of the actual product doing the work, in the order a user meets it: input, processing, result, then asking questions | 40 to 60 s |
| 6 | **Impact in numbers** | three or four large-figure cards, each a measured result | 10 to 15 s |
| 7 | **How it is built / deployed** | a layered architecture diagram, built part by part, with arrows for the data flow, ending on the whole picture | 12 to 18 s |
| 8 | **How it is watched** | a monitoring or observability diagram with the live dashboard inset and its key figures highlighted | 6 to 8 s |
| 9 | **Summary** | the product's three or four strengths, each a plain-language claim with one supporting figure, ending on the tagline | 15 to 20 s |

Drop a section that does not apply; keep the order. If there is no architecture story, sections 7 and 8 go. Do not add sections.

### 1.2 How features are highlighted (the pattern for every feature)

Every feature gets the same four moves in the same order. This is what makes the video read as a demonstration and not a tour:

1. **Name it:** a one to three word callout lands on the keyword in the sentence.
2. **Show it:** the camera glides to it, framed with room around it (section 6), and a green ring pulses on exactly what is meant.
3. **Prove it:** the result is held still for a moment (a flagged item, a cited answer, a number). Show the real output, not a mock-up.
4. **Tie it to the benefit** in the next sentence ("instantly", "no guessing", "in a tenth of a second"). The benefit is a fact from the brief, never an adjective.

---

## 2. The brief (fill this in, give it with the footage)

Everything the editor needs, and nothing else. An AI must refuse to invent anything that is not here.

```
PRODUCT
  full name:               ...
  short name (spoken):     ...        # easy to say, 2 to 4 words; the full name appears on screen only
  one line, general use:   ...        # for the title card: what it does for "any <kind of organisation>"
  sponsor / brand logo:    ...        # file, official and correctly coloured, or none
AUDIENCE:                  ...        # who watches, what they decide
PROBLEM (3 to 4 plain pictures, no statistics unless sourced)
  1. where information is lost:         ...
  2. who chases answers and how:        ...
  3. where the time goes:               ...
  4. what risk hides in it:             ...
FEATURES, in the order a user meets them (6 to 10)
  - name | what it does in a sentence | the keyword for the callout | where it is in the recording (file, time)
CLAIMS (every number the video may say)
  - claim | exact figure | where it is measured or from | on-screen in the recording? (yes/no)
PROCESS STAGES (3 to 5, for the "how it works" diagram)
  - stage | one-line description | the technology or method named, if any
ARCHITECTURE (optional): layers, parts in each layer, and the true data flow between them (what goes where)
OBSERVABILITY (optional): what is monitored, where the dashboard is, which 2 to 4 panels matter
TAGLINE:                   ...        # three short words or phrases, e.g. "Fast. Grounded. Yours."
LENGTH BUDGET:             ...        # total seconds
FOOTAGE
  - file | resolution | what it shows | useful time ranges | is any page taller than the screen? (yes/no)
CONSTRAINTS: what must not appear (keys, hostnames, personal data), what must not be claimed
```

**Claims discipline.** A claim is allowed in the video only if it is in CLAIMS with a source. "Faster", "better" and "saves hours" are not claims; **0.4 s per answer, median of 50 runs** and
**all 120 test answers traced to a source** are. If the figure on screen can change between recordings (a count that rises after a step in the demo), read it from the screen
at the moment it is shown, and put that figure in the narration.

---

## 3. Footage: what to capture so it can be edited well

- **Record at 2x the delivery size** (3840 x 2160 for a 1920 x 1080 video) and **draw nothing on it**: no cursor trails, rings, zooms or captions. All of that is added in editing,
  so it can be changed without recording again. Zooming into 2x footage stays sharp up to about 2.5 x.
- **One continuous take per step** of the demo, with a second of stillness at the start and after the result appears. Do not rely on a live pointer; click only what the story needs.
- **Show the result, not the wait.** Slow steps (a spinner, a model thinking) are cut in editing, but only if the take shows when the result arrived. Note the time.
- A **page taller than the screen** is recorded at its full height (a 3000 px page is a 3840 x 6000 video). The camera pans down it.
- **Keep the data consistent** across takes (the same record, the same numbers), and record a sequence in the order of the story, so the on-screen numbers agree with the narration.
- For each takes list: the time each action happens, the time the result appears, and **the box of every element you may want to zoom to** (x, y, width, height at 1x).

---

## 4. Writing the beats (the script)

The script is a table of beats. Write it before touching the footage.

| rule | detail |
|---|---|
| One idea per beat | One sentence, 5 to 18 words, 2 to 6 seconds spoken. Two ideas are two beats |
| Active, concrete, spoken | Short words. Read it aloud. No jargon the audience would not say, no "leverage", no "seamless" |
| The keyword is early or late, not buried | The callout lands on it, so put it at the start or end of the sentence |
| Numbers as the viewer will hear them | "seven of twelve", "under half a second". Put the digits in the caption, spell them for the voice if the voice engine misreads |
| Introduce, show, prove | A feature takes 1 to 3 beats: say what it is, show it, say what it did |
| The hook ties the problem to the product | The last problem beat ends on the risk; the next beat opens with "That is where *<short name>* comes in" |
| End on a summary of strengths | Three or four strengths, each named and backed by one figure from the brief (not a second wall of numbers), then the tagline, spoken once. Head it "Summary" |
| Sentence rhythm | Vary length; avoid three of the same shape in a row |
| Claims | Only from the brief |

Give each beat an id: a letter for its section and a number (`P1`, `A2`). Keep the ids stable when you edit; the schedule refers to them.

**Voice.** Use one voice, natural speed, never time-stretched. Generate or record each beat as its own file so each can be moved independently; put 0.3 s of silence after each.
Respell a word the voice mispronounces (spell out acronyms letter by letter in the audio script, keep the real spelling in the caption).

---

## 5. Timing

```
beat length = voice length + 0.3 s breath + hold
```
- Beats are laid back to back. A **cross-dissolve of 0.5 s** between two major screens adds 0.5 s of silence.
- **Holds** (0.3 to 1.2 s) go on proofs: a result, a figure, the last frame of a diagram. Not on set-up beats.
- The sum of beat lengths plus dissolves is the video length. If it exceeds the budget, **cut holds and lead-in phrases first, then whole beats; never speed the voice.**
- **Footage speed:** play recorded steps at 0.8 x to 1.6 x at most, and only to remove waiting. Prefer cutting out the dead time (a spinner) to speeding the clip.
- A **static screen** that is being described (a dashboard) works best as a **frozen frame** with a camera move: it reads as live, and has no flicker or pointer.

---

## 6. The camera: zooming in and out

The camera is a virtual crop of the recording, moved over the 1920 x 1080 frame. The aim is that the viewer can read what the narrator is talking about.

### 6.1 Where to point it
- **At the thing named in the sentence.** Zoom is a pointer, not decoration.
- **Out to 1.00 x (the whole frame)** for a beat about the whole screen, before a scene change, and at the end of a section.
- **Stay wide** on a beat that only introduces the next ("Now the manager asks the question that matters").
- **One target per beat.** A second is allowed only if the sentence names two things; the second move then starts when the second word is spoken.

### 6.2 How far: the framing function
Coordinates are in pixels of the 1920 x 1080 frame **at zoom 1.00**. A target is a box `(x, y, w, h)` (top-left corner and size); a page is `(page_w, page_h)`, normally `(1920, 1080)`.

```python
def frame(box, pad=80, max_zoom=2.4, page=(1920, 1080), prev=(1.0, 0.0, 0.0)):
    """The camera state (zoom, tx, ty) that frames box = (x, y, w, h). tx, ty is where the page's top-left corner sits on the 1920 x 1080 canvas."""
    px, py = pad, 0.6 * pad
    if box is None:                               # no target: ease about the centre of the frame (or pass a fixed zoom instead)
        z0, tx0, ty0 = prev
        z = min(z0 * 1.05, max_zoom)
        tx, ty = 960 - (960 - tx0) * z / z0, 540 - (540 - ty0) * z / z0
    else:
        x, y, w, h = box
        z = max(1.0, min(max_zoom, (1920 - 2 * px) / w, (1080 - 2 * py) / h))
        tx, ty = 960 - z * (x + w / 2), 540 - z * (y + h / 2)        # the target's centre goes to the centre of the frame
    tx = min(0.0, max(1920 - z * page[0], tx))    # never show beyond the page: no black edges
    ty = min(0.0, max(1080 - z * page[1], ty))
    return z, tx, ty
```

| decision | guidance |
|---|---|
| `pad` (breathing room) | 60 for a tight crop of a tile or number, 80 default, up to 200 for a small target that needs context |
| `max_zoom` | 1.5 to 1.7 for a table, form or text block (the text must stay in context); up to 2.3 for a single tile, number or field; never beyond 2.5 |
| A wide target (a full-width row) | the width limit decides the zoom, so the zoom comes out near 1.0; that is correct, add the ring |
| A tall page | pan down it at 1.00 x (or the zoom the width allows); do not zoom and pan down at once |
| Target near an edge | the clamp stops the camera at the page edge; the target then sits off-centre, which is fine |
| Two targets in one beat | frame the union box of both |

### 6.3 How to move: slow in, slow out
- Every move is a **glide with ease-in and ease-out**. A linear move looks mechanical; a snap looks like a cut.
- **Duration:** almost the whole beat (beat length minus 0.04 s); at least 0.6 s for a quick second move. The final 0.5 s of a beat is still.
- **Start on the first word**, or on the keyword if it is a second move. If the target is not on screen yet (a result loading), wait until it appears, then glide.
- **Never reverse inside a beat.** Zoom in and out across beats.
- **Carry the state:** the next beat's camera starts where the last ended, so there is no jump at a cut. If two glides overlap, the later one wins from wherever the camera is.
- **Do not move while text is typing or a value is counting**, unless that is the point of the beat.

**Easing by keyframes.** If the editor has only linear keyframes, add intermediate ones. For a glide of length `D` from `A` to `B`, put keyframes at these fractions of `D`, with this fraction of `B - A` covered
(a smoothstep, `u*u*(3 - 2*u)`):

| time | 0 | 0.10 D | 0.25 D | 0.50 D | 0.75 D | 0.90 D | D |
|---|---|---|---|---|---|---|---|
| fraction of the distance | 0 | 0.03 | 0.16 | 0.50 | 0.84 | 0.97 | 1 |

Use the same times for zoom, x and y so they arrive together. If the editor offers an *ease in-out* or *bezier* option on keyframes, use it and skip the table.

### 6.4 Turning a camera state into editor numbers
For a clip whose width fills the canvas at 100 % (the normal case):
```
Scale (%)  = zoom * 100
Position X = tx + zoom * 960
Position Y = ty + zoom * (clip height on the canvas at zoom 1.00) / 2        # 540 for a normal page; for a tall page, half its height
```
Position is the canvas point where the clip's centre sits (check: a centred clip reads 960, 540). Check by eye: at zoom 1.00 the clip's edges touch the canvas edges; zoomed in, the target is centred and no black shows.

*Example.* A tile at `(60, 100, 340, 120)` on a normal page, `pad = 80`, `max_zoom = 2.3`: `z = min(2.3, (1920 - 160)/340 = 5.2, (1080 - 96)/120 = 8.2) = 2.3`; `tx = 960 - 2.3*(60 + 170) = 431` clamped to `0`; `ty = 540 - 2.3*160 = 172` clamped to `0`. Scale 230 %, Position X = 0 + 2.3 * 960 = 2208, Y = 0 + 2.3 * 540 = 1242.

### 6.5 Picture-in-picture
To show a live dashboard beside a diagram: scale the recording to about half the canvas width (940 px, 48.96 %), place its top-left at (930, 300), put a white rounded frame 12 px around it, fade it in as the frame appears
(0.4 s), and draw the highlight rings over it at its small scale (their border stays 4 to 5 px, so they read).

---

## 7. Overlays

All overlay sizes are for a 1920 x 1080 canvas. Scale together if the canvas differs.

**Highlight ring** (the "look here")
- A rounded rectangle, 5 px outline in the accent colour (a strong green `#76B900` here; use your brand accent), corner radius 10 px, no fill, a soft glow around it.
- Padding 4 to 10 px beyond the target. It covers the **whole** thing meant: the full row, the full card, all the lines, not the first line.
- Appears when the camera arrives, fades in over 0.25 s, stays until the end of the beat or until the next target.
- Pulses once every 1.4 s: glow and brightness rise and fall. (Keyframe opacity 70 % to 100 % to 70 % over 1.4 s, repeated.)
- It is part of the recording's layer: it moves with the camera, so it never slides off. If the screen is still rearranging, **wait for it to settle** before placing the ring.
- One at a time, unless the sentence names several; then they appear one after another and stay.
- A ring in a picture-in-picture is placed after scaling, so its border stays readable.

**Callout** (the keyword)
- One to three words, bold white, 50 px, on a dark plate (near-black green, 92 % opaque), a 12 px accent bar on the left, rounded corners 6 px, soft shadow.
- Top left, about 16 px from the left edge and 10 px from the top. It slides in from 40 px to its left while fading in over 0.3 s, on the keyword.
- Replaced by the next beat's callout; never stacked. If it covers something important, move it, do not shrink the text.

**Badge** (the product or technology named)
- A white pill at the top right: the official logo(s) and a short label, 30 px bold, fading in 0.15 s into the beat. Use official logo files at their real colours; never recolour a brand mark.

**Captions** (optional: this format ships **without burned-in captions** and offers an SRT as a separate file; if you do burn them in, follow these rules)
- One caption per beat, the words exactly as spoken. Bold white, 32 px, centred, 16 px above the bottom edge, at most 1560 px wide, never more than two lines.
- **Transparent: no background plate.** A thin dark outline (about 1.5 px) and a soft shadow keep it readable on light and dark screens. A thick outline smears on light screens, so keep it thin.
- Proofread against the screen. Put the real spelling in the caption even if the voice needed a respelling.

**Counting figures.** In the impact cards the number counts up from 0 over about 0.9 s as it is spoken, and stops. In the summary, a figure is a small supporting chip under each strength. Decimals count with their decimals (0.0 to 0.1).

**Diagrams** (process, architecture, observability)
- **Process:** one stage per beat, each appearing as it is spoken, camera on the new stage; the last beat pulls back to show all stages.
- **Architecture:** layers in one frame, with the layer names in a gutter at the left so that no label crosses a card, and clear space between layers for arrows and their labels. Highlight the part being shown with a **soft glow, never a ring**: a ring sits on the part's own border and clashes with it. Do not add callouts to this diagram; each part is already labelled. Show one part large, then **shrink it back into the diagram, dimmed but still on screen**, while the next is shown; finish by pulling out to the whole frame with everything lit.
  Draw an **arrow with a short label** for each true data flow, as the layer it belongs to appears (for example *transcript*, *checked question*, *answer*). Only draw flows that are real.
- **Observability:** the sources (with their counts) into the collector into the dashboard; the live dashboard as an inset, with a ring on its primary figures and then on its key graphs, and a legend chip under the frame for each ring.

---

## 8. Transitions, holds and audio

- **Hard cut** between beats of the same scene (the camera state carries over).
- **Script the transition, not just the cut.** The first sentence of every section links to the one before ("Behind it, the deployed architecture...", "With the update recorded, a manager asks...", "And it is all observable..."). Do not open a section with an imperative ("Watch", "Look") or a bare "Now"; keep the register calm and formal.
- **A 0.5 s cross-dissolve** between different screens (diagram to live product, one app screen to another). No wipes, spins or other effects.
- **Open on the title card.** Its first frame is the thumbnail: logo, short name, one line. It is on screen from frame 0, not animated in.
- **Holds** as in section 5. **Hold the final frame** of the video for about 0.6 s after the last word.
- **Audio:** one voice at a steady level, about -16 LUFS; fade in and out over 0.3 s at the start and end; no sound effects; music optional, royalty-free, at least 18 dB under the voice and ducked during speech.

---

## 9. The procedure (for a person or an AI)

1. **Read the brief.** List every claim and check its source and whether the screen shows it. Ask about gaps.
2. **Write the beats** (section 4). Check the length with the timing rule (section 5).
3. **Voice the beats**, one file each, 0.3 s of silence after each. Measure each length.
4. **Lay out the timeline:** start of beat *n* = sum of the lengths of beats before it, plus 0.5 s for each dissolve before it.
5. **For each live beat:** pick the footage step; find the target box on screen at its first and last frame (it must be the same layout; if the screen is still settling, use the settled frame);
   compute the camera with the framing function; set the move's start and length; place the ring, callout and badge; decide the hold.
6. **Generated diagrams:** build or render the process, impact, architecture, observability and recap pictures as short clips; time their elements to the narration (a part appears when its word is spoken).
7. **Write the edit decision list** (section 10). Review it against the checklist before building.
8. **Build** the timeline in the editor, in this order: voice, pictures, camera, overlays, dissolves, audio levels, and the SRT as a separate file.
9. **Run the checklist** (section 12) with the playhead on the first, middle and last frame of every beat that has a ring, then at full screen. Fix, then export.

---

## 10. The edit decision list (the contract)

Produce this before editing. Times are seconds from the start of the video; coordinates are pixels of the 1920 x 1080 frame at zoom 1.00 (`box = [x, y, w, h]`).

```json
{
  "canvas": {"w": 1920, "h": 1080, "fps": 30},
  "style": {"accent": "#76B900", "dissolve": 0.5, "breath": 0.3},
  "beats": [
    {
      "id": "A2",
      "section": "live-demo",
      "start": 18.2,
      "narration": "A flagged job sits in a note that nobody has time to read.",
      "voice_seconds": 4.1,
      "hold": 0.0,
      "transition_in": {"type": "dissolve", "seconds": 0.5},
      "picture": {"kind": "recording", "file": "dashboard.mp4", "in": 12.0, "freeze": true, "speed": 1.0, "page": [1920, 1080]},
      "camera": [{"at": 0.0, "glide": 4.1, "zoom": 1.70, "offset": [-518, -325]}],
      "highlight": [{"at": 0.0, "box": [320, 410, 1180, 40], "pad": 8}],
      "callout": {"at": 0.0, "text": "Flagged jobs"},
      "badge": null
    }
  ],
  "captions": "none burned in; deliver one SRT entry per beat, text = narration"
}
```
Field rules:
- `picture.kind` is `recording`, `generated` (an animated diagram or card clip) or `still`.
- `camera` entries are glides: start `at` (seconds into the beat), length `glide`, target `zoom`, and `offset` = `[tx, ty]` from the framing function.
- `highlight` may be empty; `at` is when the camera has arrived. `callout.at` is the keyword's time in the sentence.
- Every beat has `start` and `voice_seconds`; the next `start` is this `start` + `voice_seconds` + `breath` + `hold` (+ any dissolve).
- Also output the same data as a markdown table (beat, start, length, narration, picture, camera, highlight, callout, hold) so a person can review it.

---

## 11. Executing it in an editor (example: OpenReel, a free browser editor)

Any editor with multiple tracks, keyframes on scale and position, text, subtitle import and cross-dissolves works. Labels below are from OpenReel's web app (`app.openreel.video`); they may differ between versions.

| task | where |
|---|---|
| New project | Home, *Start creating*, **Horizontal** (1920 x 1080); set 30 fps |
| Import clips, audio and the SRT | left tab **Media**, *Import Media* (or drag files in) |
| Titles, lower thirds, captions | left tab **Text** (Heading, Subtitle, Lower Third, Caption, Hero, Quote, Outline, Badge) |
| Shapes for rings | left tab **Graphics** (an outline-only rounded rectangle; if there is none, make one in any image tool and import it with a transparent background) |
| Dissolves | left tab **Transitions**, applied at the join of two clips |
| Zoom and pan | select the clip; right panel **Properties** > **Transform**: Position X/Y, Scale, Rotation, Anchor Point, Opacity |
| Keyframes | **Properties** > **Keyframes** > *Animate Property*, choose Position X, Position Y, Scale X, Scale Y, Rotation or Opacity, then *Add Keyframe at <time>*; the top bar also has a **Keyframe editor** |
| Cut and trim | **S** split, **Q** trim start to the playhead, **W** trim end, **Del** delete, **Shift+Del** ripple delete, **Cmd/Ctrl+D** duplicate; **N** toggles snap, **I** and **O** mark in and out |
| Preview aids | buttons under the player: *Aspect ratio*, *Preview Zoom*, *Canvas snapping*, *Composition grid*, *Title and action safe margins* |
| Export | **Export**: MP4 (H.264), 1920 x 1080 or 4K, 30 fps |

Notes. Scale X and Scale Y are separate keyframe properties: set both to the same value. No easing option was visible in the keyframe panel when this was written; use the smoothstep table in 6.3.
Tracks, top to bottom: callouts and badges, highlights, a spare for a picture-in-picture, the recordings and diagram clips, subtitles, narration, optional music. Turn snapping on so clips lock to the narration markers.
Order of work: drop the narration first and add a marker at each beat start from the edit decision list; every other clip is cut to those markers.

---

## 12. Checklist

- [ ] The voice never overlaps itself; each sentence has its 0.3 s breath; no beat is time-stretched.
- [ ] Every picture change lands on a sentence boundary; every callout on its keyword.
- [ ] Zoom stays within limits; no black edge shows; on-screen text is readable at the zoom used.
- [ ] Every glide eases in and out and starts where the last one ended; no jump at a cut.
- [ ] Each ring covers **all** of its target at its first, middle and last frame, and does not sit on a layout that is still moving.
- [ ] No captions are burned in; the SRT, if delivered, is exactly the spoken words (and if captions are burned in, they are transparent and inside the safe margin).
- [ ] Every number in the narration, callouts and cards is in the brief's CLAIMS and **matches the screen** at that moment.
- [ ] Every feature in the brief has been named, shown and proved (section 1.2); none outside the brief appears.
- [ ] The first frame is the title card (logo, short name, one line); the last beat holds on the tagline.
- [ ] No secrets, hostnames, addresses or personal data in any frame; logos are official and not recoloured.
- [ ] Exported at 1920 x 1080 (or 4K), 30 fps, H.264, audio about -16 LUFS, length within budget.

## 13. If something looks wrong

| symptom | cause and fix |
|---|---|
| A zoom looks jittery | zoom and position keyframes on different times, or values rounded to whole pixels. Use the same times for all, and the extra keyframes of 6.3 |
| The picture goes soft when zoomed | the source was scaled down before zooming. Edit from the 2x recordings |
| A ring sits off its target | it was not grouped with the clip, or the screen rearranged after it was placed. Group it; place it on the settled layout |
| The picture drifts from the voice | a clip was stretched. Cut it to the sentence; trim dead time, never change the voice speed |
| A callout covers what is described | move the callout; keep the text size |
| A number disagrees with the screen | the recording changed after the script was written. Read the figure from the screen and change the sentence and the caption |
| The video is too long | cut holds and lead-in words first (section 5), then whole beats |
| The summary repeats earlier cards word for word | name the strength and give one figure; the earlier cards were the evidence |

---

## Appendix: a tiny worked example (fictional)

*Product:* "RouteDesk", a scheduling tool for field-service teams. *Use case line:* "Turn every shift update into a clear next step, for any field team."

| id | beat | picture | camera | highlight | callout |
|---|---|---|---|---|---|
| P1 | Every field team runs on handovers. | title card (logo, "RouteDesk", the use-case line) | slow push-in to 1.05 x | none | none |
| P2 | A technician jots a note, then the shift ends. | two shift panels, a note crossing, half of it fading | none | none | Handover |
| P3 | And the real risk hides between shifts. | notes flying onto a grid, one stamped URGENT | none | none | none |
| A2 | An overdue job sits in a note nobody has time to read. | dashboard, one frozen frame | zoom 1.70 on the first table row | ring on the row | Overdue jobs |
| A3 | Right now, 7 jobs are overdue. | same frame | zoom 2.30 on the "Overdue" tile | ring on the tile | 7 overdue |
| A4 | That is where RouteDesk comes in. | dashboard, pulled back | glide to 1.00 x | none | RouteDesk |

Each row would become one entry in the edit decision list of section 10, with times, camera offsets from the framing function and the hold set on the proof beat (A3, 0.8 s).
