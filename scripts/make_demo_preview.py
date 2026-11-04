#!/usr/bin/env python
"""Build the client demo video. No GPU box is needed: the live scenes are edited from raw footage.

    python scripts/make_demo_preview.py                  # the whole video + the slide clip
    python scripts/make_demo_preview.py --scene OE       # only some pieces, for iteration
    python scripts/make_demo_preview.py --slide-only     # just the process-slide clip

Run it with an interpreter that has `playwright`, `imageio-ffmpeg` and `nvidia-riva-client` - deliberately NOT
project dependencies, so use a throwaway venv (see docs/demo/README.md).

TWO STAGES, SO THE BOX IS ONLY NEEDED WHEN THE APP CHANGES

  1. scripts/demo_footage.py records the real application ONCE on the Brev L40S: the dashboard, the Technician Update
     tab (a spoken update is uploaded, transcribed by Riva, extracted by Nemotron and flagged by the rules), the
     Manager Assistant (a structured and a semantic question, search + rerank + narration on the local NIMs) and live
     Grafana with DCGM metrics. It saves 4K footage with nothing drawn on it, plus a timeline of where everything is.
  2. This script edits that footage into the video, offline: it re-times each shot to the narration, then adds the
     camera, the ring, the keyword callout, the product badge, the caption and - only on a click - a cursor.
     Changing the script, the pacing, the zoom or any of those overlays never needs the box.
     It prints whether the footage still matches the app (demo_footage.py --check). Only the process slide (rendered
     from the deck's own XML), the opening visual, the component cards, the business-value cards and the end card are
     made here, from HTML.

HOW IT IS EDITED

The script is a table of short beats in docs/DEMO_VIDEO.md. Each beat is voiced on its own (NVIDIA Riva Magpie TTS,
44.1 kHz), and its audio length sets the length of its shot, so picture and words cannot drift apart. In every shot the
camera is moving, a keyword callout lands as the word is spoken, a ring pulses on what is described, and a subtitle
runs along the bottom. Soft dissolves ease the three changes of screen (dashboard to process slide to app to assistant).
"""
from __future__ import annotations

import argparse, json, os, re, shutil, subprocess, sys, tempfile, time, wave, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
from demo_footage import FOOT, FPS, H, K, TTS_CACHE, W, check, ffmpeg, load_timeline, run
OUT = ROOT / "docs" / "demo"
WORK = Path(tempfile.mkdtemp(prefix="asoia-demo-"))
GAP = 0.30                       # silence after each beat's voice
F_TAIL = 0.4                     # seconds the closing card stays after the last word
CAPTIONS = False                 # burned-in captions: off. demo-preview.srt (scripts/export_edit_sheet.py) carries them as a separate file
TEMPO = 1.0                      # speech speed (1.0 = the voice's natural pace)
# seconds a key visual is held, still, after its line has been spoken, so it can be read
HOLD = {"A4": 0.3, "B5": 0.3, "C3": 0.6, "C4": 0.6, "D3": 0.4, "D4": 0.6, "D6": 0.5,
        "E1": 0.4, "E5": 1.0, "G1": 0.3, "V4": 0.0, "F4": 0.4, "H1": 0.0, "K1": 0.5}
VOICE, RATE = "Magpie-Multilingual.EN-US.Sofia", 44100

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


# ------------------------------------------------------------------ the script
def beats():
    """{scene letter: [(beat id, narration)]} from the beat table in docs/DEMO_VIDEO.md."""
    out: dict[str, list] = {}
    for line in (ROOT / "docs" / "DEMO_VIDEO.md").read_text().splitlines():
        m = re.match(r"\| ([A-V])(\d) \| (.+?) \| (.+) \|$", line)
        if m:
            out.setdefault(m.group(1), []).append((m.group(1) + m.group(2), m.group(3)))
    assert sorted(out) == list("ABCDEFGHKPV"), "expected scenes A-H, K, P and V in docs/DEMO_VIDEO.md, found %s" % sorted(out)
    return out


# ------------------------------------------------------------------ voice
# The caption keeps the real spelling; the voice is given a respelling where it would get the word wrong:
# "read" as present tense, and DCGM spelled out letter by letter.
SPOKEN = [(r"\bread\b", "reed"), (r"\bDCGM\b", "D C G M")]


def spoken(text: str) -> str:
    for pat, rep in SPOKEN:
        text = re.sub(pat, rep, text)
    return text


_voice_cache: dict[tuple, tuple[Path, float]] = {}


def voice(text: str, tempo: float | None = None, gap: float | None = None) -> tuple[Path, float]:
    """Voice one beat at `tempo`, padded with `gap`. Returns (wav, seconds)."""
    tempo, gap = tempo or TEMPO, GAP if gap is None else gap
    key = (text, tempo, gap)
    if key in _voice_cache:
        return _voice_cache[key]
    import _env  # noqa: F401  - .env like stack.sh; the key is never printed
    import hashlib
    said = spoken(text)
    cached = TTS_CACHE / (hashlib.sha1((VOICE + said).encode()).hexdigest()[:16] + ".pcm")
    if not cached.exists():
        import riva.client as rc
        auth = rc.Auth(uri="grpc.nvcf.nvidia.com:443", use_ssl=True, metadata_args=[
            ["function-id", "877104f7-e885-42b9-8de8-f6e4c6303969"],
            ["authorization", "Bearer " + os.environ["NVIDIA_API_KEY"]]])
        for wait in (0, 4, 10, 25, 45):               # the free endpoint rate-limits bursts
            time.sleep(wait)
            try:
                r = rc.SpeechSynthesisService(auth).synthesize(
                    said, voice_name=VOICE, language_code="en-US", sample_rate_hz=RATE,
                    encoding=rc.AudioEncoding.LINEAR_PCM)
                break
            except Exception as e:
                if not any(c in str(e) for c in ("RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED", "UNAVAILABLE")) or wait == 45:
                    raise
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(r.audio)
    n = len(_voice_cache)
    raw, fast = WORK / ("raw%d.wav" % n), WORK / ("beat%d.wav" % n)
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(cached.read_bytes())
    run(ffmpeg(), "-y", "-i", raw, "-filter:a", "atempo=%.3f,apad=pad_dur=%.3f" % (tempo, gap), "-ar", RATE, "-ac", 1, fast)
    with wave.open(str(fast)) as w:
        dur = w.getnframes() / w.getframerate()
    _voice_cache[key] = (fast, dur)
    return fast, dur


def join_wavs(paths, out: Path, holds=None):
    with wave.open(str(out), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(RATE)
        for i, p in enumerate(paths):
            with wave.open(str(p)) as w:
                o.writeframes(w.readframes(w.getnframes()))
            if holds and holds[i]:
                o.writeframes(b"\0\0" * int(RATE * holds[i]))


# ------------------------------------------------------------------ the slide, from its own XML
def slide_html(pptx: Path, marker: str = "anim-s0-card", driven: bool = False) -> tuple[str, float]:
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
        if "NVIDIA-hosted" in "".join(sp.itertext()):
            continue                  # the slide's footnote about hosted speech recognition is not shown in the video
        shapes.append((c.get("id"), '<div class="sh" data-id="%s" data-name="%s" style="%s">%s</div>' % (c.get("id"), c.get("name"), ";".join(css), inner)))
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
    if driven:
        return DRIVEN_HTML.replace("@W@", str(W)).replace("@H@", str(H)).replace("@SHAPES@", "".join(h for _, h in shapes)), 0.0
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


DRIVEN_HTML = r"""<!doctype html><meta charset=utf-8><style>
html,body{margin:0;background:#fff}#s{position:relative;width:@W@px;height:@H@px;overflow:hidden;background:#fff}
.sh{position:absolute;box-sizing:border-box}[data-name^="anim-"]{opacity:0}</style><div id=s>@SHAPES@</div><script>
const grp=n=>[...document.querySelectorAll('[data-name^="'+n+'"]')];
const fade=(e,d,dur)=>e.animate([{opacity:0,transform:'translateY(16px)'},{opacity:1,transform:'none'}],{duration:dur||380,delay:d||0,fill:'forwards',easing:'ease-out'});
const wipe=(e,d)=>{const own=e.style.clipPath;const from=own?own.replace(/polygon\((.*)\)/,(m,p)=>'polygon('+p.split(',').map(q=>'0% '+q.trim().split(' ')[1]).join(',')+')'):'inset(0 100% 0 0)';
 e.style.opacity=1;e.animate([{clipPath:from},{clipPath:own||'inset(0 0 0 0)'}],{duration:320,delay:d||0,fill:'forwards',easing:'ease-out'});};
window.__stage=i=>{grp('anim-a'+i).forEach(e=>wipe(e,0));grp('anim-s'+i+'-card').forEach(e=>fade(e,60));grp('anim-s'+i+'-num').forEach(e=>fade(e,0,300));
 grp('anim-s'+i+'-text').forEach(e=>fade(e,160));grp('anim-s'+i+'-badge').forEach(e=>wipe(e,300));};
window.__stats=()=>{grp('anim-o').forEach(e=>fade(e,(+e.dataset.name.match(/anim-o(\d)/)[1])*220));};
</script>"""

# ------------------------------------------------------------------ the in-page toolkit
TOOLKIT_JS = r"""
(() => {
  if (window.__beat) return;
  const html = document.documentElement, body = document.body;
  html.style.overflow = 'hidden'; body.style.margin = '0'; body.style.transformOrigin = '0 0'; body.style.willChange = 'transform';
  const css = document.createElement('style');
  css.textContent = `
  #__cap{position:fixed;left:0;right:0;bottom:16px;text-align:center;z-index:99999;pointer-events:none}
  #__cap span{display:inline-block;max-width:1560px;color:#fff;font:700 32px/1.3 Arial,sans-serif;padding:8px 24px;text-shadow:0 0 2px #000,0 0 5px rgba(0,0,0,.9),1.5px 1.5px 0 #000,-1.5px -1.5px 0 #000,1.5px -1.5px 0 #000,-1.5px 1.5px 0 #000,0 3px 12px rgba(0,0,0,.6)}
  .__co{position:fixed;left:var(--co-x,56px);top:var(--co-y,50px);z-index:99998;pointer-events:none}
  .__co b{display:block;background:rgba(10,30,22,.92);color:#fff;font:700 50px/1.1 Arial,sans-serif;padding:14px 30px;border-left:12px solid #76B900;border-radius:6px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
  .__ring{position:absolute;z-index:99990;pointer-events:none;border:5px solid #76B900;border-radius:10px;animation:__p .8s ease-in-out infinite alternate}
  @keyframes __p{from{box-shadow:0 0 0 2px rgba(118,185,0,.2),0 0 10px rgba(118,185,0,.5)}to{box-shadow:0 0 0 10px rgba(118,185,0,.25),0 0 34px rgba(118,185,0,.9)}}
  `;
  document.head.appendChild(css);
  const cap = Object.assign(document.createElement('div'), {id: '__cap'}); html.appendChild(cap);

  addEventListener('scroll', () => scrollTo(0, 0), true);
  window.__mat = () => { const m = new DOMMatrix(getComputedStyle(body).transform); return {s: m.a, tx: m.e, ty: m.f}; };
  window.__find = d => {
    if (Array.isArray(d)) { const rs = d.map(window.__find).filter(Boolean); if (!rs.length) return null;
      const x0 = Math.min(...rs.map(r => r.x)), y0 = Math.min(...rs.map(r => r.y)), x1 = Math.max(...rs.map(r => r.x + r.w)), y1 = Math.max(...rs.map(r => r.y + r.h));
      return {x: x0, y: y0, w: x1 - x0, h: y1 - y0, o: Math.min(...rs.map(r => r.o === undefined ? 1 : r.o))}; }
    if (d.rect) return {x: d.rect[0], y: d.rect[1], w: d.rect[2], h: d.rect[3]};
    let el = null;
    if (d.fn) el = (new Function('return (' + d.fn + ')'))()();
    else if (d.sel) el = document.querySelectorAll(d.sel)[d.nth || 0];
    else if (d.text) { const w = document.createTreeWalker(body, NodeFilter.SHOW_TEXT); let n;
      while ((n = w.nextNode())) if (n.textContent.includes(d.text)) { const e = n.parentElement, r = e.getBoundingClientRect(); if (r.width > 0 && r.height > 0) { el = e; break; } } }
    if (!el) return null;
    if (d.up) el = el.closest(d.up) || el;
    const r = el.getBoundingClientRect(), b = body.getBoundingClientRect(), m = window.__mat();
    let op = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) op *= +getComputedStyle(n).opacity;
    const o = {x: (r.left - b.left) / m.s, y: (r.top - b.top) / m.s, w: r.width / m.s, h: r.height / m.s, o: op};
    if (d.skip) { o.y += d.skip; o.h = Math.max(40, o.h - d.skip); }
    if (d.top) o.h = Math.min(o.h, d.top);
    if (d.grow) { const g = d.grow; o.x -= g[0]; o.y -= g[1]; o.w += g[0] + g[2]; o.h += g[1] + g[3]; }
    return o;
  };
  window.__cam = (d, o) => {
    o = o || {}; const W = innerWidth, H = innerHeight, m = window.__mat(); let s, tx, ty;
    const L = d ? window.__find(d) : null;
    if (L) { const px = o.pad || 80, py = (o.pad || 80) * 0.6;
      s = Math.max(o.min || 1, Math.min(o.max || 2.4, Math.min((W - 2 * px) / L.w, (H - 2 * py) / L.h)));
      tx = W / 2 - s * (L.x + L.w / 2); ty = H / 2 - s * (L.y + L.h / 2); }
    else { s = o.to !== undefined ? o.to : Math.min(m.s * 1.05, o.max || 2.4); const cx = W / 2, cy = H / 2;
      tx = cx - (cx - m.tx) * s / m.s; ty = cy - (cy - m.ty) * s / m.s; }
    const bw = Math.max(body.scrollWidth, W), bh = Math.max(body.scrollHeight, H);
    tx = Math.min(0, Math.max(W - s * bw, tx)); ty = Math.min(0, Math.max(H - s * bh, ty));
    body.style.transition = 'transform ' + (o.ms || 1500) + 'ms ' + (o.ease || 'cubic-bezier(.45,.05,.25,1)');
    body.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + s + ')';
  };
  window.__ring = (d, pad) => { cancelAnimationFrame(window.__ringRaf); document.querySelectorAll('.__ring').forEach(e => e.remove()); if (!d) return;
    pad = pad || 10; const e = document.createElement('div'); e.className = '__ring'; e.style.opacity = 0; body.appendChild(e);
    const tick = () => { const L = window.__find(d);
      if (L) Object.assign(e.style, {left: (L.x - pad) + 'px', top: (L.y - pad) + 'px', width: (L.w + 2 * pad) + 'px', height: (L.h + 2 * pad) + 'px', opacity: L.o});
      window.__ringRaf = requestAnimationFrame(tick); };
    tick(); };
  window.__co = text => { document.querySelectorAll('.__co').forEach(e => { e.animate([{opacity: 1}, {opacity: 0}], {duration: 160, fill: 'forwards'}); setTimeout(() => e.remove(), 180); });
    if (!text) return; const e = document.createElement('div'); e.className = '__co'; e.innerHTML = '<b>' + text + '</b>'; html.appendChild(e);
    e.animate([{opacity: 0, transform: 'translateX(-40px) scale(.9)'}, {opacity: 1, transform: 'none'}], {duration: 340, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both'}); };
  window.__beat = b => { cap.innerHTML = b.cap ? '<span>' + b.cap + '</span>' : '';
    window.__cam(b.cam, Object.assign({ms: b.ms}, b.camo || {})); window.__ring(b.ring, b.ringpad); window.__co(b.co); };
})();
"""


def inject(page):
    page.add_script_tag(content=TOOLKIT_JS)
    page.wait_for_timeout(150)


# ------------------------------------------------------------------ html scenes
# ------------------------------------------------------------------ logos
LOGO_URLS = {"nvidia": "https://upload.wikimedia.org/wikipedia/sco/2/21/Nvidia_logo.svg",
             "grafana": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Grafana_logo.svg",
             "deloitte": "https://commons.wikimedia.org/wiki/Special:FilePath/Deloitte.svg"}
LOGO_CACHE = Path.home() / ".cache" / "asoia-demo-logos"


def logo(name: str) -> str:
    """A product logo as a data URI. Fetched once from the project's public brand assets into
    ~/.cache/asoia-demo-logos (third-party marks are not committed to this repository)."""
    f = LOGO_CACHE / (name + ".svg")
    if not f.exists():
        import urllib.request
        LOGO_CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(LOGO_URLS[name], headers={"User-Agent": "Mozilla/5.0 (demo-video build)"})
        svg = urllib.request.urlopen(req, timeout=30).read()
        if name == "deloitte":      # Commons has the older blue wordmark; the current mark is black with Deloitte green (#86BC25). Drop the official file in the cache to override
            svg = svg.replace(b"#004990", b"#000000").replace(b"#9bcd65", b"#86BC25")
        f.write_bytes(svg)
    import base64
    return "data:image/svg+xml;base64," + base64.b64encode(f.read_bytes()).decode()


# pictograms, drawn here: simple line icons in NVIDIA green
IC = {
    "chat": '<svg viewBox="0 0 64 64"><path d="M8 10h48a4 4 0 0 1 4 4v28a4 4 0 0 1-4 4H30L16 58V46H8a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4z" fill="none" stroke="#76B900" stroke-width="4" stroke-linejoin="round"/><circle cx="22" cy="28" r="3.5" fill="#76B900"/><circle cx="34" cy="28" r="3.5" fill="#76B900"/><circle cx="46" cy="28" r="3.5" fill="#76B900"/></svg>',
    "search": '<svg viewBox="0 0 64 64"><circle cx="26" cy="26" r="16" fill="none" stroke="#76B900" stroke-width="4"/><path d="M38 38l18 18" stroke="#76B900" stroke-width="5" stroke-linecap="round"/><circle cx="20" cy="24" r="2.6" fill="#76B900"/><circle cx="30" cy="20" r="2.6" fill="#76B900"/><circle cx="27" cy="31" r="2.6" fill="#76B900"/></svg>',
    "rank": '<svg viewBox="0 0 64 64"><path d="M8 14h40M8 30h30M8 46h20" stroke="#76B900" stroke-width="6" stroke-linecap="round"/><path d="M52 52V22m-8 8l8-10 8 10" fill="none" stroke="#76B900" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "wave": '<svg viewBox="0 0 64 64"><path d="M8 32v0M16 22v20M24 12v40M32 24v16M40 16v32M48 26v12M56 32v0" stroke="#76B900" stroke-width="5" stroke-linecap="round"/></svg>',
    "shield": '<svg viewBox="0 0 64 64"><path d="M32 5l22 8v17c0 14-9 24-22 29C19 54 10 44 10 30V13z" fill="none" stroke="#76B900" stroke-width="4" stroke-linejoin="round"/><path d="M22 32l7 7 14-15" fill="none" stroke="#76B900" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "chip": '<svg viewBox="0 0 64 64"><rect x="16" y="16" width="32" height="32" rx="4" fill="none" stroke="#76B900" stroke-width="4"/><rect x="25" y="25" width="14" height="14" rx="2" fill="#76B900"/><path d="M24 6v10M32 6v10M40 6v10M24 48v10M32 48v10M40 48v10M6 24h10M6 32h10M6 40h10M48 24h10M48 32h10M48 40h10" stroke="#76B900" stroke-width="3.5" stroke-linecap="round"/></svg>',
    "gauge": '<svg viewBox="0 0 64 64"><path d="M10 46a24 24 0 1 1 44 0" fill="none" stroke="#76B900" stroke-width="5" stroke-linecap="round"/><path d="M32 42l12-16" stroke="#76B900" stroke-width="5" stroke-linecap="round"/><circle cx="32" cy="42" r="4" fill="#76B900"/><path d="M14 56h36" stroke="#76B900" stroke-width="4" stroke-linecap="round"/></svg>',
}


def intro_html() -> str:
    notes = [("C/S grinding from the front under braking", 150, 200, -4, "0"),
             ("Front pads 1.8 mm. Spec min 3.0.", 760, 150, 3, "1"),
             ("Waiting on parts: 45022-K4A-B80", 1290, 240, -2, "2"),
             ("Promised 17:00. Customer ringing again.", 330, 520, 2, "3"),
             ("Handover: see notes on the bench", 980, 570, -3, "4")]
    cards = "".join('<div class=note id=n%s style="left:%dpx;top:%dpx;--r:%ddeg">%s</div>' % (i, x, y, r, t) for t, x, y, r, i in notes)
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;
 background:radial-gradient(circle at 30% 20%,#1d4d3f 0%,#0d201b 70%)}
.grid{position:absolute;inset:-120px;background-image:linear-gradient(rgba(118,185,0,.10) 2px,transparent 2px),linear-gradient(90deg,rgba(118,185,0,.10) 2px,transparent 2px);background-size:120px 120px;animation:drift 6s linear infinite}
@keyframes drift{to{transform:translate(120px,120px)}}
.note{position:absolute;width:520px;padding:26px 30px;box-sizing:border-box;background:#F4F1E4;color:#262626;font:600 32px/1.3 'Courier New',monospace;border-radius:6px;box-shadow:0 20px 44px rgba(0,0,0,.5);opacity:0;transform:rotate(var(--r))}
#stamp{position:absolute;left:1010px;top:110px;width:210px;height:210px;border:12px solid #E5352B;border-radius:50%;color:#E5352B;font:900 38px/186px Arial;text-align:center;transform:rotate(-14deg);opacity:0;letter-spacing:2px;background:rgba(244,241,228,.0)}
#head{position:absolute;left:0;right:0;top:845px;text-align:center;font:700 86px Arial;opacity:0;text-shadow:0 6px 30px rgba(0,0,0,.6)}
#head u{text-decoration:none;color:#76B900}
</style><div class=grid></div>@CARDS@<div id=stamp>SAFETY</div>
<div id=head>The risk hides <u>between shifts.</u></div>
<script>const $=id=>document.getElementById(id);
const fly=(e,from,d,dur)=>e.animate([{opacity:0,transform:'translate('+from[0]+'px,'+from[1]+'px) rotate(var(--r)) scale(.9)'},{opacity:1,transform:'rotate(var(--r))'}],{duration:dur||520,delay:d,fill:'forwards',easing:'cubic-bezier(.2,.9,.25,1.1)'});
window.__go=ms=>{const F=[[-700,-200],[0,-600],[700,-300],[-600,500],[700,600]];
 for(let i=0;i<5;i++) fly($('n'+i),F[i],i*ms*0.08);
 $('head').animate([{opacity:0,transform:'translateY(60px)'},{opacity:1,transform:'none'}],{duration:620,delay:ms*0.30,fill:'forwards',easing:'cubic-bezier(.2,.8,.2,1)'});
 $('stamp').animate([{opacity:0,transform:'rotate(-14deg) scale(2.4)'},{opacity:1,transform:'rotate(-14deg) scale(1)'}],{duration:300,delay:ms*0.58,fill:'forwards',easing:'cubic-bezier(.3,1.4,.5,1)'});
 $('n1').animate([{boxShadow:'0 20px 44px rgba(0,0,0,.5)'},{boxShadow:'0 0 0 10px rgba(229,53,43,.8),0 0 60px rgba(229,53,43,.9)'}],{duration:500,delay:ms*0.58,fill:'forwards'});};
</script>""".replace("@CARDS@", cards)


PI = {   # white pictograms for the problem scene
    "doc": '<svg viewBox="0 0 64 64"><path d="M14 6h26l12 12v40H14z" fill="none" stroke="#fff" stroke-width="4" stroke-linejoin="round"/><path d="M40 6v12h12M22 30h24M22 40h24M22 50h14" stroke="#fff" stroke-width="4" stroke-linecap="round" fill="none"/></svg>',
    "phone": '<svg viewBox="0 0 64 64"><path d="M16 8h10l5 14-7 4c3 7 8 12 15 15l4-7 14 5v10c0 3-2 6-6 6C27 55 9 37 10 14c0-4 3-6 6-6z" fill="none" stroke="#fff" stroke-width="4" stroke-linejoin="round"/></svg>',
    "monitor": '<svg viewBox="0 0 64 64"><rect x="6" y="10" width="52" height="34" rx="4" fill="none" stroke="#fff" stroke-width="4"/><path d="M22 54h20M32 44v10" stroke="#fff" stroke-width="4" stroke-linecap="round"/><path d="M14 36l10-10 8 6 12-14" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round"/></svg>',
    "person": '<svg viewBox="0 0 64 64"><circle cx="32" cy="22" r="12" fill="none" stroke="#fff" stroke-width="4"/><path d="M8 58c2-14 12-20 24-20s22 6 24 20" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/></svg>',
    "clock": '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="27" fill="none" stroke="#76B900" stroke-width="3.5"/><path class=hh d="M32 32V17" stroke="#fff" stroke-width="4" stroke-linecap="round" style="transform-origin:32px 32px"/><path class=mh d="M32 32V10" stroke="#76B900" stroke-width="3" stroke-linecap="round" style="transform-origin:32px 32px"/><circle cx="32" cy="32" r="3" fill="#fff"/></svg>',
}


def problem_html() -> str:
    """The opening: a title card (the first frame), then the problem in three pictures: a handover that loses the detail, a
    manager chasing answers, and the time that goes on it."""
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;
 background:radial-gradient(circle at 30% 20%,#1d4d3f 0%,#0d201b 70%)}
.grid{position:absolute;inset:-120px;background-image:linear-gradient(rgba(118,185,0,.10) 2px,transparent 2px),linear-gradient(90deg,rgba(118,185,0,.10) 2px,transparent 2px);background-size:120px 120px;animation:drift 6s linear infinite}
@keyframes drift{to{transform:translate(120px,120px)}}
.layer{position:absolute;inset:0;opacity:0}
#title{opacity:1;display:flex;flex-direction:column;align-items:center;justify-content:center}
#dl{background:#fff;border-radius:26px;padding:40px 78px;box-shadow:0 24px 70px rgba(0,0,0,.5)}#dl img{height:112px;display:block}
#title h1{margin:64px 0 0;text-align:center;font:800 118px/1.08 Arial;text-shadow:0 6px 30px rgba(0,0,0,.55)}#title h1 u{text-decoration:none;color:#76B900}
#bar{width:420px;height:8px;border-radius:4px;background:#76B900;margin:38px 0 26px;box-shadow:0 0 24px rgba(118,185,0,.7)}
#title p{margin:0;font:40px Arial;color:#BFD6B0;text-align:center}
.hd{position:absolute;left:0;right:0;top:70px;text-align:center;margin:0;font:700 56px Arial;color:#C8D6BE}
.panel{position:absolute;top:210px;width:790px;height:610px;border-radius:22px;background:rgba(255,255,255,.06);border:2px solid rgba(118,185,0,.35);opacity:0}
.panel b{position:absolute;left:36px;top:26px;font:800 40px Arial;letter-spacing:3px;color:#76B900}.panel i{position:absolute;left:36px;top:80px;font:30px Arial;color:#BFD6B0;font-style:normal}
#day{left:110px}#night{left:1020px}
#ho{position:absolute;left:910px;width:110px;top:470px;text-align:center;font:700 26px Arial;color:#C8D6BE}
.note{position:absolute;width:560px;padding:26px 30px;box-sizing:border-box;background:#F4F1E4;color:#262626;font:600 34px/1.45 'Courier New',monospace;border-radius:6px;box-shadow:0 20px 44px rgba(0,0,0,.5);opacity:0}
#sn1{left:225px;top:400px}#sn2{left:1135px;top:400px}
#sn2 .lost{filter:blur(4px);opacity:.35}
#q{position:absolute;left:1520px;top:330px;width:120px;height:120px;border-radius:50%;background:#E5352B;font:900 90px/120px Arial;text-align:center;opacity:0;box-shadow:0 10px 30px rgba(0,0,0,.45)}
#qt{position:absolute;left:1020px;width:790px;top:700px;text-align:center;font:700 40px Arial;color:#fff;opacity:0}
.src{position:absolute;top:210px;width:480px;height:290px;border-radius:22px;background:rgba(255,255,255,.07);border:2px solid rgba(255,255,255,.28);opacity:0;text-align:center}
.src .pi{width:100px;height:100px;margin:40px auto 10px}.src b{display:block;font:800 46px Arial}.src i{display:block;font:30px Arial;color:#BFD6B0;font-style:normal;margin-top:8px}
#s0{left:150px}#s1{left:720px}#s2{left:1290px}
#mgr{position:absolute;left:810px;top:690px;width:300px;text-align:center;opacity:0}
#mgr .pi{width:150px;height:150px;margin:0 auto;background:rgba(118,185,0,.18);border:3px solid #76B900;border-radius:50%;padding:28px;box-sizing:border-box}#mgr b{display:block;font:800 40px Arial;margin-top:12px}
.dash{position:absolute;width:0;border-left:4px dashed rgba(118,185,0,.8);opacity:0}
.bub{position:absolute;padding:16px 28px;border-radius:30px;background:#fff;color:#142019;font:700 36px Arial;box-shadow:0 12px 30px rgba(0,0,0,.45);opacity:0}
#clk{position:absolute;left:150px;top:300px;width:520px;height:520px;opacity:0}#clk svg{width:100%;height:100%}
.mh{animation:spin 1.6s linear infinite}.hh{animation:spin 19.2s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.chip{position:absolute;left:800px;width:960px;height:130px;border-radius:24px;background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.26);font:700 52px/126px Arial;padding-left:150px;box-sizing:border-box;opacity:0}
.chip .pi{position:absolute;left:34px;top:26px;width:76px;height:76px}
#c0{top:260px}#c1{top:430px}#c2{top:600px}
#fin{position:absolute;left:0;right:0;top:870px;text-align:center;font:800 78px Arial;opacity:0;text-shadow:0 6px 30px rgba(0,0,0,.6)}#fin u{text-decoration:none;color:#76B900}
</style><div class=grid></div>
<div id=title class=layer><div id=dl><img src="@DL@"></div><h1>Service Operations <u>Agent</u></h1><div id=bar></div>
 <p>From first update to final answer: one connected view of service operations</p></div>

<div id=shift class=layer><h2 class=hd>Every shift change</h2>
 <div class=panel id=day><b>DAY SHIFT</b><i>the technician who did the work</i></div><div class=panel id=night><b>NIGHT SHIFT</b><i>the technician who picks it up</i></div>
 <div class=note id=sn1>Rotor 21.9 mm<br>spec min 23?<br>told Dave, parts</div>
 <div class=note id=sn2><span>Rotor 21.9 mm</span><br><span class=lost>spec min 23?</span><br><span class=lost>told Dave, parts</span></div>
 <div id=q>?</div><div id=qt>The detail that mattered is gone</div></div>

<div id=chase class=layer><h2 class=hd>A manager hunting for an answer</h2>
 <div class=src id=s0><div class=pi>@DOC@</div><b>Notes</b><i>paper and chat threads</i></div>
 <div class=src id=s1><div class=pi>@PHONE@</div><b>Calls</b><i>"has anyone seen&hellip;?"</i></div>
 <div class=src id=s2><div class=pi>@MON@</div><b>Screens</b><i>one system per question</i></div>
 <div class=dash id=d0></div><div class=dash id=d1></div><div class=dash id=d2></div>
 <div id=mgr><div class=pi>@PERSON@</div><b>Service manager</b></div>
 <div class=bub id=b0 style="left:200px;top:580px">Where is the Passat?</div>
 <div class=bub id=b1 style="left:1230px;top:580px">Is it safe to release?</div>
 <div class=bub id=b2 style="left:690px;top:900px;background:#76B900;color:#0d201b">Who worked on it?</div></div>

<div id=lost class=layer><h2 class=hd>Where the time goes</h2>
 <div id=clk>@CLOCK@</div>
 <div class=chip id=c0><div class=pi>@SEARCH@</div>Asking again</div>
 <div class=chip id=c1><div class=pi>@DOC@</div>Searching old notes</div>
 <div class=chip id=c2><div class=pi>@DOC@</div>Re-typing updates</div>
 <div id=fin>Less time <u>fixing cars.</u></div></div>
<script>const $=id=>document.getElementById(id);
const pop=(e,d,y,rot)=>{const r=rot||'rotate(0deg)';e.animate([{opacity:0,transform:r+' translateY('+(y===undefined?40:y)+'px) scale(.92)'},{opacity:1,transform:r}],{duration:d||460,fill:'forwards',easing:'cubic-bezier(.2,.9,.25,1.1)'});};
const show=(e,d)=>{e.animate([{opacity:0},{opacity:1}],{duration:d||360,fill:'forwards'});};
window.__layer=id=>{for(const l of document.querySelectorAll('.layer')){const on=l.id===id;l.animate([{opacity:getComputedStyle(l).opacity},{opacity:on?1:0}],{duration:420,fill:'forwards'});}};
window.__pop=(id,rot)=>pop($(id),460,40,rot);
window.__fade=id=>show($(id));
window.__handover=()=>{$('sn1').animate([{transform:'rotate(-3deg)',opacity:1},{transform:'translate(910px,0) rotate(2deg)',opacity:0}],{duration:900,fill:'forwards',easing:'cubic-bezier(.5,0,.3,1)'});
 setTimeout(()=>pop($('sn2'),420,0,'rotate(2deg)'),700);setTimeout(()=>{pop($('q'),380,0);show($('qt'),500)},1250);};
window.__link=i=>{const s=$('s'+i),m=$('mgr'),d=$('d'+i);
 const x1=s.offsetLeft+s.offsetWidth/2,y1=s.offsetTop+s.offsetHeight,x2=m.offsetLeft+m.offsetWidth/2,y2=m.offsetTop+20;
 const len=Math.hypot(x2-x1,y2-y1),ang=Math.atan2(x2-x1,y2-y1);
 Object.assign(d.style,{left:x1+'px',top:y1+'px',height:len+'px',transformOrigin:'0 0',transform:'rotate('+(-ang)+'rad)'});show(d,500);};
</script>""".replace("@DL@", logo("deloitte")).replace("@DOC@", PI["doc"]).replace("@PHONE@", PI["phone"]).replace("@MON@", PI["monitor"]) \
        .replace("@PERSON@", PI["person"]).replace("@CLOCK@", PI["clock"]).replace("@SEARCH@", IC["search"])


def observ_html() -> str:
    """The observability infographic: DCGM's 19 GPU series and the app's 13 into Prometheus into Grafana. The live dashboard is
    laid into the empty frame by pip_overlay; the legend chips light up as its figures and graphs are ringed."""
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;
 background:radial-gradient(circle at 30% 20%,#1d4d3f 0%,#0d201b 70%)}
.grid{position:absolute;inset:-120px;background-image:linear-gradient(rgba(118,185,0,.08) 2px,transparent 2px),linear-gradient(90deg,rgba(118,185,0,.08) 2px,transparent 2px);background-size:120px 120px}
h1{position:absolute;left:0;right:0;top:56px;margin:0;text-align:center;font:800 70px Arial;text-shadow:0 6px 30px rgba(0,0,0,.55)}h1 u{text-decoration:none;color:#76B900}
.src{position:absolute;left:60px;width:540px;height:250px;border-radius:22px;background:#fff;color:#142019;border-left:16px solid #76B900;box-shadow:0 22px 50px rgba(0,0,0,.45);opacity:0}
#a{top:288px}#b{top:591px}
.src img{position:absolute;left:36px;top:26px;height:42px}.src .t{position:absolute;left:36px;top:34px;font:800 24px Arial;letter-spacing:.5px}
.src .sub{position:absolute;left:36px;top:84px;font:700 28px Arial}
.src .n{position:absolute;right:34px;top:14px;font:800 104px/1 Arial;color:#2f5f00}.src .u{position:absolute;right:34px;top:118px;font:700 28px Arial;color:#4b5b50;text-align:right}
.src .m{position:absolute;left:36px;right:30px;bottom:22px;font:25px/1.35 Arial;color:#4b5b50}
#prom{position:absolute;left:652px;top:474px;width:200px;height:180px;border-radius:22px;background:#1b3a30;border:3px solid #76B900;text-align:center;opacity:0;box-shadow:0 0 50px rgba(118,185,0,.25)}
#prom b{display:block;font:800 30px Arial;margin-top:56px}#prom i{display:block;font:24px Arial;color:#BFD6B0;font-style:normal;margin-top:10px}
#frame{position:absolute;left:918px;top:288px;width:964px;height:553px;border-radius:18px;background:#fff;box-shadow:0 22px 60px rgba(0,0,0,.55);opacity:0}
#gl{position:absolute;left:918px;top:206px;height:64px;padding:0 26px;border-radius:16px;background:#fff;color:#142019;display:flex;align-items:center;gap:16px;font:700 30px Arial;opacity:0;box-shadow:0 8px 26px rgba(0,0,0,.35)}#gl img{height:44px}
svg.ar{position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none}
.ln{fill:none;stroke:#76B900;stroke-width:7;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1;opacity:0}
#lgs{position:absolute;left:918px;top:872px;display:flex;gap:14px}
.lg{height:54px;padding:0 22px 0 18px;border-radius:27px;background:rgba(255,255,255,.1);border:2px solid rgba(118,185,0,.8);font:700 24px/50px Arial;white-space:nowrap;opacity:0}
.lg:before{content:"";display:inline-block;width:20px;height:20px;border-radius:5px;border:4px solid #76B900;margin-right:10px;vertical-align:-3px;box-shadow:0 0 10px rgba(118,185,0,.8)}
</style><div class=grid></div><h1>Observability, <u>built in</u></h1>
<div class=src id=a><img src="@NV@"><div class=sub style="top:80px">DCGM exporter</div><div class=n><span class=v data-to=19>19</span></div><div class=u>GPU series</div>
 <div class=m>utilisation &middot; framebuffer &middot; power &middot; temperature &middot; clock</div></div>
<div class=src id=b><div class=t>Service Operations Agent</div><div class=sub style="top:80px">the app's own metrics</div><div class=n><span class=v data-to=13>13</span></div><div class=u>app series</div>
 <div class=m>answer latency &middot; NIM latency &middot; model calls &middot; tool use &middot; guardrail blocks</div></div>
<div id=prom><b>Prometheus</b><i>scrapes both</i></div>
<div id=gl><img src="@GR@">Grafana &middot; live</div><div id=frame></div>
<svg class=ar viewBox="0 0 1920 1080"><defs><marker id=h viewBox="0 0 10 10" refX=7 refY=5 markerWidth=5 markerHeight=5 orient=auto-start-reverse><path d="M0 0L10 5L0 10z" fill="#76B900"/></marker></defs>
 <path class=ln id=l0 pathLength=1 marker-end="url(#h)" d="M606 413 C 630 413 630 530 646 530"/>
 <path class=ln id=l1 pathLength=1 marker-end="url(#h)" d="M606 716 C 630 716 630 598 646 598"/>
 <path class=ln id=l2 pathLength=1 marker-end="url(#h)" d="M858 564 L 906 564"/></svg>
<div id=lgs><div class=lg id=g0>Primary figures</div><div class=lg id=g1>DCGM &middot; GPU load</div><div class=lg id=g2>DCGM &middot; GPU power</div></div>
<script>const $=id=>document.getElementById(id);
const up=(e,d)=>e.animate([{opacity:0,transform:'translateY(46px) scale(.95)'},{opacity:1,transform:'none'}],{duration:d||520,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
const draw=e=>{e.style.opacity=1;e.animate([{strokeDashoffset:1},{strokeDashoffset:0}],{duration:420,fill:'forwards',easing:'ease-out'});};
const count=e=>{const to=+e.dataset.to,t0=performance.now();const tick=t=>{const k=Math.min(1,(t-t0)/800);e.textContent=Math.round(to*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(tick);};requestAnimationFrame(tick);};
window.__go=ms=>{const at=(f,fn)=>setTimeout(fn,ms*f);
 at(.03,()=>{up($('a'));count($('a').querySelector('.v'));});at(.10,()=>{up($('b'));count($('b').querySelector('.v'));});
 at(.18,()=>{draw($('l0'));draw($('l1'));});at(.22,()=>up($('prom'),380));
 at(.28,()=>draw($('l2')));at(.30,()=>{$('frame').animate([{opacity:0},{opacity:1}],{duration:400,fill:'forwards'});up($('gl'),420);});
 at(.46,()=>up($('g0'),360));at(.60,()=>up($('g1'),360));at(.72,()=>up($('g2'),360));};
</script>""".replace("@NV@", logo("nvidia")).replace("@GR@", logo("grafana"))


def architecture_html() -> str:
    """The deployed architecture as a layered diagram inside one frame: quality on top, speech and safety in the middle, the three
    NIMs on the L40S at the bottom. Row names sit in a left gutter, so nothing crosses a card or its border. Parts are shown one at a
    time; the camera frames each with the earlier ones still on screen, dimmed. The part being shown glows; it is not ringed, because
    a ring would sit on the part's own border."""
    tiles = [("t0", "chat", "Nemotron 8B", "language"), ("t1", "search", "Embedding", "search"), ("t2", "rank", "Reranking", "search")]
    t_html = "".join('<div class=tile id=%s><div class=ic>%s</div><b>%s</b><i>%s</i><span>NIM</span></div>' % (i, IC[ic], a, b) for i, ic, a, b in tiles)
    cards = [("c0", "wave", "Riva", "Speech to text, for spoken updates"), ("c1", "shield", "NeMo Guardrails", "Stops unsafe requests before tools run"),
             ("c2", "gauge", "NeMo Evaluator", "Scores every release against the baseline")]
    c_html = "".join('<div class=card id=%s><div class=ic2>%s</div><div class=tx><img src="@NV@"><b>%s</b><i>%s</i></div></div>' % (i, IC[ic], a, b) for i, ic, a, b in cards)
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;background:radial-gradient(circle at 25% 15%,#1d4d3f 0%,#0d201b 75%)}
#logo{position:absolute;left:70px;top:30px;height:44px;background:#fff;padding:9px 20px;border-radius:12px;box-sizing:content-box}
#ttl{position:absolute;left:0;right:0;top:26px;margin:0;text-align:center;font:800 58px Arial;text-shadow:0 6px 30px rgba(0,0,0,.55)}#ttl u{text-decoration:none;color:#76B900}
#frame{position:absolute;left:100px;top:120px;width:1720px;height:930px;border:3px dashed rgba(118,185,0,.45);border-radius:30px;box-sizing:border-box}
#tab{position:absolute;left:140px;top:104px;padding:6px 22px;background:#0d201b;border:2px solid rgba(118,185,0,.6);border-radius:14px;font:700 26px Arial;color:#BFD6B0}
.lab{position:absolute;left:140px;width:190px;font:700 24px/1.3 Arial;letter-spacing:3px;color:#76B900;opacity:0}
#r2{position:absolute;left:350px;top:380px;width:1440px;height:160px}
#gpu{position:absolute;left:350px;top:640px;width:1440px;height:380px;opacity:0}
.chip{position:absolute;inset:0;border:5px solid #2f6a4a;border-radius:26px;background:#10261f;transition:box-shadow .4s,border-color .4s}
#gpu.hl .chip{border-color:#76B900;animation:glow 1.4s ease-in-out infinite alternate}
.chip .nm{position:absolute;left:40px;top:22px;font:700 30px Arial;color:#76B900;letter-spacing:4px}
.tile{position:absolute;top:72px;width:410px;height:196px;border-radius:16px;background:#1b3a30;border:2px solid #2f6a4a;opacity:0}
.tile .ic{position:absolute;left:24px;top:30px;width:84px;height:84px}.tile b{position:absolute;left:130px;top:44px;font-size:34px}.tile i{position:absolute;left:130px;top:94px;font:26px Arial;color:#BFD6B0;font-style:normal}
.tile span{position:absolute;right:14px;top:12px;background:#76B900;color:#0d201b;font:700 17px Arial;padding:2px 9px;border-radius:9px}
#t0{left:40px}#t1{left:490px}#t2{left:940px}
#vr{position:absolute;left:40px;right:40px;top:300px;opacity:0}
#vr .l{font:600 26px Arial;color:#C8D6BE;margin-bottom:10px;display:flex;justify-content:space-between}
#vr .tr{height:30px;border-radius:15px;background:#1b3a30;overflow:hidden;border:2px solid #2f6a4a}#vf{height:100%;width:0;background:linear-gradient(90deg,#4d8a00,#76B900)}
.card{position:absolute;height:160px;border-radius:20px;background:#fff;color:#142019;opacity:0;box-shadow:0 14px 34px rgba(0,0,0,.4);border-left:12px solid #76B900}
.card.hl{animation:glow 1.4s ease-in-out infinite alternate}
@keyframes glow{from{box-shadow:0 0 30px 6px rgba(118,185,0,.40)}to{box-shadow:0 0 56px 14px rgba(118,185,0,.75)}}
#c0{left:350px;top:380px;width:700px}#c1{left:1090px;top:380px;width:700px}#c2{left:350px;top:160px;width:1440px;height:140px}
.ic2{position:absolute;left:30px;top:26px;width:104px;height:104px;background:#EEF6DF;border-radius:22px;padding:18px;box-sizing:border-box}#c2 .ic2{top:18px}
.tx{position:absolute;left:162px;top:20px;right:24px}.tx img{height:44px;display:block;margin:-4px 0 4px -4px}.tx b{display:block;font-size:40px}.tx i{display:block;font:27px/1.25 Arial;color:#4b5b50;font-style:normal;margin-top:4px}
#c2 .tx{top:12px}#c2 .tx img{height:38px;margin:-2px 0 2px -4px}#c2 .tx b{font-size:38px}
svg#flow{position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none}
.fl{fill:none;stroke:#76B900;stroke-width:6;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1;opacity:0}
.fn{position:absolute;padding:3px 14px;border-radius:14px;background:#0d201b;border:2px solid rgba(118,185,0,.7);font:700 24px Arial;color:#DCE8CF;white-space:nowrap;opacity:0}
</style><img id=logo src="@NV@"><h1 id=ttl>Deployed <u>architecture</u></h1>
<div id=frame></div><div id=tab>Service Operations Agent</div>
<div class=lab id=lab0 style="top:216px">QUALITY</div><div class=lab id=lab1 style="top:432px">SPEECH AND SAFETY</div><div class=lab id=lab2 style="top:662px">MODELS ON ONE GPU</div>
<div id=r2></div>
<svg id=flow viewBox="0 0 1920 1080"><defs><marker id=ah viewBox="0 0 10 10" refX=7 refY=5 markerWidth=4.5 markerHeight=4.5 orient=auto-start-reverse><path d="M0 0L10 5L0 10z" fill="#76B900"/></marker></defs>
 <path class=fl id=f0 pathLength=1 marker-end="url(#ah)" d="M640 548 L640 630"/>
 <path class=fl id=f1 pathLength=1 marker-end="url(#ah)" d="M1230 548 L1230 630"/>
 <path class=fl id=f2 pathLength=1 marker-end="url(#ah)" d="M1560 632 L1560 550"/>
 <path class=fl id=f3 pathLength=1 marker-end="url(#ah)" d="M1230 308 L1230 372"/>
 <path class=fl id=f4 pathLength=1 marker-end="url(#ah)" d="M1560 374 L1560 310"/></svg>
<div class=fn id=n0 style="left:660px;top:573px">transcript</div><div class=fn id=n1 style="left:1250px;top:573px">checked question</div><div class=fn id=n2 style="left:1580px;top:573px">checked answer</div>
<div class=fn id=n3 style="left:1250px;top:323px">test questions</div><div class=fn id=n4 style="left:1580px;top:323px">answers scored</div>
<div id=gpu><div class=chip><div class=nm>NVIDIA L40S</div>@TILES@</div>
 <div id=vr><div class=l><span>GPU memory in use</span><span>about 30 GB of 46 GB</span></div><div class=tr><div id=vf></div></div></div></div>
@CARDS@
<script>const $=id=>document.getElementById(id);
const show=(e,d)=>e.animate([{opacity:0,transform:'translateY(46px) scale(.94)'},{opacity:1,transform:'none'}],{duration:d||480,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
window.__show=id=>show($(id));window.__vram=()=>{show($('vr'));$('vf').animate([{width:'0%'},{width:'65%'}],{duration:1200,fill:'forwards',easing:'ease-out'});};
window.__pulse=id=>$(id).animate([{transform:'scale(1)',filter:'brightness(1)'},{transform:'scale(1.09)',filter:'brightness(1.35)'},{transform:'scale(1)',filter:'brightness(1)'}],{duration:640});
window.__hl=id=>{document.querySelectorAll('.hl').forEach(e=>e.classList.remove('hl'));if(id)$(id).classList.add('hl');};
window.__dim=(ids,on)=>ids.forEach(i=>{const e=$(i);e.animate([{opacity:getComputedStyle(e).opacity},{opacity:on?.5:1}],{duration:450,fill:'forwards'});});
window.__flow=ids=>ids.forEach(i=>{const f=$('f'+i),n=$('n'+i);f.style.opacity=1;f.animate([{strokeDashoffset:1},{strokeDashoffset:0}],{duration:520,fill:'forwards',easing:'ease-out'});
 n.animate([{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{duration:420,delay:260,fill:'forwards'});});
</script>""".replace("@NV@", logo("nvidia")).replace("@TILES@", t_html).replace("@CARDS@", c_html.replace("@NV@", logo("nvidia")))


def brand_html(closing: bool) -> str:
    """The Deloitte and NVIDIA card. As the preface (before the solution is shown) the label sits above the logos and the
    product name below; as the closing card the name leads, then the logos, then the line beneath."""
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;
 background:radial-gradient(circle at 30% 20%,#1d4d3f 0%,#0d201b 70%)}
.grid{position:absolute;inset:-120px;background-image:linear-gradient(rgba(118,185,0,.10) 2px,transparent 2px),linear-gradient(90deg,rgba(118,185,0,.10) 2px,transparent 2px);background-size:120px 120px;animation:drift 6s linear infinite}
@keyframes drift{to{transform:translate(120px,120px)}}
#w{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
#lab{order:1;font:700 42px Arial;letter-spacing:9px;color:#76B900;opacity:0;text-transform:uppercase}
#lock{order:2;margin:52px 0 0;background:#fff;border-radius:30px;padding:64px 104px;display:flex;align-items:center;gap:96px;box-shadow:0 24px 70px rgba(0,0,0,.5);opacity:0}
#lock img{display:block;opacity:0}#d{height:112px}#n{height:176px}
#vr{width:4px;height:150px;border-radius:2px;background:#CFCFCF;transform:scaleY(0)}
#nm{order:3;margin:64px 0 0;text-align:center;font:800 @NM@px/1.08 Arial;text-shadow:0 6px 30px rgba(0,0,0,.55);opacity:0}#nm u{text-decoration:none;color:#76B900}
#sub{order:4;margin:30px 0 0;font:600 46px Arial;color:#C8D6BE;opacity:0}
body.closing #nm{order:1;margin:0 0 56px}body.closing #lock{order:2;margin:0}body.closing #sub{order:3}body.closing #lab{display:none}
body:not(.closing) #sub{display:none}
</style><body class="@CLS@"><div class=grid></div><div id=w>
 <div id=lab>The solution, powered by</div>
 <div id=nm>Service Operations <u>Agent</u></div>
 <div id=lock><img id=d src="@DL@"><div id=vr></div><img id=n src="@NV@"></div>
 <div id=sub>Powered by Deloitte and NVIDIA</div></div>
<script>const $=id=>document.getElementById(id);
const up=(e,d,t)=>e.animate([{opacity:0,transform:'translateY(40px) scale(.97)'},{opacity:1,transform:'none'}],{duration:t||620,delay:d,fill:'forwards',easing:'cubic-bezier(.2,.8,.2,1)'});
const fd=(e,d)=>e.animate([{opacity:0},{opacity:1}],{duration:520,delay:d,fill:'forwards'});
window.__go=ms=>{const c=document.body.classList.contains('closing');
 if(c){up($('nm'),0);up($('lock'),ms*.20);fd($('d'),ms*.28);$('vr').animate([{transform:'scaleY(0)'},{transform:'scaleY(1)'}],{duration:520,delay:ms*.36,fill:'forwards',easing:'ease-out'});fd($('n'),ms*.44);up($('sub'),ms*.62);}
 else{fd($('lab'),0);up($('lock'),ms*.10);fd($('d'),ms*.20);$('vr').animate([{transform:'scaleY(0)'},{transform:'scaleY(1)'}],{duration:520,delay:ms*.34,fill:'forwards',easing:'ease-out'});fd($('n'),ms*.42);up($('nm'),ms*.62);}};
</script>""".replace("@DL@", logo("deloitte")).replace("@NV@", logo("nvidia")).replace("@NM@", "104" if closing else "88").replace("@CLS@", "closing" if closing else "")


def end_html(subs: dict) -> str:
    """The summary: the application's strengths, each with one supporting figure, then the tagline."""
    cards = [("shield", "Safety first", "Safety-critical findings are flagged the moment an update is logged.", "%s of %s vehicles flagged" % (subs["{safety}"], subs["{open}"])),
             ("gauge", "Instant answers", "Managers get answers in a tenth of a second, with no model call.", "0.1 s per answer"),
             ("search", "Grounded in records", "Every figure is checked and traced back to a real record.", "905 of 905 answers traced"),
             ("chip", "Yours to run", "Three NIMs on one GPU you own, with observability built in.", "30 of 46 GB used")]
    c_html = "".join('<div class=c style="left:%dpx"><div class=ic>%s</div><div class=l>%s</div><div class=d>%s</div><div class=m>%s</div></div>'
                     % (76 + i * 440, IC[ic], t, d, m) for i, (ic, t, d, m) in enumerate(cards))
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;background:radial-gradient(circle at 25% 15%,#1d4d3f 0%,#0d201b 75%);font-family:Arial,sans-serif;color:#fff;overflow:hidden;position:relative}
h1{position:absolute;left:0;right:0;top:96px;text-align:center;margin:0;font-size:84px;opacity:0}
.c{position:absolute;top:250px;width:410px;height:450px;background:#fff;color:#142019;border-top:14px solid #76B900;border-radius:20px;padding:34px 30px;box-sizing:border-box;opacity:0;box-shadow:0 22px 50px rgba(0,0,0,.45)}
.c .ic{width:84px;height:84px;background:#EEF6DF;border-radius:20px;padding:14px;box-sizing:border-box}
.c .l{font:800 42px/1.15 Arial;margin-top:26px}.c .d{font:28px/1.35 Arial;color:#4b5b50;margin-top:16px}
.c .m{position:absolute;left:30px;bottom:30px;padding:8px 18px;border-radius:22px;background:#EEF6DF;color:#2f5f00;font:700 26px Arial}
#big{position:absolute;left:0;right:0;top:770px;text-align:center;font-size:92px;font-weight:700;opacity:0}#big u{text-decoration:none;color:#76B900}
#nm{position:absolute;left:0;right:0;top:900px;text-align:center;font-size:44px;color:#C8D6BE;opacity:0}
</style><h1 id=t>Summary</h1>@CARDS@<div id=big>Fast. <u>Grounded.</u> Yours to run.</div><div id=nm>Service Operations Agent</div>
<script>const $=id=>document.getElementById(id);
const up=(e,d)=>e.animate([{opacity:0,transform:'translateY(60px) scale(.96)'},{opacity:1,transform:'none'}],{duration:d||520,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
window.__title=()=>up($('t'));window.__card=i=>up(document.querySelectorAll('.c')[i]);
window.__big=()=>{up($('big'),600);setTimeout(()=>up($('nm'),600),900);};
</script>""".replace("@CARDS@", c_html)


def value_html(subs: dict) -> str:
    cards = [("v0", "shield", "%s of %s" % (subs["{safety}"], subs["{open}"]), "unsafe vehicles surfaced at once", "not buried in a technician's note"),
             ("v1", "gauge", "0.1 s", "to answer a manager's question", "from live state, with no model call"),
             ("v2", "search", "905 / 905", "answers traced to a real record", "every cited figure is checked"),
             ("v3", "chat", "1 update", "feeds the whole shop", "the record, the handover and the dashboard")]
    c_html = "".join('<div class=v id=%s><div class=ic>%s</div><div class=big>%s</div><div class=lab>%s</div><div class=sub>%s</div></div>'
                     % (i, IC[ic], big, lab, sub) for i, ic, big, lab, sub in cards)
    return """<!doctype html><meta charset=utf-8><style>
:root{--co-x:1430px;--co-y:50px}
body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;font-family:Arial,sans-serif;color:#fff;background:radial-gradient(circle at 25% 15%,#1d4d3f 0%,#0d201b 75%)}
h1{position:absolute;left:0;right:0;top:78px;text-align:center;margin:0;font-size:64px}
p.sub2{position:absolute;left:0;right:0;top:166px;text-align:center;margin:0;font-size:30px;color:#C8D6BE}
.v{position:absolute;top:270px;width:410px;height:600px;border-radius:22px;background:#fff;color:#142019;opacity:0;box-shadow:0 22px 50px rgba(0,0,0,.45);border-top:14px solid #76B900;padding:34px;box-sizing:border-box}
.v .ic{width:96px;height:96px;background:#EEF6DF;border-radius:20px;padding:16px;box-sizing:border-box}
.v .big{font:800 82px/1.05 Arial;margin:34px 0 16px;color:#2f5f00;white-space:nowrap}
.v .lab{font:700 38px/1.22 Arial}.v .sub{font:28px/1.32 Arial;color:#4b5b50;margin-top:18px}
#v0{left:72px}#v1{left:527px}#v2{left:982px}#v3{left:1437px}
#note{position:absolute;left:0;right:0;bottom:70px;text-align:center;font:26px Arial;color:#9FB59A;opacity:0}
</style><h1>What it changes for the shop</h1><p class=sub2>Measured on the demo dataset</p>@CARDS@
<div id=note>Figures are from this demo dataset. Your shop's results will vary.</div>
<script>const $=id=>document.getElementById(id);
const show=(e,d)=>e.animate([{opacity:0,transform:'translateY(50px) scale(.95)'},{opacity:1,transform:'none'}],{duration:d||520,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
window.__show=id=>show($(id));window.__note=()=>$('note').animate([{opacity:0},{opacity:1}],{duration:600,fill:'forwards'});
</script>""".replace("@CARDS@", c_html)


# ------------------------------------------------------------------ recording
def record(pw, name: str, url: str, texts, durs, plan, tail=0.0, holds=None) -> Path:
    """Record one scene. `plan[i]` is the choreography dict for beat i; it runs in real time,
    each beat starting at the running total of the voiced durations before it."""
    vdir = WORK / ("v_" + name)
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir),
                              record_video_size={"width": W, "height": H})
    page = ctx.new_page()
    t_ctx = time.time()
    page.goto(url, wait_until="load", timeout=90000)
    page.wait_for_timeout(1500)
    inject(page)
    segs, due = [], time.perf_counter()
    for i, (text, d, b) in enumerate(zip(texts, durs, plan)):
        lag = due - time.perf_counter()
        if lag > 0:
            time.sleep(lag)
        began = time.perf_counter()
        segs.append((time.time() - t_ctx, d + (tail if i == len(plan) - 1 else 0.0)))
        co = b["co"](page) if callable(b.get("co")) else b.get("co")
        page.evaluate("b => window.__beat(b)", {"cap": text if CAPTIONS else "", "ms": int((d - (holds[i] if holds else 0.0)) * 1000) - 40, "cam": b.get("cam"),
                                                 "camo": b.get("camo"), "ring": b.get("ring"),
                                                 "ringpad": b.get("ringpad"), "co": co})
        if b.get("act"):
            try:
                b["act"](page, d)
            except Exception as e:                  # a missed wait must not abandon the take
                print("  beat %d: %s" % (i + 1, str(e).splitlines()[0][:110]))
        due = began + d                              # an action that overran starts the next beat late, never short
    time.sleep(max(0.0, due + tail - time.perf_counter()))
    ctx.close(); browser.close()
    webm = next(vdir.glob("*.webm"))
    out = WORK / (name + ".mp4")
    # Cut each beat's shot from the instant it began, for exactly its voiced length: the time a slow
    # model call spent working between two beats is dropped, so the picture can never lag the words.
    parts = "".join("[0:v]trim=start=%.3f:end=%.3f,setpts=PTS-STARTPTS,scale=%d:%d:flags=lanczos,fps=%d[v%d];" % (s0, s0 + dd, W, H, FPS, k)
                    for k, (s0, dd) in enumerate(segs))
    chain = "".join("[v%d]" % k for k in range(len(segs))) + "concat=n=%d:v=1:a=0[v]" % len(segs)
    run(ffmpeg(), "-y", "-i", webm, "-filter_complex", parts + chain, "-map", "[v]", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-crf", "21", "-preset", "veryfast", "-an", out)
    return out


def mux(video: Path, wav: Path | None, total: float, out: Path):
    run(ffmpeg(), "-y", "-i", video, "-i", wav, "-filter_complex", "[1:a]apad,atrim=0:%.2f[a]" % total,
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % total, out)


OUTRO_DIR = Path.home() / ".cache" / "asoia-demo-outro"      # the client's Deloitte outro clip (a phone screen recording): kept here, not committed
OUTRO_CUTS = [(0.30, 3.60)]                  # seconds of the recording to use: the wordmark animating in with its sound, and nothing after it (the legal text comes later)
OUTRO_CROP = (980, 551, 100, 703)            # w, h, x, y of the Deloitte frame inside the 1180 x 2556 recording, placed so the wordmark is in the middle of the picture; no player controls
OUTRO_WM = (739, 498, 443)                   # x, y, width of the clip's wordmark once placed on the 1920 x 1080 frame (measured)
OUTRO_SETTLE = 1.75                          # seconds into the outro when the animation has finished: the crisp vector wordmark swaps in over it
OUTRO_HOLD = 2.5                             # the last frame stays this long, then fades to black
OUTRO_DB = -2.0                              # the clip's own sound, relative to how it was recorded


def outro_file() -> Path | None:
    return next(iter(sorted(OUTRO_DIR.glob("outro.*"))), None)


def outro_len() -> float:
    return sum(b - a for a, b in OUTRO_CUTS) + OUTRO_HOLD


def wordmark_png(pw, out: Path) -> tuple[int, int]:
    """The Deloitte wordmark as a crisp vector, white on black, sized to land exactly over the clip's own (OUTRO_WM). The
    recording is a phone's capture of a small video, so its wordmark is soft; once the animation settles this replaces it.
    Returns where the picture goes on the frame."""
    logo("deloitte")                                              # makes sure the file is cached
    uri = "data:image/svg+xml;base64," + __import__("base64").b64encode((LOGO_CACHE / "deloitte.svg").read_bytes().replace(b"#000000", b"#FFFFFF")).decode()
    x0, y0, w = OUTRO_WM
    pad = 16
    br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1400, "height": 400})
    minx, miny, maxx, maxy, W0 = pg.evaluate("""async uri => { const im = new Image(); im.src = uri; await im.decode();
      const W = 1200, H = Math.round(W * im.naturalHeight / im.naturalWidth), c = document.createElement('canvas'); c.width = W; c.height = H;
      const x = c.getContext('2d'); x.fillStyle = '#000'; x.fillRect(0, 0, W, H); x.drawImage(im, 0, 0, W, H);
      const d = x.getImageData(0, 0, W, H).data; let a = W, b = H, e = 0, f = 0;
      for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) { const k = (j * W + i) * 4; if (Math.max(d[k], d[k + 1], d[k + 2]) > 60) { a = Math.min(a, i); e = Math.max(e, i); b = Math.min(b, j); f = Math.max(f, j); } }
      return [a, b, e, f, W]; }""", uri)
    sc = w / (maxx - minx + 1)
    gh = round((maxy - miny + 1) * sc)
    pw_, ph = w + 2 * pad, gh + 2 * pad
    pg.set_viewport_size({"width": pw_, "height": ph})
    pg.set_content('<body style="margin:0;background:#000"><img src="%s" style="position:absolute;left:%.2fpx;top:%.2fpx;width:%.2fpx">'
                   % (uri, pad - minx * sc, pad - miny * sc, W0 * sc))
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(out))
    br.close()
    return x0 - pad - 1, round(y0 + 42 - ph / 2) + 1                    # the clip's wordmark is about 85 px tall; centre ours on it


def build_outro(pw, src: Path, out: Path):
    """The Deloitte outro, from the recording: the stretch where it plays, cropped to the frame itself, denoised and sharpened,
    scaled to 1920 x 1080; when its animation settles the soft wordmark gives way to the crisp vector one; the last frame is
    held and fades out. Its own sound, as mono to join the rest."""
    n = len(OUTRO_CUTS)
    png = WORK / "wordmark.png"
    ox, oy = wordmark_png(pw, png)
    v = "".join("[0:v]trim=%.2f:%.2f,setpts=PTS-STARTPTS[v%d];" % (a, b, i) for i, (a, b) in enumerate(OUTRO_CUTS))
    au = "".join("[0:a]atrim=%.2f:%.2f,asetpts=PTS-STARTPTS,afade=t=in:d=0.04,afade=t=out:st=%.2f:d=0.08[a%d];" % (a, b, b - a - 0.08, i) for i, (a, b) in enumerate(OUTRO_CUTS))
    w, h, x, y = OUTRO_CROP
    L = outro_len()
    fc = (v + au + "".join("[v%d]" % i for i in range(n))
          + "concat=n=%d:v=1:a=0,hqdn3d=1.5:1.5:3:3,crop=%d:%d:%d:%d,scale=%d:%d:flags=lanczos:in_range=pc:out_range=tv,fps=%d,unsharp=7:7:1.6:7:7:0,tpad=stop_mode=clone:stop_duration=%.2f,format=yuv420p[b];"
          % (n, w, h, x, y, W, H, FPS, OUTRO_HOLD)
          + "[1:v]format=yuva420p,fade=t=in:st=%.2f:d=0.12:alpha=1[wm];[b][wm]overlay=%d:%d:format=yuv444,fade=t=out:st=%.2f:d=0.6,format=yuv420p[v];"
          % (OUTRO_SETTLE, ox, oy, L - 0.6)
          + "".join("[a%d]" % i for i in range(n)) + "concat=n=%d:v=0:a=1,volume=%.1fdB,aformat=channel_layouts=mono,aresample=%d,apad[a]" % (n, OUTRO_DB, RATE))
    run(ffmpeg(), "-y", "-i", src, "-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % L, "-i", png, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % L, out)


MUSIC_DIR = Path.home() / ".cache" / "asoia-demo-music"      # the music bed is the client's own file: kept here, not committed
MUSIC_BELOW = 9.0                # dB: the bed's average level under the narration's
DUCK = dict(threshold=0.02, ratio=4, attack=25, release=500)   # the bed dips while the voice speaks and swells back in the gaps


def music_file(arg: str | None) -> Path | None:
    f = Path(arg).expanduser() if arg else next(iter(sorted(MUSIC_DIR.glob("bed.*"))), None)
    return f if f and f.exists() else None


def mean_db(src: Path, af: str = "anull", map_: str = "0:a:0") -> float:
    r = subprocess.run([str(ffmpeg()), "-hide_banner", "-i", str(src), "-map", map_, "-af", af + ",volumedetect", "-vn", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr).group(1))


def duration(f: Path) -> float:
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", subprocess.run([str(ffmpeg()), "-i", str(f)], capture_output=True, text=True).stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


LOOP_XFADE, FADE_IN, FADE_OUT = 3.0, 2.0, 6.0     # seconds: the overlap where one pass of the track melts into the next, and the ends


def add_music(video: Path, music: Path, out: Path):
    """Mix the music bed under the narration: repeated end to end with each pass cross-faded into the next (no gap and no
    click at the join) to span the whole video, set MUSIC_BELOW dB under the voice, ducked by the voice itself (sidechain)
    so it never competes with a word, faded in at the start and out at the end."""
    total, dm = duration(video), duration(music)
    x = min(LOOP_XFADE, dm / 3)
    n = 1 if dm >= total else int(-(-(total - x) // (dm - x)))        # passes needed: n*dm - (n-1)*x >= total
    gain = mean_db(video) - MUSIC_BELOW - mean_db(music)
    chain = ""
    fmt = "aformat=sample_fmts=fltp:channel_layouts=stereo,aresample=%d" % RATE
    for i in range(n):
        chain += "[%d:a]%s[m%d];" % (i + 1, fmt, i)
    last = "[m0]"
    for i in range(1, n):
        chain += "%s[m%d]acrossfade=d=%.2f:c1=tri:c2=tri[x%d];" % (last, i, x, i); last = "[x%d]" % i
    fc = (chain + "%svolume=%.1fdB,atrim=0:%.2f,afade=t=in:d=%.1f,afade=t=out:st=%.2f:d=%.1f[m];"
          "[0:a]pan=stereo|c0=c0|c1=c0,asplit=2[n][k];"
          "[m][k]sidechaincompress=threshold=%s:ratio=%s:attack=%s:release=%s[md];"
          "[n][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
          % (last, gain, total, FADE_IN, total - FADE_OUT, FADE_OUT, DUCK["threshold"], DUCK["ratio"], DUCK["attack"], DUCK["release"]))
    ins = ["-i", video]
    for _ in range(n):
        ins += ["-i", music]
    run(ffmpeg(), "-y", *ins, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-t", "%.2f" % total, "-movflags", "+faststart", out)


def concat(parts, out: Path):
    lst = WORK / "list.txt"
    lst.write_text("".join("file '%s'\n" % p for p in parts))
    run(ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-crf", "27", "-preset", "slow",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out)


# ------------------------------------------------------------------ logo badges and the transition between pieces
BADGES = {"C2": (["nvidia"], "Riva · speech to text"), "C3": (["nvidia"], "Nemotron 8B · NIM"),
          "D6": (["nvidia"], "NIM · embed + rerank")}


def badge_png(pw, key: str) -> Path:
    """A white pill with the product logo(s) and a label, on a transparent background."""
    logos, label = BADGES[key]
    imgs = '<span class=p>+</span>'.join('<img src="%s">' % logo(n) for n in logos)
    out = WORK / ("badge_%s.png" % key)
    br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 900, "height": 200})
    pg.set_content("""<style>body{margin:0;background:transparent}#b{display:inline-flex;align-items:center;gap:18px;background:#fff;padding:14px 26px;border-radius:16px;
      font:700 30px Arial;color:#142019;box-shadow:0 8px 26px rgba(0,0,0,.35)}#b img{height:42px}.p{font:700 30px Arial;color:#888}</style>
      <div id=b>%s<span>%s</span></div>""" % (imgs, label))
    pg.locator("#b").screenshot(path=str(out), omit_background=True)
    br.close()
    return out


def bridge(prev: Path, nxt: Path, out: Path, d: float = 0.5):
    """A short silent dissolve from the last frame of one piece to the first frame of the next, so a change of
    screen eases in instead of cutting."""
    fa, fb = WORK / "bridge_a.png", WORK / "bridge_b.png"
    run(ffmpeg(), "-y", "-sseof", "-0.2", "-i", prev, "-frames:v", "1", "-update", "1", fa)
    run(ffmpeg(), "-y", "-i", nxt, "-frames:v", "1", "-update", "1", fb)
    silent = WORK / "bridge.wav"
    with wave.open(str(silent), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(b"\0\0" * int(RATE * d))
    run(ffmpeg(), "-y", "-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % d, "-i", fa, "-loop", "1", "-framerate", str(FPS), "-t", "%.2f" % d, "-i", fb,
        "-i", silent, "-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=%.2f:offset=0,format=yuv420p,scale=%d:%d[v]" % (d - 0.01, W, H),
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-crf", "21", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % d, out)


# ------------------------------------------------------------------ choreography, one scene each


def scene_P():
    def go(layer, *steps):
        """Switch to a layer, then run (fraction of the beat, javascript) steps in time with the words."""
        def f(page, d):
            page.evaluate("l => window.__layer(l)", layer)
            at = 0.0
            for frac, js in steps:
                page.wait_for_timeout(max(0, int((frac - at) * d * 1000))); at = frac
                page.evaluate("() => { %s }" % js)
        return f
    call = lambda fn, *a: "window.%s(%s)" % (fn, ",".join("'%s'" % x for x in a))
    return [dict(cam=None, camo=dict(to=1.05)),                                                    # the title card is already on screen
            dict(cam=None, camo=dict(to=1.0), co="Handover",
                 act=go("shift", (0.04, call("__fade", "day") + ";" + call("__fade", "night")), (0.28, call("__pop", "sn1", "rotate(-3deg)")),
                        (0.60, "window.__handover()"))),
            dict(cam=None, camo=dict(to=1.05), co="Chasing answers",
                 act=go("chase", (0.04, call("__fade", "mgr")), (0.22, call("__pop", "b0") + ";" + call("__pop", "b1")),
                        (0.50, call("__fade", "s0") + ";window.__link(0)"), (0.64, call("__fade", "s1") + ";window.__link(1)"),
                        (0.78, call("__fade", "s2") + ";window.__link(2);" + call("__pop", "b2")))),
            dict(cam=None, camo=dict(to=1.0), co="Lost time",
                 act=go("lost", (0.04, call("__fade", "clk")), (0.26, call("__pop", "c0")), (0.44, call("__pop", "c1")), (0.60, call("__pop", "c2")),
                        (0.80, call("__fade", "fin"))))]


def scene_I():
    return [dict(cam=None, camo=dict(to=1.0), co="Observability", act=lambda page, d: page.evaluate("ms => window.__go(ms)", int(d * 1000)))]


def scene_B():
    def stage(i, co):
        c = [{"sel": '[data-name="anim-s%d-card"]' % i}, {"sel": '[data-name="anim-s%d-badge"]' % i}]
        return dict(cam=c, camo=dict(max=1.55, pad=110), co=co, ring={"sel": '[data-name="anim-s%d-badge"]' % i}, ringpad=6,
                    act=lambda page, d, i=i: page.evaluate("i => window.__stage(i)", i))
    out = [stage(0, "Capture"), stage(1, "Understand"), stage(2, "Verify"), stage(3, "Record"), stage(4, "Decide")]

    def last(page, d):
        page.evaluate("() => window.__stage(4)")
    out[4]["act"] = last
    out[4]["cam"] = None                       # pull back: the whole five-stage flow, with nothing else on the slide
    out[4]["camo"] = dict(to=1.0)
    return out


def scene_O():
    return [dict(cam=None, camo=dict(to=1.07), act=lambda page, d: page.evaluate("ms => window.__go(ms)", int(d * 1000)))]


def scene_E():
    def e1(page, d):
        page.evaluate("() => { window.__show('gpu'); window.__hl('gpu'); }")
        for i in ("t0", "t1", "t2"):
            page.wait_for_timeout(int(d * 1000 * 0.10))
            page.evaluate("i => window.__show(i)", i)
        page.wait_for_timeout(int(d * 1000 * 0.10))
        page.evaluate("() => window.__vram()")
        page.wait_for_timeout(int(d * 1000 * 0.22))
        for i in ("t0", "t1", "t2"):
            page.evaluate("i => window.__pulse(i)", i)
            page.wait_for_timeout(int(d * 1000 * 0.07))

    def e3(page, d):                      # the GPU shrinks back into the frame, dimmed; speech and safety come up in front of it
        page.evaluate("() => { window.__dim(['gpu'], true); window.__show('lab2'); window.__show('lab1'); window.__show('c0'); window.__hl('c0'); }")
        page.wait_for_timeout(int(d * 1000 * 0.18))
        page.evaluate("() => window.__flow([0])")                                    # speech: Riva's transcript goes to the language model
        page.wait_for_timeout(int(d * 1000 * 0.30))
        page.evaluate("() => { window.__show('c1'); window.__hl('c1'); }")
        page.wait_for_timeout(int(d * 1000 * 0.18))
        page.evaluate("() => window.__flow([1, 2])")                                 # a question goes through the rail in, the answer through it out

    def e5(page, d):                      # quality comes in on top, then the camera pulls all the way out to the whole architecture
        page.evaluate("() => { window.__dim(['gpu', 'c0', 'c1'], true); window.__show('lab0'); window.__show('c2'); window.__hl('c2'); }")
        page.wait_for_timeout(int(d * 1000 * 0.16))
        page.evaluate("() => window.__flow([3, 4])")                                 # the evaluator asks through the same doorway and scores what comes back
        page.wait_for_timeout(int(d * 1000 * 0.30))
        page.evaluate("() => { window.__hl(null); window.__dim(['gpu', 'c0', 'c1'], false); window.__cam(null, {to: 1.0, ms: 1200}); }")

    GPU = {"sel": "#gpu"}
    return [dict(cam=GPU, camo=dict(max=1.9, pad=70), act=e1),
            dict(cam={"rect": [130, 380, 1660, 640]}, camo=dict(max=1.3, pad=40), act=e3),      # the two lower rows and their names
            dict(cam={"sel": "#frame"}, camo=dict(max=1.18, pad=10), act=e5)]


def scene_V():
    def show(*ids, note=False):
        def f(page, d):
            for i in ids:
                page.evaluate("i => window.__show(i)", i)
            if note:
                page.wait_for_timeout(int(d * 500))
                page.evaluate("() => window.__note()")
        return f
    V = lambda i: {"sel": "#v%d" % i}
    return [dict(cam=V(0), camo=dict(max=1.55, pad=160), co="Safety", act=show("v0")),
            dict(cam=[V(0), V(1)], camo=dict(max=1.5, pad=120), co="Speed", act=show("v1")),
            dict(cam=[V(1), V(2)], camo=dict(max=1.5, pad=120), co="Trust", act=show("v2")),
            dict(cam=None, camo=dict(to=1.0), co="One source", act=show("v3", note=True))]


def scene_brand():
    return [dict(cam=None, camo=dict(to=1.04), act=lambda page, d: page.evaluate("ms => window.__go(ms)", int(d * 1000)))]


def scene_F():
    def card(*idx):
        def f(page, d):
            for k, i in enumerate(idx):
                page.evaluate("i => window.__card(i)", i)
                if k < len(idx) - 1:
                    page.wait_for_timeout(int(d * 1000 * 0.30))
        return f

    def f1(page, d):
        page.evaluate("() => window.__title()")
        page.wait_for_timeout(int(d * 250))
        page.evaluate("() => window.__card(0)")
    return [dict(cam={"sel": ".c", "nth": 0}, camo=dict(max=1.4, pad=240), act=f1),
            dict(cam=[{"sel": ".c", "nth": 1}, {"sel": ".c", "nth": 3}], camo=dict(max=1.25, pad=100), act=card(1, 2, 3)),
            dict(cam=None, camo=dict(to=1.0), act=lambda page, d: page.evaluate("() => window.__big()"))]


# ------------------------------------------------------------------ live scenes: raw footage + camera, ring, callout, caption, cursor
# For each beat of a live scene: the captured step it shows, and how the camera, ring and callout move through it.
# `cam` and `ring` name an entry of demo_footage.TARGETS (cam None = ease about the centre of the page); `camo` is the
# camera's limits; `co` the keyword callout; `freeze` shows one still of the step instead of playing it. `then` lists
# later moves: `at` is a fraction of the beat, or "done+0.9" = 0.9 s after the step's result appeared on screen.
LIVE_PLAN = {
    "A1": dict(src="A", freeze=True, cam=None, camo=dict(to=1.04), co="Service Operations Agent"),
    "A2": dict(src="A", freeze=True, cam="ROW", camo=dict(max=1.7, pad=70), ring="ROW", co="Live view"),
    "A4": dict(src="A", freeze=True, cam="TILE", camo=dict(max=2.3, pad=200), ring="TILE", co="{safety} flagged"),
    "C1": dict(src="C1", cam="VOICE", camo=dict(max=1.55, pad=100), co="Voice in"),
    "C2": dict(src="C2", cam="TRANS", camo=dict(max=1.6, pad=100), co="Riva ASR", badge="C2"),
    "C3": dict(src="C3", cam="EXTR", camo=dict(max=1.5, pad=100), co="Nemotron 8B", badge="C3",
               then=[dict(at="done+1.05", cam="MEAS", camo=dict(max=2.1, pad=60), ring="MEAS", dur=0.45)]),
    "C4": dict(src="C4", freeze=True, cam="CARD", camo=dict(max=2.2, pad=90), ring="CARD", ringpad=6, co="Flagged unsafe"),
    "D1": dict(src="D1", freeze=True, cam="Q", camo=dict(max=1.5, pad=140)),
    "D2": dict(src="D2", cam="Q", camo=dict(max=1.75, pad=140), ring="Q"),
    "D3": dict(src="D3", cam=None, camo=dict(to=1.05),
               then=[dict(at=0.08, cam="ANS", camo=dict(max=1.45, pad=70), ring=None, co="Cited · no model call", dur=0.5)]),
    "D5": dict(src="D5", cam="Q", camo=dict(max=1.75, pad=140), ring="Q"),
    "D6": dict(src="D6", cam=None, camo=dict(to=1.05), badge="D6",
               then=[dict(at="done+0.2", cam="LAST", camo=dict(max=1.6, pad=60), ring=None, co="Search + rerank", dur=0.45)]),
}
RING_STATES = 2                  # the ring pulses by blending these two stills: a plain ring and a full glow
PULSE = 1.4                      # seconds for one pulse
PIP = (930, 300, 940)            # the live Grafana inset in the observability shot: left, top, width


def pulse(fc: list, lo: int, hi: int, k: int, ts: float):
    """Blend a plain ring still (input lo) and a glowing one (input hi) into a pulsing ring that fades in at ts: stream [rg<k>]."""
    pm = "format=gbrap,premultiply=inplace=1,setpts=PTS+%.3f/TB" % ts          # blend in premultiplied alpha, so the glow has no dark fringe
    fc.append("[%d:v]%s[ra%d];[%d:v]%s[rb%d]" % (lo, pm, k, hi, pm, k))
    fc.append("[ra%d][rb%d]blend=all_expr='A+(B-A)*(0.5-0.5*cos(2*PI*(T-%.3f)/%.2f))',unpremultiply=inplace=1,format=rgba,"
              "fade=t=in:st=%.3f:d=0.25:alpha=1[rg%d]" % (k, k, ts, PULSE, ts, k))
CUR_FROM = (190, 130)            # the cursor glides in from this far down and right of the control, only for a click


class Pngs:
    """Transparent overlay stills, drawn once by the browser: rings, callouts, captions, the cursor."""

    def __init__(self, pw):
        self.pw, self.br, self.pages, self.n = pw, pw.chromium.launch(), {}, 0

    def shot(self, html: str, sel: str, scale: int = 1) -> Path:
        if scale not in self.pages:
            self.pages[scale] = self.br.new_page(viewport={"width": 1920, "height": 700}, device_scale_factor=scale)
        self.n += 1
        out = WORK / ("ov%03d.png" % self.n)
        self.pages[scale].set_content(html)
        self.pages[scale].locator(sel).screenshot(path=str(out), omit_background=True)
        return out

    def ring(self, w: float, h: float, state: int) -> Path:
        s = state / (RING_STATES - 1)
        return self.shot("<style>body{margin:0;background:transparent}#w{display:inline-block;padding:44px}#r{box-sizing:border-box;width:%.1fpx;height:%.1fpx;"
                         "border:5px solid #76B900;border-radius:10px;box-shadow:0 0 0 %.1fpx rgba(118,185,0,%.2f),0 0 %.1fpx rgba(118,185,0,%.2f)}</style>"
                         "<div id=w><div id=r></div></div>" % (w, h, 2 + 8 * s, .2 + .05 * s, 10 + 24 * s, .5 + .4 * s), "#w", K)

    def callout(self, text: str) -> Path:
        return self.shot("<style>body{margin:0;background:transparent}#w{display:inline-block;padding:40px}b{display:block;background:rgba(10,30,22,.92);color:#fff;"
                         "font:700 50px/1.1 Arial,sans-serif;padding:14px 30px;border-left:12px solid #76B900;border-radius:6px;box-shadow:0 10px 30px rgba(0,0,0,.35)}"
                         "</style><div id=w><b>%s</b></div>" % html_escape(text), "#w")

    def caption(self, text: str) -> Path:
        return self.shot("<style>body{margin:0;background:transparent}span{display:inline-block;max-width:1560px;color:#fff;"
                         "font:700 32px/1.3 Arial,sans-serif;padding:8px 24px;text-shadow:0 0 2px #000,0 0 5px rgba(0,0,0,.9),1.5px 1.5px 0 #000,-1.5px -1.5px 0 #000,1.5px -1.5px 0 #000,-1.5px 1.5px 0 #000,0 3px 12px rgba(0,0,0,.6)}</style><span id=c>%s</span>" % html_escape(text), "#c")

    def cursor(self) -> Path:
        return self.shot("<style>body{margin:0;background:transparent}svg{display:block;filter:drop-shadow(0 2px 3px rgba(0,0,0,.45))}</style>"
                         '<svg id=s width=24 height=34 viewBox="0 0 36 52"><path d="M3 3 L3 40 L13 31 L20 48 L27 45 L20 28 L33 28 Z" fill="#fff" '
                         'stroke="#111" stroke-width="3" stroke-linejoin="round"/></svg>', "#s", K)


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def png_size(p: Path) -> tuple[int, int]:
    b = p.read_bytes()[16:24]
    return int.from_bytes(b[:4], "big"), int.from_bytes(b[4:], "big")


def cam_state(rect, o: dict, prev: tuple, page_h: int = H) -> tuple:
    """The page transform (scale, translate x, translate y) that frames `rect`: the rule the old in-page camera used.
    The page can be taller than the screen (the Technician Update tab is); the camera pans down it."""
    s0, tx0, ty0 = prev
    if rect:
        px = o.get("pad", 80); py = px * 0.6
        s = max(o.get("min", 1), min(o.get("max", 2.4), min((W - 2 * px) / rect["w"], (H - 2 * py) / rect["h"])))
        tx, ty = W / 2 - s * (rect["x"] + rect["w"] / 2), H / 2 - s * (rect["y"] + rect["h"] / 2)
    else:
        s = o["to"] if "to" in o else min(s0 * 1.05, o.get("max", 2.4))
        tx, ty = W / 2 - (W / 2 - tx0) * s / s0, H / 2 - (H / 2 - ty0) * s / s0
    return s, min(0.0, max(W - s * W, tx)), min(0.0, max(H - s * page_h, ty))


def _smooth(a: float, d: float, var: str = "t") -> str:
    """Smoothstep from time a over d seconds, as an ffmpeg expression."""
    u = "min(max((%s-%.3f)/%.3f,0),1)" % (var, a, max(d, 0.05))
    return "(%s*%s*(3-2*%s))" % (u, u, u)


def _path(v0: tuple, moves: list, i: int, var: str = "t") -> str:
    e, prev = "%.4f" % v0[i], v0[i]
    for a, d, st in moves:
        e += "+(%.4f)*%s" % (st[i] - prev, _smooth(a, d, var)); prev = st[i]
    return e


def time_map(st: dict, v: float, freeze: bool):
    """Which stretches of the captured step to play, how fast, and how a time in the step maps into the beat. The wait for
    a slow model is the only thing cut; everything else plays between 0.8x and 1.6x, then the last frame is held."""
    t0, t1 = st["t0"], st["t1"]
    if freeze:
        return [], 1.0, 0.0, lambda t: 0.0
    segs, done = [(t0, t1)], st["marks"].get("done")
    if done is not None and (t1 - t0) / v > 1.6:
        a = (max([c["t"] for c in st["clicks"]] or [t0])) + 0.6
        b = done - 0.4
        cut = min(b - a - 0.3, (t1 - t0) - 1.6 * v)
        if cut > 0:
            m = (a + b) / 2
            segs = [(t0, m - cut / 2), (m + cut / 2, t1)]
    total = sum(b - a for a, b in segs)
    sp = min(max(total / v, 0.8), 1.6)
    play = min(total / sp, v)
    need, kept = play * sp, []
    for a, b in segs:
        take = min(b - a, need - sum(y - x for x, y in kept))
        if take > 1e-3:
            kept.append((a, a + take))

    def out_t(t):
        c = 0.0
        for a, b in kept:
            if t <= a:
                return c / sp
            if t <= b:
                return (c + t - a) / sp
            c += b - a
        return play
    return kept, sp, play, out_t


def camera_plan(bid: str, plan: dict, st: dict, v: float, nd: float, out_t, page_h: int, subs: dict, state: tuple) -> tuple:
    """A live beat's camera moves [(start, duration, (scale, tx, ty))], ring cues [(start, target, pad)], callouts [(start, text)] and the
    camera state it ends in. Shared by the edit and by scripts/export_edit_sheet.py, so the sheet is the edit."""
    rect = lambda name: st["rects1"].get(name) or st["rects0"].get(name)
    fill = lambda t: t.format(**{k.strip("{}"): x for k, x in subs.items()}) if t else t
    moves, rings, cos = [], [], []
    cur = state
    steps = [dict(at=0.0, cam=plan.get("cam"), camo=plan.get("camo", {}), dur=max(0.6, v - 0.04), ring=plan.get("ring"), ringpad=plan.get("ringpad", 10),
                  co=plan.get("co"), has_ring=True, has_co=True)]
    for m in plan.get("then", []):
        steps.append(dict(m, has_ring="ring" in m, has_co="co" in m))
    for m in steps:
        at = m["at"]
        if isinstance(at, str):
            name, _, off = at.partition("+")
            at = out_t(st["marks"][name] + float(off or 0)) if name in st["marks"] else 0.55 * v
            at = min(at, max(0.0, nd - 0.9))               # a late move may run into the hold, never past the beat
        else:
            at = at * v
        dur = m["dur"] if m is steps[0] else m["dur"] * v
        dur = min(dur, max(0.3, nd - at - 0.05))      # the move must finish inside the beat, or the next one starts from the wrong place
        target = m.get("cam")
        r = rect(target) if target else None
        if target and not r:
            print("  %s: target %s not found on screen; the camera holds" % (bid, target))
        cur = cam_state(r, m.get("camo", {}), cur, page_h) if (r or not target) else cur
        moves.append((at, dur, cur))
        if m["has_ring"]:
            rings.append((at, m.get("ring"), m.get("ringpad", plan.get("ringpad", 10))))
        if m["has_co"]:
            cos.append((at, fill(m.get("co"))))
    return moves, rings, cos, cur


def beat_clip(pngs: Pngs, bid: str, plan: dict, st: dict, raw: Path, page_h: int, nd: float, hold: float, caption: str, subs: dict, state: tuple, out: Path) -> tuple:
    """One shot of a live scene, in a single ffmpeg pass: the captured footage re-timed to this beat's length, a ring and
    (only for a click) a cursor drawn in page space, the camera, then callout, badge and caption in screen space."""
    v = nd - hold
    freeze = plan.get("freeze", False)
    segs, sp, play, out_t = time_map(st, v, freeze)
    ins, fc, i = [], [], 0

    def add(path: Path, loop: float = 0.0) -> int:
        nonlocal i
        ins.extend((["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % loop] if loop else []) + ["-i", path]); i += 1
        return i - 1

    # base: the footage
    if freeze:
        still = WORK / ("still_%s.jpg" % bid)
        run(ffmpeg(), "-y", "-ss", "%.3f" % max(0.0, st["t1"] - 0.15), "-i", raw, "-frames:v", "1", "-q:v", "2", still)
        add(still, nd); fc.append("[0:v]format=yuv444p[base]")
    else:
        add(raw)
        parts = ["[0:v]trim=start=%.3f:end=%.3f,setpts=(PTS-STARTPTS)/%.4f,fps=%d[s%d]" % (a, b, sp, FPS, k) for k, (a, b) in enumerate(segs)]
        fc += parts
        fc.append("%sconcat=n=%d:v=1:a=0,tpad=stop_mode=clone:stop_duration=%.3f,format=yuv444p[base]"
                  % ("".join("[s%d]" % k for k in range(len(segs))), len(segs), max(0.0, nd - play)))
    last = "[base]"

    moves, rings, cos, end_state = camera_plan(bid, plan, st, v, nd, out_t, page_h, subs, state)
    rect = lambda name: st["rects1"].get(name) or st["rects0"].get(name)

    # page-space overlays: rings (pulsing), then the cursor
    for k, (ts, name, pad) in enumerate(rings):
        if not name:
            continue
        te = rings[k + 1][0] if k + 1 < len(rings) else nd
        r = rect(name)
        if not r:
            continue
        w, h = r["w"] + 2 * pad, r["h"] + 2 * pad
        x, y = (r["x"] - pad - 44) * K, (r["y"] - pad - 44) * K
        pulse(fc, add(pngs.ring(w, h, 0), nd), add(pngs.ring(w, h, RING_STATES - 1), nd), k, ts)
        fc.append("%s[rg%d]overlay=x=%.1f:y=%.1f:format=yuv444:enable='between(t,%.3f,%.3f)'[g%d]" % (last, k, x, y, ts, te, k))
        last = "[g%d]" % k
    for n, c in enumerate(c for c in st["clicks"] if c.get("show") and not freeze):
        tc = out_t(c["t"])
        x1, y1 = c["x"] * K, c["y"] * K
        x0, y0 = x1 + CUR_FROM[0] * K, y1 + CUR_FROM[1] * K
        ts = max(0.0, tc - 0.6)
        e = _smooth(ts, min(0.5, tc - ts), "t")
        k = add(pngs.cursor())
        fc.append("%s[%d:v]overlay=x='%.1f+(%.1f)*%s':y='%.1f+(%.1f)*%s':format=yuv444:enable='between(t,%.3f,%.3f)'[cu%d]"
                  % (last, k, x0, x1 - x0, e, y0, y1 - y0, e, ts, tc + 0.5, n))
        last = "[cu%d]" % n

    # camera: a sub-pixel zoom and pan. `perspective` maps a window of the page, of the frame's own shape, onto the whole
    # frame (scale + overlay snap to whole, even pixels and shimmer); the part of a tall page below the screen is cropped off.
    on = "(on/%d)" % FPS
    S, TX, TY = (_path(state, moves, i, on) for i in range(3))
    x0, y0 = "(-%d*(%s)/(%s))" % (K, TX, S), "(-%d*(%s)/(%s))" % (K, TY, S)
    fc.append("%sperspective=x0='%s':y0='%s':x1='%s+%d/(%s)':y1='%s':x2='%s':y2='%s+%d/(%s)':x3='%s+%d/(%s)':y3='%s+%d/(%s)'"
              ":interpolation=cubic:eval=frame%s,scale=%d:%d:flags=lanczos,format=yuv420p[cam]"
              % (last, x0, y0, x0, W * K, S, y0, x0, y0, page_h * K, S, x0, W * K, S, y0, page_h * K, S,
                 ",crop=%d:%d:0:0" % (W * K, H * K) if page_h > H else "", W, H))
    last = "[cam]"

    # screen-space overlays: callouts, the product badge, the caption
    for k, (ts, text) in enumerate(cos):
        if not text:
            continue
        te = cos[k + 1][0] if k + 1 < len(cos) else nd
        p = pngs.callout(text)
        j = add(p, te - ts + 0.1)
        fc.append("[%d:v]format=rgba,setpts=PTS+%.3f/TB,fade=t=in:st=%.3f:d=0.3:alpha=1[co%d]" % (j, ts, ts, k))
        fc.append("%s[co%d]overlay=x='16-40*(1-%s)':y=10:enable='between(t,%.3f,%.3f)'[o%d]" % (last, k, _smooth(ts, 0.34, "t"), ts, te, k))
        last = "[o%d]" % k
    if plan.get("badge"):
        b = badge_png(pngs.pw, plan["badge"]); bw, _ = png_size(b)
        j = add(b)
        fc.append("%s[%d:v]overlay=x=%d:y=44:enable='gte(t,0.15)'[bd]" % (last, j, W - bw - 48))
        last = "[bd]"
    if CAPTIONS:
        cp = pngs.caption(caption); cw, ch = png_size(cp)
        j = add(cp)
        fc.append("%s[%d:v]overlay=x=%d:y=%d[fin]" % (last, j, (W - cw) // 2, H - 16 - ch))
    else:
        fc.append("%snull[fin]" % last)
    run(ffmpeg(), "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[fin]", "-t", "%.3f" % nd, "-r", str(FPS), "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast", out)
    return end_state


def live_piece(pngs: Pngs, name: str, rows, durs, holds, texts, tl: dict, subs: dict, out: Path) -> Path:
    """A piece of live scenes: one clip per beat, the camera carried from one to the next."""
    clips, state = [], (1.0, 0.0, 0.0)
    for (bid, _), nd, hold, cap in zip(rows, durs, holds, texts):
        plan = LIVE_PLAN[bid]
        sc = tl["scenes"][plan["src"][0]]
        st = next(s for s in sc["steps"] if s["id"] == plan["src"])
        clip = WORK / ("beat_%s.mp4" % bid)
        state = beat_clip(pngs, bid, plan, st, FOOT / sc["file"], sc.get("page", [W, H])[1], nd, hold, cap, subs, state, clip)
        clips.append(clip)
    lst = WORK / ("list_%s.txt" % name)
    lst.write_text("".join("file '%s'\n" % c for c in clips))
    run(ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    return out


def pip_overlay(pngs: Pngs, bg: Path, tl: dict, nd: float, out: Path) -> Path:
    """Lay the live Grafana footage, small, into the frame of the observability infographic and ring, one after another, its
    primary figures and the two DCGM graphs. Rings are drawn at inset scale, after the footage is scaled down."""
    sc = tl["scenes"]["G"]; st = sc["steps"][0]
    x0, y0, w = PIP
    sc_f = w / W; h = round(H * sc_f)
    ts = 0.34 * nd                                           # the footage appears just as the frame does
    cues = [("STATS", dict(x=16, y=16, w=1888, h=184), 0.46), ("GPU", st["rects1"]["GPU"], 0.60), ("POWER", st["rects1"]["POWER"], 0.72)]
    ins = ["-i", bg, "-ss", "%.3f" % st["t0"], "-t", "%.3f" % nd, "-i", FOOT / sc["file"]]
    fc = ["[1:v]scale=%d:%d:flags=lanczos,fps=%d,format=yuva420p,setpts=PTS-STARTPTS+%.3f/TB,fade=t=in:st=%.3f:d=0.4:alpha=1[pip]" % (w, h, FPS, ts, ts),
          "[0:v]format=yuv420p[b]", "[b][pip]overlay=x=%d:y=%d:format=auto[v0]" % (x0, y0)]
    last, n = "[v0]", 2
    for k, (name, r, f) in enumerate(cues):
        pad = 4
        rw, rh = r["w"] * sc_f + 2 * pad, r["h"] * sc_f + 2 * pad
        rx, ry = x0 + r["x"] * sc_f - pad - 44, y0 + r["y"] * sc_f - pad - 44
        for png in (pngs.ring(rw, rh, 0), pngs.ring(rw, rh, RING_STATES - 1)):
            ins += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % nd, "-i", png]
        pulse(fc, n, n + 1, 10 + k, f * nd)
        n += 2
        fc.append("[rg%d]scale=iw/%d:ih/%d[rs%d]" % (10 + k, K, K, k))
        fc.append("%s[rs%d]overlay=x=%.1f:y=%.1f:format=yuv444:enable='gte(t,%.3f)'[v%d]" % (last, k, rx, ry, f * nd, k + 1))
        last = "[v%d]" % (k + 1)
    run(ffmpeg(), "-y", *ins, "-filter_complex", ";".join(fc), "-map", last, "-t", "%.3f" % nd, "-r", str(FPS), "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "veryfast", out)
    return out


# ------------------------------------------------------------------ main
# (output piece, script scene, beat ids or None for all): the title card and the problem, then the stamped-note visual, then the live app
PIECES = [("P", "P", ["P1", "P2", "P3", "P4"]), ("O", "P", ["P5"]), ("H", "H", None), ("A", "A", ["A1", "A2", "A4"]), ("B", "B", None), ("C", "C", None), ("D", "D", None),
          ("V", "V", None), ("E", "E", None), ("I", "G", None), ("F", "F", None), ("K", "K", None)]
LIVE = "ACD"
BRIDGE_BEFORE = "AHBCDVEIFK"   # ease from one screen to the next instead of cutting: problem, dashboard, process, ingest, assistant, impact, architecture, observability, summary


def main():
    ap = argparse.ArgumentParser(description="Build the client demo video.")
    ap.add_argument("--slide-only", action="store_true", help="only the process-slide clip")
    ap.add_argument("--scene", help="build only these pieces, e.g. O or OE (for iteration)")
    ap.add_argument("--music", help="a music bed to mix under the narration (default: bed.* in ~/.cache/asoia-demo-music, if there is one)")
    ap.add_argument("--keep", help="copy each piece's mp4 into this directory")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        pptx = ROOT / "docs" / "architecture-deck.pptx"
        if not args.scene:
            html, dur = slide_html(pptx)
            (WORK / "slide.html").write_text(html)
            vdir = WORK / "v_slide"
            br = pw.chromium.launch()
            ctx = br.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir),
                                 record_video_size={"width": W, "height": H})
            pg = ctx.new_page()
            pg.goto((WORK / "slide.html").as_uri()); pg.wait_for_timeout(int((dur + 1.0) * 1000))
            ctx.close(); br.close()
            run(ffmpeg(), "-y", "-ss", "0.25", "-i", next(vdir.glob("*.webm")), "-t", "%.2f" % (dur + 0.8), "-vf",
                "scale=%d:%d:flags=lanczos,fps=%d" % (W, H, FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
                "-preset", "veryfast", "-an", OUT / "process-slide-preview.mp4")
            print("process-slide-preview.mp4: %.1f s" % (dur + 0.8))
            if args.slide_only:
                return

        script = beats()
        tl = load_timeline()
        subs = dict(tl["subs"])
        stale = check()
        print("live footage: %s" % ("current, so no box is needed." if not stale else
              "STALE for scene(s) %s - the app (or the Grafana dashboard, or what is typed into it) changed since it was captured.\n"
              "  If the screen is unaffected: python scripts/demo_footage.py --restamp. Otherwise capture again on a box." % "".join(stale)))

        def fill(t):
            for k, v in subs.items():
                t = t.replace(k, v)
            return t
        slide_driven, _ = slide_html(pptx, driven=True)
        (WORK / "slide_driven.html").write_text(slide_driven)
        (WORK / "intro.html").write_text(intro_html())
        (WORK / "problem.html").write_text(problem_html())
        (WORK / "value.html").write_text(value_html(subs))
        (WORK / "comp.html").write_text(architecture_html())
        (WORK / "observ.html").write_text(observ_html())
        (WORK / "end.html").write_text(end_html(subs))
        (WORK / "brand_open.html").write_text(brand_html(False))
        (WORK / "brand_close.html").write_text(brand_html(True))
        local = {"P": ((WORK / "problem.html").as_uri(), scene_P()),
                 "O": ((WORK / "intro.html").as_uri(), scene_O()),
                 "B": ((WORK / "slide_driven.html").as_uri(), scene_B()),
                 "V": ((WORK / "value.html").as_uri(), scene_V()),
                 "E": ((WORK / "comp.html").as_uri(), scene_E()),
                 "I": ((WORK / "observ.html").as_uri(), scene_I()),
                 "F": ((WORK / "end.html").as_uri(), scene_F()),
                 "H": ((WORK / "brand_open.html").as_uri(), scene_brand()),
                 "K": ((WORK / "brand_close.html").as_uri(), scene_brand())}
        want = list(args.scene) if args.scene else [p[0] for p in PIECES]
        pngs = Pngs(pw)
        parts, total = [], 0.0
        for name, sc, ids in PIECES:
            if name not in want:
                continue
            if name == "K" and outro_file():            # the supplied Deloitte outro replaces the closing card
                m = WORK / "m_K.mp4"; build_outro(pw, outro_file(), m)
                if parts:
                    br_clip = WORK / "bridge_K.mp4"; bridge(parts[-1], m, br_clip); parts.append(br_clip); total += 0.5
                parts.append(m); total += outro_len()
                print("piece K: the supplied Deloitte outro, %.1f s" % outro_len())
                if args.keep:
                    Path(args.keep).mkdir(parents=True, exist_ok=True); shutil.copy(m, Path(args.keep) / "piece_K.mp4")
                continue
            rows = [r for r in script[sc] if ids is None or r[0] in ids]
            files, vdur = zip(*[voice(fill(t)) for _, t in rows])
            holds = [HOLD.get(i, 0.0) for i, _ in rows]
            durs = [v + h for v, h in zip(vdur, holds)]
            tail = F_TAIL if name == "F" else 0.0
            texts = [fill(t) for _, t in rows]
            if name in LIVE:
                shown = live_piece(pngs, name, rows, durs, holds, texts, tl, subs, WORK / (name + "_v.mp4"))
            else:
                url, plan = local[name]
                shown = record(pw, name, url, texts, durs, plan, tail, holds)
                if name == "I":
                    shown = pip_overlay(pngs, shown, tl, sum(durs), WORK / "I_pip.mp4")
            wavf = WORK / (name + ".wav"); join_wavs(list(files), wavf, holds)
            m = WORK / ("m_" + name + ".mp4"); mux(shown, wavf, sum(durs) + tail, m)
            if name in BRIDGE_BEFORE and parts:
                br_clip = WORK / ("bridge_%s.mp4" % name)
                bridge(parts[-1], shown, br_clip)
                parts.append(br_clip); total += 0.5
            parts.append(m)
            total += sum(durs) + tail
            print("piece %s: %d beats, %.1f s" % (name, len(rows), sum(durs) + tail))
            if args.keep:
                Path(args.keep).mkdir(parents=True, exist_ok=True); shutil.copy(m, Path(args.keep) / ("piece_%s.mp4" % name))
        if not args.scene:
            final = OUT / "demo-preview.mp4"
            bed = music_file(args.music)
            concat(parts, WORK / "nomusic.mp4" if bed else final)
            if bed:
                add_music(WORK / "nomusic.mp4", bed, final)
            print("music bed: %s" % (bed or "none (put one at %s/bed.<ext> or pass --music)" % MUSIC_DIR))
            print("demo-preview.mp4: %.0f s total, %.1f MB" % (total, final.stat().st_size / 1e6))

if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
