"""Write the edit sheet for the demo video: every beat with its start time, length, narration, picture, camera moves,
highlight and callout, plus subtitles (SRT) and, if asked, the narration audio per beat and in one file.

It reads the same script, timings, hold table and camera plan that scripts/make_demo_preview.py edits the video from
(camera_plan), so the sheet is the edit, not a description of it. Use it to rebuild the video by hand in an editor:
docs/EDITING_GUIDE.md says how.

    python scripts/export_edit_sheet.py                    # docs/demo/edit-sheet.md and docs/demo/demo-preview.srt
    python scripts/export_edit_sheet.py --audio DIR        # also DIR/beats/<id>.wav and DIR/narration.wav

Run it in the same throwaway environment as the video build (docs/demo/README.md). Narration is read from the voice cache
(~/.cache/asoia-demo-tts); a line that was never voiced needs the NVIDIA key, as in the build."""
import argparse
import shutil
import wave
from pathlib import Path

import make_demo_preview as m
from demo_footage import load_timeline

BRIDGE = 0.5                       # the soft dissolve before a piece in BRIDGE_BEFORE


def tc(t: float) -> str:
    return "%d:%04.1f" % (int(t // 60), t % 60)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def describe(cam, camo: dict) -> str:
    """How an in-page (generated) scene frames its picture, in words."""
    def one(d):
        return (d.get("sel") or 'text "%s"' % d.get("text")) if isinstance(d, dict) else str(d)
    if cam is None:
        return "ease to %.2f x" % camo["to"] if "to" in camo else "slow push in"
    parts = cam if isinstance(cam, list) else [cam]
    return "frame %s, up to %.2f x" % (" + ".join(one(d) for d in parts), camo.get("max", 2.4))


def main():
    ap = argparse.ArgumentParser(description="Write the demo's edit sheet and subtitles.")
    ap.add_argument("--audio", help="also write the narration here: <dir>/beats/<id>.wav and <dir>/narration.wav")
    ap.add_argument("--out", default=str(m.OUT), help="where the sheet and subtitles go (default docs/demo)")
    a = ap.parse_args()
    out = Path(a.out)

    script, tl = m.beats(), load_timeline()
    subs = dict(tl["subs"])

    def fill(t: str) -> str:
        for k, v in subs.items():
            t = t.replace(k, v)
        return t
    plans = {"P": m.scene_P(), "O": m.scene_O(), "B": m.scene_B(), "V": m.scene_V(), "E": m.scene_E(), "I": m.scene_I(), "F": m.scene_F(), "H": m.scene_brand(), "K": m.scene_brand()}

    rows, srt, now, first = [], [], 0.0, True
    wavs = []                                            # (path, seconds of voice+gap, hold, bridge before) for narration.wav
    for name, sc, ids in m.PIECES:
        piece = [r for r in script[sc] if ids is None or r[0] in ids]
        if name in m.BRIDGE_BEFORE and not first:
            wavs.append((None, 0.0, 0.0, BRIDGE)); now += BRIDGE
        first = False
        state = (1.0, 0.0, 0.0)
        if name == "K" and m.outro_file():
            cuts = " + ".join("%.2f-%.2f s" % c for c in m.OUTRO_CUTS)
            rows.append((name, "K1", now, m.outro_len(), "(none: the clip's own sound)", "the supplied Deloitte outro recording, playing stretches %s joined (the pause between them dropped)" % cuts,
                         "crop %d x %d at (%d, %d) of the recording, scaled to the full frame; last frame held %.1f s" % (*m.OUTRO_CROP, m.OUTRO_HOLD), "none", "none", m.OUTRO_HOLD))
            wavs.append((None, 0.0, m.outro_len(), 0.0)); now += m.outro_len()
            continue
        for k, (bid, text) in enumerate(piece):
            text = fill(text)
            wav, v = m.voice(text)
            hold = m.HOLD.get(bid, 0.0)
            nd = v + hold + (m.F_TAIL if name == "F" and k == len(piece) - 1 else 0.0)
            cam = ""
            if name in m.LIVE:
                plan = m.LIVE_PLAN[bid]
                stp = next(s for s in tl["scenes"][plan["src"][0]]["steps"] if s["id"] == plan["src"])
                page_h = tl["scenes"][plan["src"][0]].get("page", [m.W, m.H])[1]
                freeze = plan.get("freeze", False)
                out_t = m.time_map(stp, v, freeze)[3]
                moves, rings, cos, state_next = m.camera_plan(bid, plan, stp, v, v + hold, out_t, page_h, subs, state)
                cam = "<br>".join("+%.1f s, %.1f s glide: **%.2f x**, page offset (%d, %d)" % (t, d, s, tx, ty) for t, d, (s, tx, ty) in moves)
                state = state_next
                picture = "footage `%s` step %s%s%s" % (tl["scenes"][plan["src"][0]]["file"], plan["src"], " (one frozen frame)" if freeze else "",
                                                       "" if page_h == m.H else " (page %d px tall: the camera pans down it)" % page_h)
                hl = ", ".join("+%.1f s %s" % (t, n) for t, n, _ in rings if n) or "none"
                co = ", ".join("+%.1f s %s" % (t, c) for t, c in cos if c) or "none"
                if plan.get("badge"):
                    co += " · badge %s" % m.BADGES[plan["badge"]][1]
            else:
                p = plans[name][k] if k < len(plans[name]) else {}
                picture = "generated scene %s" % name
                cam = describe(p.get("cam"), p.get("camo", {}))
                ring = p.get("ring")
                hl = (ring.get("sel") or ring.get("text") if isinstance(ring, dict) else "none") if ring else "none"
                co = p.get("co") if isinstance(p.get("co"), str) else "none"
            rows.append((name, bid, now, nd, text, picture, cam, hl, co or "none", hold))
            srt.append((now, now + v - m.GAP, text))
            wavs.append((wav, v, hold, 0.0))
            now += nd
    total = now

    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Edit sheet — demo-preview.mp4", "",
             "Generated by `scripts/export_edit_sheet.py` from the same script, timings and camera plan the video is built from. "
             "Total **%s**. Times are from the start of the video. **Zoom** 1.00 x shows the whole 1920 x 1080 frame. **Page offset** is "
             "where the top-left corner of the screen recording sits on the 1920 x 1080 canvas at that zoom (so it is negative once "
             "you zoom in). A glide is smooth, slow-in slow-out (see `docs/EDITING_GUIDE.md` section 4). If two glides in a beat overlap, "
             "the later one wins: the camera heads for its value from wherever it is." % tc(total), ""]
    cur = None
    for name, bid, t0, nd, text, picture, cam, hl, co, hold in rows:
        if name != cur:
            cur = name
            lines += ["", "## Piece %s" % name, "", "| beat | start | length | narration | picture | camera | highlight | callout | hold |", "|---|---|---|---|---|---|---|---|---|"]
        lines.append("| %s | %s | %.1f s | %s | %s | %s | %s | %s | %.1f s |" % (bid, tc(t0), nd, text.replace("|", "/"), picture, cam, hl, co, hold))
    (out / "edit-sheet.md").write_text("\n".join(lines) + "\n")
    (out / "demo-preview.srt").write_text("".join("%d\n%s --> %s\n%s\n\n" % (i + 1, srt_time(a_), srt_time(b_), t) for i, (a_, b_, t) in enumerate(srt)))
    print("wrote %s and %s: %d beats, %s" % (out / "edit-sheet.md", out / "demo-preview.srt", len(rows), tc(total)))

    if a.audio:
        d = Path(a.audio)
        (d / "beats").mkdir(parents=True, exist_ok=True)
        for (name, bid, *_), (wav, *_r) in zip(rows, [w for w in wavs if w[0]]):
            shutil.copy(wav, d / "beats" / (bid + ".wav"))
        with wave.open(str(d / "narration.wav"), "wb") as o:
            o.setnchannels(1); o.setsampwidth(2); o.setframerate(m.RATE)
            for wav, v, hold, bridge in wavs:
                if wav:
                    with wave.open(str(wav)) as w:
                        o.writeframes(w.readframes(w.getnframes()))
                o.writeframes(b"\0\0" * int(m.RATE * (hold + bridge)))
        print("wrote the narration to %s" % d)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(m.WORK, ignore_errors=True)
