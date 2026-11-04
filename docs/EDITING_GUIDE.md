# Editing guide: a narrated product demo, by hand, in an online editor

How `docs/demo/demo-preview.mp4` is edited, written so you can redo it, or edit any video of the same kind, in a browser
editor such as [OpenReel](https://openreel.video) (free, open source, no account). Sections 1 to 9 are about the craft and apply
to any editor. Section 10 is OpenReel's own controls. Section 11 says how to rebuild this exact video.

The video is built by `scripts/make_demo_preview.py`. This guide describes what that script does, so by hand you get the
same result. `docs/demo/edit-sheet.md` lists every beat with its start time, camera and highlight, and is generated from the
same code, so it cannot drift from the video.

## 1. What kind of video this is

A **voice-led screen demo**. The narration is a list of short sentences (beats). Each beat is one idea and has one picture.
Everything follows from three rules:

1. **The voice sets the clock.** A beat's picture lasts as long as its sentence, plus a short breath of 0.3 s. Never stretch
   the picture to fit a fancy move, and never speed up the voice.
2. **Something changes on every beat.** A new picture, a camera move, a callout or a highlight. The only still moments are
   the *holds* (section 5), and they are deliberate.
3. **Show it as it is said.** The callout lands on the keyword, the highlight appears when the camera arrives at its target,
   a number counts up as it is read out. Nothing appears before it is mentioned.

## 2. What to gather before you open the editor

| asset | where it comes from | notes |
|---|---|---|
| Screen recordings, clean | `docs/demo/footage/raw/{A,C,D,G}.mp4` | 3840 x 2160 (page 1920 x 1080 at 2x), nothing drawn on them. C is a tall page (3000 px) |
| Generated scene clips | `python scripts/make_demo_preview.py --keep DIR` writes `DIR/piece_<X>.mp4` | The animated scenes (problem, process, value, architecture, observability, recap) are code-built, so import these rather than redrawing them |
| Narration, one file per beat and one whole | `python scripts/export_edit_sheet.py --audio DIR` | `DIR/beats/<id>.wav`, and `DIR/narration.wav` already spaced with the holds and dissolves |
| Subtitles | `docs/demo/demo-preview.srt` | One caption per beat, timed to the narration |
| Beat sheet | `docs/demo/edit-sheet.md` | Start, length, camera, highlight, callout and hold for every beat |
| Logos | `~/.cache/asoia-demo-logos` (fetched by the build, not committed) | NVIDIA, Grafana, Deloitte. Use only the official files |

Set the throwaway environment up as in `docs/demo/README.md` ("Rebuild") before running the scripts.

## 3. Project setup

- **Canvas 1920 x 1080, 30 fps.** (OpenReel: *Start creating* under *Horizontal*, then check the **Aspect ratio** button reads 16:9.)
- **Tracks, top to bottom:** V4 callouts and badges, V3 highlights, V2 (spare, for a picture-in-picture), V1 footage and scene clips,
  Subtitle track, A1 narration, A2 music (optional).
- Turn **Snap** on (N in OpenReel) so clips and markers lock to each other.
- Turn on the title and action safe margins and the composition grid in the preview. Keep captions and callouts inside the safe margin.
- Drop `narration.wav` on A1 first. **Everything else is cut to it.**

## 4. The core skill: zooming in and out

Zoom is how a screen recording becomes a story. The aim is that the viewer can read what the narrator is talking about.

### 4.1 When to zoom
- **Zoom in on the thing named in the sentence**, a tile, a table row, a field, a graph. Zoom is a pointer, not decoration.
- **Zoom out to 1.00 x** (the whole frame) when a beat is about the whole screen, before a scene change, and at the end of a section.
- **No zoom** on a beat that only introduces the next one ("Now the manager asks the question that matters"). Hold the wide shot.
- One target per beat. A second target in the same beat is allowed only if the sentence names two things, and then the second
  move starts when the second word is spoken.

### 4.2 How far (the framing rule)
Frame the target's bounding box with padding, centred:

```
zoom = clamp( min( (1920 - 2*pad) / box_w ,  (1080 - 1.2*pad) / box_h ), 1.00, max )
```
- `box_w`, `box_h` are the target's size on the 1920 x 1080 screen at zoom 1.00; `pad` is breathing room, 60 to 200 px.
- **Max zoom:** 1.5 to 1.7 for a table or a form (text must stay in context), up to 2.3 for a single tile or number.
  Beyond about 2.5 the picture looks like a crop and the viewer loses where they are.
- Centre the box: the point at the middle of the box goes to the middle of the frame (1920/2, 1080/2) unless that would
  show beyond the edge of the recording, in which case stop at the edge. Never show the black void outside the screen.
- A **tall page** (a form 3000 px tall) is panned down at a steady zoom, usually 1.00 x, not zoomed and panned at once.

### 4.3 How to move: slow in, slow out
- Every move is a **glide with ease-in and ease-out**. A linear move looks mechanical; a snap looks like a cut.
- **Duration:** a glide uses almost the whole beat (a short beat, 2 to 4 s, glides for the whole of it). Keep the last 0.5 s still.
  Minimum 0.6 s for a move that has to happen quickly, such as a second target.
- **Start the move on the first word**, or on the keyword. If the target is not on screen yet (a result still loading), wait
  until it appears, then glide.
- **Never reverse inside a beat.** Zoom in and out only across beats.
- **Do not zoom while text is typing or a value is counting**, unless that is the point of the beat. The eye follows the typing.
- **Carry the state across beats.** The next beat's camera starts where the last one ended, so there is no jump at the cut.
  If two glides overlap, the later one wins from wherever the camera is.

If your editor only has linear keyframes, fake the ease with extra keyframes. Over a glide of length `D` from value `A` to `B`,
set keyframes at these fractions of `D` to these fractions of the distance `B - A` (a smoothstep):

| time | 0 | 0.10 D | 0.25 D | 0.50 D | 0.75 D | 0.90 D | D |
|---|---|---|---|---|---|---|---|
| distance covered | 0 | 0.03 | 0.16 | 0.50 | 0.84 | 0.97 | 1 |

Do this for scale **and** for position, with the same times, so the two arrive together. If the editor has an *ease in / ease out* or
*bezier* option on keyframes, use that and skip the table.

### 4.4 Turning a camera into editor numbers
The sheet gives each move as **zoom** (1.00 = the whole frame) and **page offset** `(x, y)`: where the top-left corner of the recording
sits on the 1920 x 1080 canvas. For a clip whose width fills the canvas at 100 %:

```
Scale (%)     = zoom * 100
Position X    = x + zoom * 960
Position Y    = y + zoom * clip_height_on_canvas / 2        (clip_height_on_canvas = 1080 for a normal page)
```
Position is the canvas point where the clip's centre sits. Check the panel: a clip centred on the canvas should read 960 and 540.
Check by eye: at zoom 1.00 the clip's edges touch the canvas edges; zoomed in, the target is centred and no black shows.

**Worked example** (beat A4, a tile 2.30 x): sheet says zoom 2.30, page offset (-37, 0). Scale 230 %; Position X = -37 + 2.30 * 960 = 2171;
Position Y = 0 + 2.30 * 540 = 1242.

A **tall page** such as the 3000 px ingest form: the clip is 1920 x 3000 in canvas pixels at zoom 1.00, so import it, set its scale so
its width is 1920 (about 278 % if the editor fits clips by height; check that the page edges meet the canvas edges), and use a
negative Y offset to slide down it: at zoom 1.00 a page offset of (0, -1229) shows the part of the page from 1229 px down.

## 5. Pacing and holds

- **Beat length = narration + 0.3 s breath (+ hold).** Place each clip so it starts with its sentence and ends with the breath.
- **Hold** = the picture stays still for 0.3 to 1.2 s after the sentence ends, so a key visual can be read. The sheet lists each one.
  Holds go on results (a flagged repair order, a cited answer, the last frame of a diagram), never on set-up beats.
- **Speed.** Footage may be played between 0.8 x and 1.6 x, and only to cut the wait for a slow system. Never retime the voice.
  Cut dead time (a spinner) rather than speeding the whole clip. Where the clip is shorter than the beat, hold its last frame
  (use *freeze frame* if the editor has it, or export a still and place it).
- **A frozen frame is fine for a static screen** (a dashboard being described): a still with a camera move reads as a live shot and
  avoids a cursor or a refresh flicker.
- **Total length:** keep to the budget in `docs/DEMO_VIDEO.md`. If you must cut, trim holds and lead-ins ("What does that change?") before
  you cut content.

## 6. Highlights (the green ring)

A highlight says "look here" and must **sit exactly on its target** at every frame. Specification:
- A rounded rectangle, 5 px outline in green `#76B900`, corner radius 10 px, no fill, a soft green glow around it.
- **Padding** 4 to 10 px around the target. It covers the whole thing described, such as a full row or a full card, not the first line.
- **Appears when the camera arrives**, fading in over 0.25 s, and stays until the end of the beat (or until the next target).
- **Pulses** gently: glow and brightness rise and fall once every 1.4 s. In an editor: keyframe Opacity 70 % to 100 % to 70 %
  over 1.4 s, repeated.
- **Moves with the camera.** If the target is in the recording, the ring is part of the recording's layer: group it with the clip or
  animate it with the same keyframes, so it never slides off.
- **Wait for the layout to settle.** If the screen is still rearranging (a panel that grows after it loads), start the ring after it stops.
  A ring on a moving target looks wrong.
- Only one ring at a time per beat, unless the sentence names several (then they appear one after another, as in the observability shot).
- Check every ring frame by frame at the start, middle and end of its beat. This is the most common visible mistake.

## 7. Callouts, badges and subtitles

**Callout** (the keyword): 1 to 3 words, bold white 50 px on a dark green plate (`#0a1e16` at 92 %), a 12 px green left border, rounded
corners, top left (about 16 px from the left, 10 from the top). It slides in 40 px from the left while fading in over 0.3 s, on the
keyword; it is replaced by the next beat's callout, never stacked. If it covers something important, move it, do not shrink the text.

**Badge** (the product named): a white pill at the top right with the product logo or logos and a short label, fading in 0.15 s into the beat.
Use logos only from official sources and at their correct colours.

**Subtitles:** import `docs/demo/demo-preview.srt` and style it once for the whole project:
- bold white, 32 px, centred, 16 px above the bottom edge, at most 1560 px wide;
- **transparent**: no background plate. Use a thin dark outline (about 1.5 px) and a soft shadow so it reads on both light app screens and dark scenes;
  a thick outline smears on light screens, so keep it thin;
- one caption per beat, never more than two lines, text exactly as spoken. Proofread numbers against the screen.

## 8. Transitions and structure

- **Hard cut** between beats of the same scene (the camera state carries over).
- **A 0.5 s cross-dissolve** between different screens: problem to dashboard, dashboard to process slide, slide to the ingest form, form to the
  assistant. It eases the viewer from one context to the next. No wipes, spins or other effects.
- **Open with a title card** (logo above the product name), which is also the thumbnail. Close on a recap that counts up its figures and
  ends on the tagline.
- **Structure of the narration:** problem, hook, how it works, the real thing live, what it changes, what it runs on, how it is watched, a recap.
- **Build-up diagrams** (the deployed architecture): show one part large, then shrink it back into the diagram, dimmed but on screen, while the next is
  shown; finish by pulling out to the whole frame. Draw an arrow, with a short label, for each data flow, as its layer appears.
- **Picture-in-picture** (the observability shot): a live screen recording at 48.96 % scale (940 px wide), top left at (930, 300), in a white rounded
  frame, fading in as its frame appears, with rings drawn over it at that small scale.

## 9. Audio

- One voice, one speed. Do not time-stretch it. Leave the 0.3 s breath after every sentence.
- Fade the narration in and out over 0.3 s at the very start and end. Keep it at a steady level: normalise the track to about -16 LUFS.
- **Music is optional.** If used, a quiet bed at least 18 dB under the voice, ducked further during speech, with a fade at both ends. Royalty-free only.
- No sound effects. Silence in the dissolves is fine.

## 10. OpenReel: where things are

Confirmed in the editor at `app.openreel.video` (the layout may change between versions; if a label differs, look for its sibling):

| task | where |
|---|---|
| New project | Home, *Start creating*, **Horizontal** (1920 x 1080) |
| Import clips, audio, SRT | left tab **Media**, *Import Media* (drag files in) |
| Titles, lower thirds, captions | left tab **Text** (Heading, Subtitle, Lower Third, Caption, Hero, Quote, Outline, Badge) |
| Shapes for rings | left tab **Graphics** (an outline-only rounded rectangle; if it has none, draw one in any image tool and import it as a PNG with a transparent background) |
| Dissolves | left tab **Transitions**, applied at the join of two clips (choose a cross dissolve, 0.5 s) |
| Zoom and pan | select the clip; right panel **Properties** > **Transform**: Position X/Y, Scale, Rotation, Anchor Point, Opacity |
| Keyframes | **Properties** > **Keyframes** > *Animate Property*, then pick Position X, Position Y, Scale X, Scale Y, Rotation or Opacity and press *Add Keyframe at <time>*; the top bar also has a **Keyframe editor** |
| Cut and trim | **S** split at the playhead, **Q** trim the start to the playhead, **W** trim the end, **Del** delete, **Shift+Del** ripple delete, **Cmd/Ctrl+D** duplicate |
| Snapping, in and out marks | **N** snap, **I** and **O** mark in and out |
| Speed | the clip's playback speed setting |
| Export | **Export**, MP4 (H.264), 1920 x 1080 or 4K, 30 fps |
| Aspect, zoom and safe margins in the preview | the buttons under the player: *Aspect ratio*, *Preview Zoom*, *Canvas snapping*, *Composition grid*, *Title and action safe margins* |

Notes. Scale X and Scale Y are separate keyframe properties: keyframe both with the same values. Easing choices for keyframes were not visible in the panel
when this was written; if there is none, use the smoothstep table in 4.3. The editor also has an AI mode (*AI editing*, bring your own model); the steps here are the manual mode.

## 11. Rebuilding this exact video, step by step

1. **Prepare.** Make the throwaway environment, run `python scripts/export_edit_sheet.py --audio ~/demo-kit` and
   `python scripts/make_demo_preview.py --keep ~/demo-kit/pieces`. You now have the narration, subtitles, the sheet and the scene clips.
2. **Create the project:** Horizontal, 1920 x 1080, 30 fps. Add the tracks in section 3.
3. **Lay the voice.** Drop `narration.wav` on A1 at 0:00. Add a marker at every beat start in `edit-sheet.md` (the *start* column).
4. **Lay the scenes.** Place each `piece_<X>.mp4` (the generated scenes: P, O, B, V, E, F, and the observability piece) on V1 at the start of its first
   beat. Use each piece with its picture only; keep A1 as the sound, and mute the piece's own audio.
5. **Rebuild the live scenes** (A dashboard, C ingest, D assistant) instead of the piece clips if you want to change them: import
   `footage/raw/<scene>.mp4`, place it at the beat's start, trim to the beat length, then do **steps 6 to 8 for each beat**.
6. **Camera.** Open the beat's row in `edit-sheet.md`. For each move listed: add keyframes for Scale and Position at the move's start and end (section 4.4),
   with the ease in 4.3. The first beat of a scene starts from zoom 1.00 and offset (0, 0).
7. **Highlight and callout.** Draw the ring (section 6) over the target, keyframed with the camera; add the callout (section 7) at its listed time.
8. **Hold.** Extend the last frame by the beat's hold.
9. **Dissolves.** Add a 0.5 s cross-dissolve at each scene change that the sheet shows with a half-second gap (before the dashboard, the process slide, the ingest form and the assistant).
10. **Subtitles.** Import `demo-preview.srt`, style it (section 7).
11. **Play it through at full screen with the safe margins on.** Check each ring, each callout, the numbers against the screen, then export (section 10).

## 12. Quality checklist

- [ ] The voice never overlaps itself and has its 0.3 s breath after each sentence.
- [ ] Every picture change lands on a sentence boundary, every callout on its keyword.
- [ ] No zoom beyond the limits; no black edge shows; text on screen is readable at the zoom used.
- [ ] Every glide eases in and out; no jump at a cut (the camera state carried over).
- [ ] Every ring covers all of its target at its first, middle and last frame, and does not pulse on a moving layout.
- [ ] Subtitles are transparent, inside the safe margin, and match the speech word for word.
- [ ] Numbers on screen match the narration (a count that rises during the video must be re-read on screen, not assumed).
- [ ] No keys, hostnames, tunnel addresses, or personal data visible in any frame.
- [ ] Logos are official and correctly coloured; no claim in the narration lacks a source (`docs/DEMO_VIDEO.md`, claims ledger).
- [ ] Exported at 1920 x 1080 (or 4K), 30 fps, H.264, audio about -16 LUFS, length within budget.

## 13. If something looks wrong

| symptom | cause and fix |
|---|---|
| A zoom looks jittery | Position and Scale keyframes on different times, or values rounded to whole pixels. Use the same times for both; use more keyframes (4.3) |
| The zoom looks soft | Source was scaled down before zooming. Use the 4K recordings; do not export a 1080p clip and zoom into it |
| A ring sits off its target | It was not grouped with the clip, or the layout moved after the ring was placed. Group it; place it after the layout settles |
| The picture drifts from the voice | A clip was stretched. Cut it to the sentence; trim dead time, do not change the voice speed |
| A callout covers the thing described | Move the callout; keep the text size |
| A number on screen disagrees with the narration | The recording changed after the script was written. Re-read the figure from the screen and change the sentence and the subtitle |
