#!/usr/bin/env python
"""Build the demo-video PREVIEW: docs/demo/process-slide-preview.mp4 and demo-preview.mp4.

    python scripts/make_demo_preview.py [--slide-only]

Run it with an interpreter that has `playwright`, `imageio-ffmpeg` and
`nvidia-riva-client` - deliberately NOT project dependencies, so put them in a throwaway
venv (`python -m venv /tmp/demoenv && /tmp/demoenv/bin/pip install playwright
imageio-ffmpeg nvidia-riva-client && /tmp/demoenv/bin/python -m playwright install
chromium`), then run this from the project root with that interpreter.

WHAT IT IS, AND IS NOT

A preview to judge pacing, layout and wording - not the client cut. Every app scene is
recorded from the LOCAL app, against a COPY of the dataset (the real database is never
written), so what cannot run on a laptop is not shown:

  * the process slide is rendered from the deck's own XML (positions, text, colours and
    the animation timing), not by PowerPoint - fonts and anti-aliasing differ;
  * scene 3 logs the measurement through the structured form, because dictation needs the
    hosted ASR and the GPU model; scene 4 shows the structured answer only, because the
    semantic answer needs the NIMs and Milvus;
  * scene 5 uses stills captured on the L40S (docs/screenshots), not live Grafana/Attu.

The narration is read from docs/DEMO_VIDEO.md, the single source of truth, and voiced by
NVIDIA Riva Magpie TTS at 44.1 kHz with the key from .env (never printed).
"""
from __future__ import annotations

import argparse, base64, json, os, re, shutil, subprocess, sys, tempfile, time, wave, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
OUT = ROOT / "docs" / "demo"
WORK = Path(tempfile.mkdtemp(prefix="asoia-demo-"))
W, H, FPS = 1920, 1080, 30
LEAD, TAIL = 0.5, 0.9            # silence before the voice starts, and after it ends
VOICE, RATE = "Magpie-Multilingual.EN-US.Sofia", 44100
APP_PY = ROOT / ".venv" / "bin" / "python"

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError("%s failed:\n%s" % (cmd[0], r.stderr[-600:]))
    return r


# ------------------------------------------------------------------ the script
def scenes():
    """(number, window, narration) from the table in docs/DEMO_VIDEO.md."""
    out = []
    for line in (ROOT / "docs" / "DEMO_VIDEO.md").read_text().splitlines():
        m = re.match(r"\| (\d) \| ([\d:–]+) \| (.+?) \| (.+) \|$", line)
        if m:
            out.append((int(m.group(1)), m.group(2), m.group(3)))
    assert len(out) == 6, "expected six scenes in docs/DEMO_VIDEO.md, found %d" % len(out)
    return out


# ------------------------------------------------------------------ voice
def tts(text: str, path: Path) -> float:
    import _env  # noqa: F401  - .env like stack.sh; the key is never printed
    import riva.client as rc
    auth = rc.Auth(uri="grpc.nvcf.nvidia.com:443", use_ssl=True, metadata_args=[
        ["function-id", "877104f7-e885-42b9-8de8-f6e4c6303969"],
        ["authorization", "Bearer " + os.environ["NVIDIA_API_KEY"]]])
    r = rc.SpeechSynthesisService(auth).synthesize(
        text, voice_name=VOICE, language_code="en-US", sample_rate_hz=RATE,
        encoding=rc.AudioEncoding.LINEAR_PCM)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(r.audio)
    return len(r.audio) / 2 / RATE


# ------------------------------------------------------------------ the slide, from its own XML
def slide_html(pptx: Path, marker: str = "anim-s0-card") -> tuple[str, float]:
    """Render the deck slide that holds `marker` as HTML with its animation timing."""
    z = zipfile.ZipFile(pptx)
    name = next(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)
                and marker.encode() in z.read(n))
    root = ET.fromstring(z.read(name))
    k = W / 12192000                      # EMU -> px;  1 pt = 2 px at this size
    shapes, ids = [], {}
    for sp in root.iter("{%s}sp" % NS["p"]):
        c = sp.find("p:nvSpPr/p:cNvPr", NS)
        xf = sp.find("p:spPr/a:xfrm", NS)
        if xf is None:
            continue
        off, ext = xf.find("a:off", NS), xf.find("a:ext", NS)
        x, y, w, h = (int(off.get("x")) * k, int(off.get("y")) * k,
                      int(ext.get("cx")) * k, int(ext.get("cy")) * k)
        pg = sp.find("p:spPr/a:prstGeom", NS)
        geom = pg.get("prst", "rect") if pg is not None else "rect"
        fill = sp.find("p:spPr/a:solidFill/a:srgbClr", NS)
        ln = sp.find("p:spPr/a:ln", NS)
        lnc = ln.find("a:solidFill/a:srgbClr", NS) if ln is not None else None
        lw = max(1.0, int(ln.get("w", "12700")) * k) if lnc is not None else 0
        css = ["left:%.1fpx" % x, "top:%.1fpx" % y, "width:%.1fpx" % w, "height:%.1fpx" % h]
        if fill is not None:
            css.append("background:#" + fill.get("val"))
        if lw:
            css.append("border:%.1fpx solid #%s" % (lw, lnc.get("val")))
        if geom == "ellipse":
            css.append("border-radius:50%")
        if geom in ("rightArrow", "downArrow"):
            pts = ("0 25%,60% 25%,60% 0,100% 50%,60% 100%,60% 75%,0 75%" if geom == "rightArrow"
                   else "25% 0,75% 0,75% 60%,100% 60%,50% 100%,0 60%,25% 60%")
            css.append("clip-path:polygon(%s)" % pts)
        body = sp.find("p:txBody", NS)
        inner = ""
        if body is not None:
            bp = body.find("a:bodyPr", NS)
            anchor = {"t": "flex-start", "ctr": "center", "b": "flex-end"}.get(bp.get("anchor", "t"), "flex-start")
            pad = [int(bp.get(i, d)) * k for i, d in (("tIns", 45720), ("rIns", 91440), ("bIns", 45720), ("lIns", 91440))]
            paras = []
            for p in body.findall("a:p", NS):
                ppr = p.find("a:pPr", NS)
                algn = {"l": "left", "ctr": "center", "r": "right"}.get(ppr.get("algn", "l") if ppr is not None else "l", "left")
                ls = ppr.find("a:lnSpc/a:spcPct", NS) if ppr is not None else None
                sb = ppr.find("a:spcBef/a:spcPts", NS) if ppr is not None else None
                pst = "text-align:%s;line-height:%.2f;" % (algn, 1.2 * (int(ls.get("val")) / 100000 if ls is not None else 1))
                if sb is not None:
                    pst += "margin-top:%.1fpx;" % (int(sb.get("val")) / 100 * 2)
                runs = ""
                for el in p:
                    tag = el.tag.split("}")[1]
                    if tag == "br":
                        runs += "<br>"
                    elif tag == "r":
                        rp, t = el.find("a:rPr", NS), el.findtext("a:t", "", NS)
                        col = rp.find("a:solidFill/a:srgbClr", NS) if rp is not None else None
                        face = rp.find("a:latin", NS) if rp is not None else None
                        st = "font-size:%.1fpx;" % (int(rp.get("sz", "1800")) / 100 * 2 if rp is not None else 36)
                        st += "font-weight:bold;" if rp is not None and rp.get("b") == "1" else ""
                        st += "font-style:italic;" if rp is not None and rp.get("i") == "1" else ""
                        st += "color:#%s;" % col.get("val") if col is not None else ""
                        st += "font-family:'%s',Calibri,'Helvetica Neue',Arial,sans-serif;" % (face.get("typeface") if face is not None else "Calibri")
                        runs += '<span style="%s">%s</span>' % (st, t.replace("&", "&amp;").replace("<", "&lt;"))
                paras.append('<div style="%s">%s</div>' % (pst, runs or "&nbsp;"))
            inner = ('<div style="display:flex;flex-direction:column;justify-content:%s;height:100%%;'
                     'padding:%.1fpx %.1fpx %.1fpx %.1fpx;box-sizing:border-box">%s</div>' % ((anchor, *pad, "".join(paras))))
        shapes.append((c.get("id"), '<div class="sh" data-id="%s" style="%s">%s</div>' % (c.get("id"), ";".join(css), inner)))
        ids[c.get("id")] = c.get("name")
    anims = []
    for ct in root.iter("{%s}cTn" % NS["p"]):
        if ct.get("presetClass") != "entr":
            continue
        spid = ct.find(".//p:spTgt", NS).get("spid")
        flt = ct.find(".//p:animEffect", NS)
        anims.append([spid, int(ct.find("p:stCondLst/p:cond", NS).get("delay")),
                      flt.get("filter"), int(flt.find("p:cBhvr/p:cTn", NS).get("dur"))])
    total = max(d + dur for _, d, _, dur in anims) / 1000
    html = """<!doctype html><meta charset=utf-8><style>
html,body{margin:0;background:#fff}#s{position:relative;width:%dpx;height:%dpx;overflow:hidden;background:#fff}
.sh{position:absolute;box-sizing:border-box;opacity:1}</style><div id=s>%s</div><script>
const A=%s;const START=700;
for(const [id,delay,f,dur] of A){const el=document.querySelector('[data-id="'+id+'"]');
 const own=el.style.clipPath;  // an arrow already has a clip: wipe it by collapsing the polygon, not by replacing it
 const wipeFrom=own?own.replace(/polygon\\((.*)\\)/,(m,pts)=>'polygon('+pts.split(',').map(q=>'0%% '+q.trim().split(' ')[1]).join(',')+')'):'inset(0 100%% 0 0)';
 const wipeTo=own||'inset(0 0 0 0)';
 const from=f.startsWith('wipe')?{clipPath:wipeFrom,opacity:1}:{opacity:0};
 const to=f.startsWith('wipe')?{clipPath:wipeTo,opacity:1}:{opacity:1};
 Object.assign(el.style,from);el.animate([from,to],{duration:dur,delay:START+delay,fill:'both',easing:'ease-out'});}
</script>""" % (W, H, "".join(h for _, h in shapes), json.dumps(anims))
    return html, total + 0.7


# ------------------------------------------------------------------ recording
CHROME_JS = r"""
(() => {
  const css = document.createElement('style');
  css.textContent = `#__cap{position:fixed;left:0;right:0;bottom:10px;text-align:center;z-index:99999;pointer-events:none}
  #__cap span{display:inline-block;max-width:1500px;background:rgba(10,20,16,.82);color:#fff;font:600 30px/1.3 Arial,sans-serif;
    padding:8px 24px;border-radius:10px}
  #__tag{position:fixed;top:18px;right:20px;z-index:99999;background:#C1562A;color:#fff;font:700 18px Arial;padding:6px 14px;border-radius:20px;pointer-events:none}
  #__cur{position:fixed;width:26px;height:26px;border-radius:50%;background:rgba(118,185,0,.55);border:3px solid #76B900;z-index:100000;pointer-events:none;
    transform:translate(-50%,-50%);transition:transform .08s}`;
  document.head.appendChild(css);
  const cap = document.createElement('div'); cap.id='__cap'; document.body.appendChild(cap);
  const tag = document.createElement('div'); tag.id='__tag'; tag.textContent = window.__TAG || 'PREVIEW'; document.body.appendChild(tag);
  const cur = document.createElement('div'); cur.id='__cur'; cur.style.left='-100px'; document.body.appendChild(cur);
  addEventListener('mousemove', e => { cur.style.left=e.clientX+'px'; cur.style.top=e.clientY+'px'; });
  addEventListener('mousedown', () => cur.style.transform='translate(-50%,-50%) scale(.7)');
  addEventListener('mouseup', () => cur.style.transform='translate(-50%,-50%) scale(1)');
  window.__captions = (caps, tag) => { if (tag) document.getElementById('__tag').textContent = tag;
    caps.forEach(([t, s]) => setTimeout(() => { cap.innerHTML = s ? '<span>'+s+'</span>' : ''; }, t)); };
})();
"""


def sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def caption_times(text: str, audio_s: float):
    """(ms, sentence) pairs, spread over the audio in proportion to word count."""
    ss, tot, t, out = sentences(text), len(text.split()), LEAD, []
    for s in ss:
        out.append((int(t * 1000), s))
        t += audio_s * len(s.split()) / tot
    out.append((int((LEAD + audio_s + 0.3) * 1000), ""))
    return out


def record_scene(pw, n: int, url: str, dur: float, caps, tag: str, actions=None, size=(W, H)) -> Path:
    """Record `dur` seconds of `url`; actions(page) runs from the moment captions start."""
    vdir = WORK / ("v%d" % n)
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]},
                              record_video_dir=str(vdir), record_video_size={"width": size[0], "height": size[1]})
    page = ctx.new_page()
    t_ctx = time.time()
    page.goto(url, wait_until="load", timeout=90000)
    page.wait_for_timeout(2500)
    page.add_script_tag(content=CHROME_JS)
    page.wait_for_timeout(300)
    t0 = time.time()
    page.evaluate("([c,t]) => window.__captions(c,t)", [caps, tag])
    if actions:
        actions(page)
    left = dur - (time.time() - t0)
    if left > 0:
        page.wait_for_timeout(int(left * 1000))
    start = t0 - t_ctx
    ctx.close(); browser.close()
    webm = next(vdir.glob("*.webm"))
    out = WORK / ("scene%d.mp4" % n)
    run(ffmpeg(), "-y", "-ss", "%.2f" % start, "-i", webm, "-t", "%.2f" % dur, "-vf",
        "scale=%d:%d:flags=lanczos,fps=%d" % (W, H, FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "22", "-preset", "veryfast", "-an", out)
    return out


def mux(video: Path, wav: Path | None, dur: float, out: Path):
    if wav is None:
        shutil.copy(video, out); return
    run(ffmpeg(), "-y", "-i", video, "-i", wav, "-filter_complex",
        "[1:a]adelay=%d|%d,apad,atrim=0:%.2f[a]" % (LEAD * 1000, LEAD * 1000, dur), "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % dur, out)


def concat(parts, out: Path):
    lst = WORK / "list.txt"
    lst.write_text("".join("file '%s'\n" % p for p in parts))
    run(ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out)


# ------------------------------------------------------------------ local app
def start_ui(tab: str, port: int, db: Path):
    env = dict(os.environ, ASOIA_DB=str(db), ASOIA_UI_TAB=tab, PORT=str(port), ASOIA_METRICS="0",
               SHARE="0", PYTHONDONTWRITEBYTECODE="1", ASOIA_LOG_ANSWERS="0")
    p = subprocess.Popen([str(APP_PY), "-m", "app.ui.gradio_app"], cwd=ROOT, env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import urllib.request
    for _ in range(90):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d" % port, timeout=2).read(1); return p
        except Exception:
            time.sleep(1)
    raise RuntimeError("UI on %d did not come up" % port)


def stop(p):
    try:
        os.killpg(p.pid, 9)
    except Exception:
        pass


def pick(page, nth_input: int, nth_option: int):
    page.locator("input[role=listbox], .wrap input").nth(nth_input).click()
    opt = page.locator("li[role=option], ul[role=listbox] li").nth(nth_option)
    opt.wait_for(state="visible", timeout=15000)
    opt.click()
    page.wait_for_timeout(450)


def scene3(page):                                    # Technician Update: log the measurement
    page.wait_for_timeout(500)
    pick(page, 0, 3)
    pick(page, 1, 1)
    page.get_by_label("Measurement").fill("front_pad_thickness"); page.wait_for_timeout(350)
    page.get_by_label("Value", exact=True).fill("1.8"); page.wait_for_timeout(350)
    page.get_by_label("Spec minimum").fill("3.0"); page.wait_for_timeout(500)
    page.get_by_role("button", name="Submit structured update").click()
    page.wait_for_timeout(1800)
    page.mouse.wheel(0, 430); page.wait_for_timeout(1500)


def scene4(page):                                    # Manager Assistant: the safety question
    page.wait_for_timeout(1500)
    box = page.get_by_label("Question")
    box.click(); page.keyboard.type("Which vehicles cannot be released on safety grounds?", delay=45)
    page.wait_for_timeout(600)
    page.get_by_role("button", name="Ask", exact=True).click()
    page.wait_for_timeout(5000)


def scene1(page):                                    # Dashboard: let the numbers be read, then scroll the table
    page.wait_for_timeout(5500)
    for _ in range(3):
        page.mouse.wheel(0, 260); page.wait_for_timeout(1300)


# ------------------------------------------------------------------ html scenes
def b64(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def components_html(dur: float) -> str:
    chips = [("NIM · Nemotron 8B", "language"), ("NIM · Embedding", "search"), ("NIM · Reranking", "search"),
             ("Riva · Parakeet ASR", "speech (hosted)"), ("NeMo Guardrails", "safety rails"),
             ("NeMo Evaluator", "release scoring"), ("DCGM", "GPU telemetry")]
    shots = ROOT / "docs" / "screenshots"
    at = [1.2 + i * (dur - 4.5) / len(chips) for i in range(len(chips))]
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;background:#14302A;font-family:Arial,sans-serif;color:#fff;overflow:hidden}
h1{position:absolute;left:70px;top:46px;margin:0;font-size:46px}p.sub{position:absolute;left:70px;top:112px;margin:0;font-size:24px;color:#C8D6BE}
.chip{position:absolute;left:70px;width:560px;height:86px;border-radius:12px;background:#5B8C3A;border:2px solid #446B29;opacity:0;padding:14px 22px;box-sizing:border-box}
.chip b{font-size:30px;display:block}.chip i{font-size:20px;color:#DCE8CF;font-style:normal}
.pan{position:absolute;left:700px;top:170px;width:1090px;height:750px;border-radius:12px;overflow:hidden;opacity:0;border:3px solid #76B900;background:#fff}
.pan img{width:100%%;display:block}.cap{position:absolute;left:700px;top:932px;font-size:21px;color:#C8D6BE;opacity:0}
</style><h1>NVIDIA at every step that needs a model</h1><p class=sub>One L40S carries the whole stack</p>
%s
<div class=pan id=g><img src="%s"></div><div class=pan id=a><img src="%s"></div>
<div class=cap id=c1>Captured on the L40S, 2026-10-09 &middot; Attu: vector(1024), 1,690 entities</div>
<div class=cap id=c2>Captured on the L40S, 2026-10-09 &middot; Grafana + DCGM: GPU utilisation during semantic queries</div>
<script>const T=%s;const show=(el,t)=>setTimeout(()=>{el.style.transition='opacity .6s';el.style.opacity=1},t*1000);
const hide=(el,t)=>setTimeout(()=>{el.style.transition='opacity .6s';el.style.opacity=0},t*1000);
document.querySelectorAll('.chip').forEach((c,i)=>show(c,T[i]));
show(document.getElementById('a'),T[1]+0.8);show(document.getElementById('c1'),T[1]+0.8);
hide(document.getElementById('a'),T[6]);hide(document.getElementById('c1'),T[6]);
show(document.getElementById('g'),T[6]+0.2);show(document.getElementById('c2'),T[6]+0.2);</script>""" % (
        "".join('<div class=chip style="top:%dpx"><b>%s</b><i>%s</i></div>' % (190 + i * 110, a, b) for i, (a, b) in enumerate(chips)),
        b64(shots / "09-grafana-dashboard.jpg"), b64(shots / "11-attu-schema-1024.jpg"), json.dumps(at))


def end_html() -> str:
    cards = [("Own your models", "The answer path never depends on a hosted endpoint that can be retired"),
             ("One card", "The whole stack fits in ~30 GB of one 46 GB L40S"),
             ("Reproducible", "A pinned container at temperature 0 gives the same answer twice"),
             ("Checked", "Every figure is verified against the records, and every call is measured")]
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;background:#14302A;font-family:Arial,sans-serif;color:#fff;overflow:hidden}
h1{position:absolute;left:0;right:0;top:70px;text-align:center;margin:0;font-size:58px}
.c{position:absolute;top:230px;width:400px;height:300px;background:#1E4035;border:2px solid #2E5245;border-radius:14px;padding:30px;box-sizing:border-box;opacity:0}
.c b{display:block;color:#76B900;font-size:40px;margin-bottom:16px}.c span{font-size:26px;color:#DCE8CF;line-height:1.35}
#e{position:absolute;left:0;right:0;top:620px;text-align:center;opacity:0}#e h2{font-size:72px;margin:0 0 18px}#e p{font-size:30px;color:#C8D6BE;margin:6px}
#e small{display:block;margin-top:40px;font-size:24px;color:#8FA58A}
</style><h1>Why it matters</h1>%s<div id=e><h2>Let's talk about your shop.</h2>
<p>Automotive Service Operations Intelligence Agent</p><p>NVIDIA NIM &middot; Riva &middot; NeMo &middot; DCGM</p>
<small>[ your name &middot; contact details ]</small></div>
<script>const f=(el,t)=>setTimeout(()=>{el.style.transition='opacity .7s';el.style.opacity=1},t);
document.querySelectorAll('.c').forEach((c,i)=>f(c,1200+i*1500));f(document.getElementById('e'),8200);</script>""" % "".join(
        '<div class=c style="left:%dpx"><b>%s</b><span>%s</span></div>' % (80 + i * 440, a, b) for i, (a, b) in enumerate(cards))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slide-only", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # ---- the process slide on its own
        html, dur = slide_html(ROOT / "docs" / "architecture-deck.pptx")
        (WORK / "slide.html").write_text(html)
        clip = record_scene(pw, 20, (WORK / "slide.html").as_uri(), dur + 1.0, [], "SLIDE PREVIEW")
        shutil.copy(clip, OUT / "process-slide-preview.mp4")
        print("process-slide-preview.mp4: %.1f s" % (dur + 1.0))
        if args.slide_only:
            return

        # ---- the demo
        sc = scenes()
        db = WORK / "demo.sqlite"
        shutil.copy(ROOT / "data" / "generated" / "service.sqlite", db)
        os.environ["ASOIA_DB"] = str(db)
        from app.analytics.queries import list_ros
        from app.state import db as dbm
        n_safety = list_ros(dbm.connect(str(db)), "safety", limit=500)["count"]
        texts = {n: t for n, _, t in sc}
        texts[3] = texts[3].replace("dictates that", "logs that")                  # preview shows the form, not dictation
        texts[4] = texts[4].replace("[N]", str(n_safety))
        texts[4] = re.split(r"\sA free-text question", texts[4])[0]                 # semantic answer needs the GPU box
        wavs, aud = {}, {}
        for n, t in texts.items():
            wavs[n] = WORK / ("n%d.wav" % n); aud[n] = tts(t, wavs[n]); print("scene %d voice: %.1f s" % (n, aud[n]))
        need = {1: 0, 2: dur + 1.5, 3: 27, 4: 20, 5: 0, 6: 12.5}
        D = {n: max(aud[n] + LEAD + TAIL, need[n]) for n in aud}
        ports = {1: 7871, 3: 7872, 4: 7873}
        procs = [start_ui(tab, ports[n], db) for n, tab in ((1, "dashboard"), (3, "update"), (4, "assistant"))]
        try:
            urls = {1: "http://127.0.0.1:7871", 3: "http://127.0.0.1:7872", 4: "http://127.0.0.1:7873",
                    2: (WORK / "slide.html").as_uri()}
            (WORK / "comp.html").write_text(components_html(D[5])); urls[5] = (WORK / "comp.html").as_uri()
            (WORK / "end.html").write_text(end_html()); urls[6] = (WORK / "end.html").as_uri()
            tags = {1: "PREVIEW · local app", 2: "PREVIEW · slide rendered from the deck XML",
                    3: "PREVIEW · structured entry (voice path runs on the GPU box)",
                    4: "PREVIEW · structured answer (semantic search runs on the GPU box)",
                    5: "PREVIEW · stills from the L40S run", 6: "PREVIEW"}
            acts = {1: scene1, 3: scene3, 4: scene4}
            parts = []
            for n in range(1, 7):
                caps = caption_times(texts[n], aud[n])
                v = record_scene(pw, n, urls[n], D[n], caps, tags[n], acts.get(n))
                m = WORK / ("m%d.mp4" % n); mux(v, wavs[n], D[n], m); parts.append(m)
                print("scene %d: %.1f s" % (n, D[n]))
        finally:
            for p in procs:
                stop(p)
        final = OUT / "demo-preview.mp4"
        concat(parts, final)
        print("demo-preview.mp4: %.0f s total, %.1f MB" % (sum(D.values()), final.stat().st_size / 1e6))


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
