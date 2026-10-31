#!/usr/bin/env python
"""Build the demo-video PREVIEW: docs/demo/process-slide-preview.mp4 and demo-preview.mp4.

    python scripts/make_demo_preview.py [--slide-only] [--scene A] [--keep DIR]

Run it with an interpreter that has `playwright`, `imageio-ffmpeg` and
`nvidia-riva-client` - deliberately NOT project dependencies, so put them in a throwaway
venv (`python -m venv /tmp/demoenv && /tmp/demoenv/bin/pip install playwright
imageio-ffmpeg nvidia-riva-client && /tmp/demoenv/bin/python -m playwright install
chromium`), then run this from the project root with that interpreter.

HOW IT IS EDITED

The script in docs/DEMO_VIDEO.md is a table of BEATS - one short sentence each. Every beat
is voiced on its own (NVIDIA Riva Magpie TTS, 44.1 kHz, sped up slightly), so its exact
length is known, and everything on screen for that beat is driven from that length:

  * a camera that is ALWAYS moving - every beat eases to a new framing over the whole beat,
    so nothing holds still for more than a moment;
  * a keyword callout that lands on the beat, a pulsing ring on what is being talked
    about, and a subtitle for the sentence;
  * the live action (typing, clicking) paced to finish inside the beat.

That is how words and pictures stay together without a video editor: the audio is cut to
the picture, not the other way round.

WHAT IT IS, AND IS NOT

A preview to judge pacing and wording - not the client cut. App scenes are recorded from
the LOCAL app against a COPY of the dataset (the real database is never written), so what
cannot run on a laptop is not shown: dictation (hosted ASR), the semantic answer (NIMs and
Milvus) and live Grafana/Attu (scene E uses stills captured on the L40S). The process slide
is rendered from the deck's own XML, not by PowerPoint. docs/demo/README.md lists these.
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
GAP = 0.12                       # silence after each beat's voice
TEMPO = 1.06                     # speech speed-up (pitch preserved)
TTS_CACHE = Path.home() / ".cache" / "asoia-demo-tts"
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
def beats():
    """{scene letter: [(beat id, narration)]} from the beat table in docs/DEMO_VIDEO.md."""
    out: dict[str, list] = {}
    for line in (ROOT / "docs" / "DEMO_VIDEO.md").read_text().splitlines():
        m = re.match(r"\| ([A-F])(\d) \| (.+?) \| (.+) \|$", line)
        if m:
            out.setdefault(m.group(1), []).append((m.group(1) + m.group(2), m.group(3)))
    assert sorted(out) == list("ABCDEF"), "expected scenes A-F in docs/DEMO_VIDEO.md, found %s" % sorted(out)
    return out


# ------------------------------------------------------------------ voice
_voice_cache: dict[str, tuple[Path, float]] = {}


def voice(text: str) -> tuple[Path, float]:
    """Voice one beat, speed it up, and pad it with GAP. Returns (wav, seconds)."""
    if text in _voice_cache:
        return _voice_cache[text]
    import _env  # noqa: F401  - .env like stack.sh; the key is never printed
    import hashlib
    cached = TTS_CACHE / (hashlib.sha1((VOICE + text).encode()).hexdigest()[:16] + ".pcm")
    if not cached.exists():
        import riva.client as rc
        auth = rc.Auth(uri="grpc.nvcf.nvidia.com:443", use_ssl=True, metadata_args=[
            ["function-id", "877104f7-e885-42b9-8de8-f6e4c6303969"],
            ["authorization", "Bearer " + os.environ["NVIDIA_API_KEY"]]])
        for wait in (0, 4, 10, 25, 45):               # the free endpoint rate-limits bursts
            time.sleep(wait)
            try:
                r = rc.SpeechSynthesisService(auth).synthesize(
                    text, voice_name=VOICE, language_code="en-US", sample_rate_hz=RATE,
                    encoding=rc.AudioEncoding.LINEAR_PCM)
                break
            except Exception as e:
                if "RESOURCE_EXHAUSTED" not in str(e) or wait == 45:
                    raise
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(r.audio)
    n = len(_voice_cache)
    raw, fast = WORK / ("raw%d.wav" % n), WORK / ("beat%d.wav" % n)
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(cached.read_bytes())
    run(ffmpeg(), "-y", "-i", raw, "-filter:a", "atempo=%.3f,apad=pad_dur=%.3f" % (TEMPO, GAP), "-ar", RATE, "-ac", 1, fast)
    with wave.open(str(fast)) as w:
        dur = w.getnframes() / w.getframerate()
    _voice_cache[text] = (fast, dur)
    return fast, dur


def join_wavs(paths, out: Path):
    with wave.open(str(out), "wb") as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(RATE)
        for p in paths:
            with wave.open(str(p)) as w:
                o.writeframes(w.readframes(w.getnframes()))


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
  #__cap span{display:inline-block;max-width:1560px;background:rgba(10,20,16,.80);color:#fff;font:600 30px/1.3 Arial,sans-serif;padding:8px 24px;border-radius:10px}
  .__co{position:fixed;left:var(--co-x,56px);top:var(--co-y,50px);z-index:99998;pointer-events:none}
  .__co b{display:block;background:rgba(10,30,22,.92);color:#fff;font:700 50px/1.1 Arial,sans-serif;padding:14px 30px;border-left:12px solid #76B900;border-radius:6px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
  .__ring{position:absolute;z-index:99990;pointer-events:none;border:5px solid #76B900;border-radius:10px;animation:__p .8s ease-in-out infinite alternate}
  @keyframes __p{from{box-shadow:0 0 0 2px rgba(118,185,0,.2),0 0 10px rgba(118,185,0,.5)}to{box-shadow:0 0 0 10px rgba(118,185,0,.25),0 0 34px rgba(118,185,0,.9)}}
  #__cur{position:fixed;width:30px;height:30px;border-radius:50%;background:rgba(118,185,0,.55);border:3px solid #76B900;z-index:100000;pointer-events:none;transform:translate(-50%,-50%)}
  .__rip{position:fixed;width:30px;height:30px;border-radius:50%;border:4px solid #76B900;z-index:100000;pointer-events:none;transform:translate(-50%,-50%)}`;
  document.head.appendChild(css);
  const cap = Object.assign(document.createElement('div'), {id: '__cap'}); html.appendChild(cap);
  const cur = Object.assign(document.createElement('div'), {id: '__cur'}); cur.style.left = '-100px'; html.appendChild(cur);
  addEventListener('mousemove', e => { cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px'; });
  addEventListener('mousedown', e => { const r = document.createElement('div'); r.className = '__rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
    html.appendChild(r); r.animate([{transform: 'translate(-50%,-50%) scale(.6)', opacity: 1}, {transform: 'translate(-50%,-50%) scale(3)', opacity: 0}], {duration: 520}).onfinish = () => r.remove(); });

  addEventListener('scroll', () => scrollTo(0, 0), true);
  window.__mat = () => { const m = new DOMMatrix(getComputedStyle(body).transform); return {s: m.a, tx: m.e, ty: m.f}; };
  window.__find = d => {
    if (Array.isArray(d)) { const rs = d.map(window.__find).filter(Boolean); if (!rs.length) return null;
      const x0 = Math.min(...rs.map(r => r.x)), y0 = Math.min(...rs.map(r => r.y)), x1 = Math.max(...rs.map(r => r.x + r.w)), y1 = Math.max(...rs.map(r => r.y + r.h));
      return {x: x0, y: y0, w: x1 - x0, h: y1 - y0}; }
    if (d.rect) return {x: d.rect[0], y: d.rect[1], w: d.rect[2], h: d.rect[3]};
    let el = null;
    if (d.fn) el = (new Function('return (' + d.fn + ')'))()();
    else if (d.sel) el = document.querySelectorAll(d.sel)[d.nth || 0];
    else if (d.text) { const w = document.createTreeWalker(body, NodeFilter.SHOW_TEXT); let n;
      while ((n = w.nextNode())) if (n.textContent.includes(d.text)) { const e = n.parentElement, r = e.getBoundingClientRect(); if (r.width > 0 && r.height > 0) { el = e; break; } } }
    if (!el) return null;
    if (d.up) el = el.closest(d.up) || el;
    const r = el.getBoundingClientRect(), b = body.getBoundingClientRect(), m = window.__mat();
    const o = {x: (r.left - b.left) / m.s, y: (r.top - b.top) / m.s, w: r.width / m.s, h: r.height / m.s};
    if (d.skip) { o.y += d.skip; o.h = Math.max(40, o.h - d.skip); }
    if (d.top) o.h = Math.min(o.h, d.top);
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
  window.__ring = (d, pad) => { document.querySelectorAll('.__ring').forEach(e => e.remove()); if (!d) return;
    const L = window.__find(d); if (!L) return; pad = pad || 10; const e = document.createElement('div'); e.className = '__ring';
    Object.assign(e.style, {left: (L.x - pad) + 'px', top: (L.y - pad) + 'px', width: (L.w + 2 * pad) + 'px', height: (L.h + 2 * pad) + 'px'}); body.appendChild(e); };
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
def b64(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


K = 1090 / 1600                      # stills are shown 1090 px wide; screenshot px -> layout px


def still(panel_x, panel_y, x, y, w, h):
    return {"rect": [panel_x + x * K, panel_y + y * K, w * K, h * K]}


def components_html() -> str:
    chips = [("NIM · Nemotron 8B", "language"), ("NIM · Embedding", "search"), ("NIM · Reranking", "search"),
             ("Riva · Parakeet ASR", "speech"), ("NeMo Guardrails", "safety rails"),
             ("NeMo Evaluator", "release scoring"), ("DCGM", "GPU telemetry")]
    shots = ROOT / "docs" / "screenshots"
    return """<!doctype html><meta charset=utf-8><style>
:root{--co-x:1180px;--co-y:40px}body{margin:0;width:1920px;height:1080px;background:#14302A;font-family:Arial,sans-serif;color:#fff;overflow:hidden;position:relative}
h1{position:absolute;left:70px;top:46px;margin:0;font-size:46px}p.sub{position:absolute;left:70px;top:112px;margin:0;font-size:24px;color:#C8D6BE}
.chip{position:absolute;left:70px;width:560px;height:86px;border-radius:12px;background:#5B8C3A;border:2px solid #446B29;opacity:0;padding:14px 22px;box-sizing:border-box}
.chip b{font-size:30px;display:block}.chip i{font-size:20px;color:#DCE8CF;font-style:normal}.chip em{position:absolute;right:16px;top:14px;background:#C1562A;font-size:18px;font-style:normal;padding:3px 12px;border-radius:12px}
.pan{position:absolute;left:700px;top:170px;width:1090px;height:750px;border-radius:12px;overflow:hidden;opacity:0;border:3px solid #76B900;background:#fff}
.pan img{width:100%%;display:block}.cap{position:absolute;left:700px;top:926px;font-size:20px;color:#C8D6BE}
</style><h1>NVIDIA at every step that needs a model</h1><p class=sub>One L40S carries the whole stack</p>
%s
<div class=pan id=g><img src="%s"></div><div class=pan id=a><img src="%s"></div>
<div class=cap id=cg style="opacity:0">Captured on the L40S, 2026-10-09 &middot; Grafana + DCGM</div>
<div class=cap id=ca style="opacity:0">Captured on the L40S, 2026-10-09 &middot; Attu, collection &lsquo;updates&rsquo;</div>
<script>const $=id=>document.getElementById(id);
const pop=e=>e.animate([{opacity:0,transform:'translateX(-50px) scale(.94)'},{opacity:1,transform:'none'}],{duration:420,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
window.__chip=i=>pop($('chip'+i));
window.__pulse=i=>$('chip'+i).animate([{transform:'scale(1)',filter:'brightness(1)'},{transform:'scale(1.06)',filter:'brightness(1.25)'},{transform:'scale(1)',filter:'brightness(1)'}],{duration:520});
window.__tag=i=>{const t=document.createElement('em');t.textContent='hosted';$('chip'+i).appendChild(t);};
window.__panel=k=>{for(const p of ['g','a']){$(p).style.transition='opacity .45s';$(p).style.opacity=(p===k)?1:0;}
 $('cg').style.opacity=(k==='g')?1:0;$('ca').style.opacity=(k==='a')?1:0;};
</script>""" % ("".join('<div class=chip id=chip%d style="top:%dpx"><b>%s</b><i>%s</i></div>' % (i, 190 + i * 110, a, b) for i, (a, b) in enumerate(chips)),
                b64(shots / "09-grafana-dashboard.jpg"), b64(shots / "11-attu-schema-1024.jpg"))


def end_html() -> str:
    cards = [("Own your models", "No hosted endpoint to retire underneath you"),
             ("One card", "About 30 GB of a 46 GB L40S"),
             ("Reproducible", "A pinned container at temperature 0"),
             ("Checked", "Every figure verified, every call measured")]
    return """<!doctype html><meta charset=utf-8><style>
body{margin:0;width:1920px;height:1080px;background:#14302A;font-family:Arial,sans-serif;color:#fff;overflow:hidden;position:relative}
h1{position:absolute;left:0;right:0;top:110px;text-align:center;margin:0;font-size:84px;opacity:0}
.c{position:absolute;top:290px;width:400px;height:280px;background:#1E4035;border:2px solid #2E5245;border-radius:14px;padding:30px;box-sizing:border-box;opacity:0}
.c b{display:block;color:#76B900;font-size:42px;margin-bottom:16px}.c span{font-size:27px;color:#DCE8CF;line-height:1.35}
#big{position:absolute;left:0;right:0;top:650px;text-align:center;font-size:92px;font-weight:700;opacity:0}#big u{text-decoration:none;color:#76B900}
#e{position:absolute;left:0;right:0;top:0;bottom:0;background:#14302A;opacity:0;text-align:center}#e h2{margin:300px 0 22px;font-size:90px}#e p{font-size:32px;color:#C8D6BE;margin:8px}
#e small{display:block;margin-top:44px;font-size:26px;color:#8FA58A}
</style><h1 id=t>Why it matters</h1>%s<div id=big>Fast. <u>Grounded.</u> Yours to run.</div>
<div id=e><h2>Let's talk about your shop.</h2><p>Automotive Service Operations Intelligence Agent</p><p>NVIDIA NIM &middot; Riva &middot; NeMo &middot; DCGM</p>
<small>[ your name &middot; contact details ]</small></div>
<script>const $=id=>document.getElementById(id);
const up=(e,d)=>e.animate([{opacity:0,transform:'translateY(60px) scale(.96)'},{opacity:1,transform:'none'}],{duration:d||520,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});
window.__title=()=>up($('t'));window.__card=i=>up(document.querySelectorAll('.c')[i]);window.__big=()=>up($('big'),600);
window.__end=()=>$('e').animate([{opacity:0},{opacity:1}],{duration:500,fill:'forwards'});
</script>""" % "".join('<div class=c style="left:%dpx"><b>%s</b><span>%s</span></div>' % (80 + i * 440, a, b) for i, (a, b) in enumerate(cards))


# ------------------------------------------------------------------ recording
def record(pw, name: str, url: str, texts, durs, plan, prep=None, tail=0.0) -> Path:
    """Record one scene. `plan[i]` is the choreography dict for beat i; it runs in real time,
    each beat starting at the running total of the voiced durations before it."""
    vdir = WORK / ("v_" + name)
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir),
                              record_video_size={"width": W, "height": H})
    page = ctx.new_page()
    t_ctx = time.time()
    page.goto(url, wait_until="load", timeout=90000)
    page.wait_for_timeout(2200)
    inject(page)
    if prep:
        prep(page)
    total = sum(durs) + tail
    t0 = time.perf_counter(); t_wall = time.time()
    at = 0.0
    for text, d, b in zip(texts, durs, plan):
        lag = t0 + at - time.perf_counter()
        if lag > 0:
            time.sleep(lag)
        page.evaluate("b => window.__beat(b)", {"cap": text, "ms": int(d * 1000) - 40, "cam": b.get("cam"),
                                                 "camo": b.get("camo"), "ring": b.get("ring"),
                                                 "ringpad": b.get("ringpad"), "co": b.get("co")})
        if b.get("act"):
            b["act"](page, d)
        at += d
    lag = t0 + total - time.perf_counter()
    if lag > 0:
        time.sleep(lag)
    start = t_wall - t_ctx
    ctx.close(); browser.close()
    webm = next(vdir.glob("*.webm"))
    out = WORK / (name + ".mp4")
    run(ffmpeg(), "-y", "-ss", "%.2f" % start, "-i", webm, "-t", "%.2f" % total, "-vf",
        "scale=%d:%d:flags=lanczos,fps=%d" % (W, H, FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "21", "-preset", "veryfast", "-an", out)
    return out


def mux(video: Path, wav: Path | None, total: float, out: Path):
    run(ffmpeg(), "-y", "-i", video, "-i", wav, "-filter_complex", "[1:a]apad,atrim=0:%.2f[a]" % total,
        "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", "%.2f" % total, out)


def concat(parts, out: Path):
    lst = WORK / "list.txt"
    lst.write_text("".join("file '%s'\n" % p for p in parts))
    run(ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-crf", "27", "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "copy",
        "-movflags", "+faststart", out)


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
    page.wait_for_timeout(350)


def glide(page, loc, steps=14):
    bb = loc.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, steps=steps)


# ------------------------------------------------------------------ choreography, one scene each
def scene_A(n_safety):
    KPI = {"text": "Open repair orders", "up": 'div[style*="flex-wrap"]'}
    ROW = {"text": "below minimum"}
    TILE = {"text": "Safety - do not release", "up": 'div[style*="border-radius:10px"]'}
    PROM = [{"text": "Promise missed", "up": 'div[style*="border-radius:10px"]'},
            {"text": "Blocked", "up": 'div[style*="border-radius:10px"]'}]
    return [dict(cam=KPI, camo=dict(max=1.25, pad=140)),
            dict(cam=ROW, camo=dict(max=1.7, pad=70), ring=ROW, co="Safety findings"),
            dict(cam=PROM, camo=dict(max=1.9, pad=120), ring=PROM, co="Missed promises"),
            dict(cam=TILE, camo=dict(max=2.3, pad=200), ring=TILE, co="%d unsafe" % n_safety),
            dict(cam=None, camo=dict(to=1.0), co="NVIDIA stack"),
            dict(cam=ROW, camo=dict(max=3.2, pad=20))]


def scene_B():
    def stage(i, co):
        c = [{"sel": '[data-name="anim-s%d-card"]' % i}, {"sel": '[data-name="anim-s%d-badge"]' % i}]
        return dict(cam=c, camo=dict(max=1.55, pad=110), co=co,
                    ring={"sel": '[data-name="anim-s%d-badge"]' % i}, ringpad=6,
                    act=lambda page, d, i=i: page.evaluate("i => window.__stage(i)", i))
    out = [stage(0, "Capture"), stage(1, "Understand"), stage(2, "Verify"), stage(3, "Record"), stage(4, "Decide")]
    stats = [{"sel": '[data-name="anim-o%d-card"]' % i} for i in range(3)]

    def last(page, d):
        page.evaluate("() => window.__stage(4)")
        page.wait_for_timeout(int(d * 450))
        page.evaluate("() => window.__stats()")
    out[4]["act"] = last
    out[4]["cam"] = [{"sel": '[data-name="anim-s4-card"]'}, *stats]
    out[4]["camo"] = dict(max=1.25, pad=60)
    return out


def scene_C():
    M = {"text": "Measurement", "up": "label"}
    V = {"text": "Value", "up": "label"}
    S = {"text": "Spec minimum", "up": "label"}
    BTN = {"text": "Submit structured update", "up": "button"}
    DIFF = {"fn": "()=>[...document.querySelectorAll('textarea')].find(t=>t.value.includes('SAFETY'))", "top": 150}
    DIFF2 = {"fn": "()=>[...document.querySelectorAll('textarea')].find(t=>t.value.includes('SAFETY'))", "top": 300}

    def c1(page, d):
        page.get_by_label("Measurement").fill("front_pad_thickness")
        page.get_by_label("Value", exact=True).fill("")
        page.keyboard.type("1.8", delay=int(d * 1000 * 0.35 / 3))

    def c2(page, d):
        page.get_by_label("Spec minimum").fill("")
        page.keyboard.type("3.0", delay=int(d * 1000 * 0.4 / 3))

    def c3(page, d):
        glide(page, page.get_by_role("button", name="Submit structured update"), steps=18)
        page.wait_for_timeout(int(d * 1000 * 0.2))
        page.get_by_role("button", name="Submit structured update").click()

    return [dict(cam=[M, V, S], camo=dict(max=1.8, pad=120), co="1.8 mm", act=c1),
            dict(cam=[V, S], camo=dict(max=2.4, pad=140), ring=S, co="min 3.0 mm", act=c2),
            dict(cam=BTN, camo=dict(max=2.2, pad=300), ring=BTN, act=c3),
            dict(cam=DIFF, camo=dict(max=2.0, pad=90), ring=DIFF, ringpad=6, co="Flagged unsafe"),
            dict(cam=DIFF2, camo=dict(max=1.4, pad=90))]


def warm_ask(page):
    """Ask once off-camera so one-off start-up work (backend probes) is not in the take."""
    page.locator("textarea").first.fill("Which vehicles cannot be released on safety grounds?")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.get_by_text("computed from the records").first.wait_for(timeout=90000)
    page.locator("button.secondary", has_text="Clear").click()
    page.wait_for_timeout(500)


def scene_D():
    Q = {"fn": "()=>[...document.querySelectorAll('textarea')].find(t=>t.offsetParent)"}
    ANS = [{"text": "Safety finding"}, {"text": "computed from the records"}]
    TOOLS = {"text": "computed from the records"}
    QTXT = "Which vehicles cannot be released on safety grounds?"

    def d1(page, d):
        page.locator("textarea").first.click()

    def d2(page, d):                                   # type in the first half, ask, so the answer lands in beat 3
        page.keyboard.type(QTXT, delay=int(d * 1000 * 0.5 / len(QTXT)))
        page.get_by_role("button", name="Ask", exact=True).click()

    def d3(page, d):                                   # re-aim the camera once the answer has actually rendered
        t0 = time.perf_counter()
        page.get_by_text("computed from the records").first.wait_for(timeout=15000)
        page.evaluate("""() => { for (const e of document.querySelectorAll('*')) if (e.scrollTop > 0) e.scrollTop = 0; }""")
        left = max(900, int((d - (time.perf_counter() - t0)) * 1000))
        page.evaluate("a => { window.__cam(a, {max: 1.35, pad: 70, ms: %d}); window.__co('Cited · no model call'); }" % left, ANS)

    def d4(page, d):                                   # scroll the answer to its source line, then close in on it
        page.evaluate("""() => { for (const e of document.querySelectorAll('*')) if (e.scrollHeight > e.clientHeight + 20 && getComputedStyle(e).overflowY !== 'visible') e.scrollTop = e.scrollHeight; }""")
        page.wait_for_timeout(250)
        page.evaluate("t => { window.__cam(t, {max: 2.2, pad: 60, ms: %d}); window.__ring(t, 8); window.__co(); }" % int(d * 1000 - 300), TOOLS)

    return [dict(cam=Q, camo=dict(max=1.5, pad=140), act=d1),
            dict(cam=Q, camo=dict(max=1.75, pad=140), ring=Q, act=d2),
            dict(cam=None, camo=dict(to=1.05), act=d3),
            dict(cam=None, camo=dict(to=1.05), act=d4)]


def scene_E():
    PX, PY = 700, 170
    CH = lambda a, b: [{"sel": "#chip%d" % i} for i in range(a, b + 1)]
    pulse = lambda idx: (lambda page, d: [page.evaluate("i => window.__pulse(i)", i) or page.wait_for_timeout(int(d * 1000 / len(idx)))
                                         for i in idx])

    def pop(*idx):
        def f(page, d):
            for k, i in enumerate(idx):
                page.evaluate("i => window.__chip(i)", i)
                if k < len(idx) - 1:
                    page.wait_for_timeout(int(d * 1000 * 0.22))
        return f

    def graf(page, d):
        page.evaluate("() => window.__panel('g')")
        page.wait_for_timeout(int(d * 500))
        page.evaluate("b => window.__beat(b)", {"cam": still(PX, PY, 16, 777, 780, 256), "camo": dict(max=1.9, pad=40, ms=int(d * 450)),
                                                 "ring": still(PX, PY, 16, 777, 780, 256), "co": "Live GPU telemetry"})

    def attu(page, d):
        page.evaluate("() => window.__panel('a')")

    def hosted(page, d):
        page.evaluate("() => window.__tag(3)")
        page.evaluate("() => window.__panel('')")

    return [dict(cam=CH(0, 2), camo=dict(max=1.5, pad=120), co="1 GPU", act=pop(0, 1, 2)),
            dict(cam=CH(0, 2), camo=dict(max=1.3, pad=140), act=pulse([0, 1, 2])),
            dict(cam=CH(3, 4), camo=dict(max=1.5, pad=120), act=pop(3, 4)),
            dict(cam=CH(5, 5), camo=dict(max=1.9, pad=300), act=pop(5), ring={"sel": "#chip5"}, ringpad=6),
            dict(cam=still(PX, PY, 16, 16, 385, 180), camo=dict(max=2.2, pad=60), ring=still(PX, PY, 16, 16, 385, 180), co="90.9% in Python", act=graf),
            dict(cam=still(PX, PY, 300, 372, 945, 34), camo=dict(max=2.0, pad=60), ring=still(PX, PY, 300, 372, 945, 34), co="1,024-dim vectors", act=attu),
            dict(cam=CH(3, 3), camo=dict(max=2.2, pad=300), ring={"sel": "#chip3"}, ringpad=6, act=hosted)]


def scene_F():
    def f1(page, d):
        page.evaluate("() => window.__title()")

    def cards(*idx):
        def f(page, d):
            for k, i in enumerate(idx):
                page.evaluate("i => window.__card(i)", i)
                if k < len(idx) - 1:
                    page.wait_for_timeout(int(d * 1000 * 0.45))
        return f

    return [dict(cam=None, camo=dict(to=1.0), act=f1),
            dict(cam={"sel": ".c", "nth": 0}, camo=dict(max=1.5, pad=240), act=cards(0)),
            dict(cam={"sel": ".c", "nth": 1}, camo=dict(max=1.5, pad=240), act=cards(1)),
            dict(cam=[{"sel": ".c", "nth": 2}, {"sel": ".c", "nth": 3}], camo=dict(max=1.4, pad=120), act=cards(2, 3)),
            dict(cam=None, camo=dict(to=1.0), act=lambda page, d: page.evaluate("() => window.__big()")),
            dict(cam=None, camo=dict(to=1.0), act=lambda page, d: page.evaluate("() => window.__end()"))]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slide-only", action="store_true")
    ap.add_argument("--scene", help="record just one scene (A-F), for iteration")
    ap.add_argument("--keep", help="copy each scene's mp4 into this directory")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        pptx = ROOT / "docs" / "architecture-deck.pptx"
        # ---- the process slide on its own, with the deck's own animation timing
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
            run(ffmpeg(), "-y", "-ss", "%.2f" % 0.25, "-i", next(vdir.glob("*.webm")), "-t", "%.2f" % (dur + 0.8), "-vf",
                "scale=%d:%d:flags=lanczos,fps=%d" % (W, H, FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
                "-preset", "veryfast", "-an", OUT / "process-slide-preview.mp4")
            print("process-slide-preview.mp4: %.1f s" % (dur + 0.8))
            if args.slide_only:
                return

        # ---- the demo
        script = beats()
        db = WORK / "demo.sqlite"
        shutil.copy(ROOT / "data" / "generated" / "service.sqlite", db)
        os.environ["ASOIA_DB"] = str(db)
        from app.analytics.queries import list_ros
        from app.state import db as dbm
        con = dbm.connect(str(db))
        n_active_safety = sum(1 for r in list_ros(con, "active", limit=500)["ros"] if r.get("safety"))
        n_ask = list_ros(con, "safety", limit=500)["count"]
        subs = {"{safety}": str(n_active_safety), "{ask_n}": str(n_ask)}

        def fill(t):
            for k, v in subs.items():
                t = t.replace(k, v)
            return t
        slide_driven, _ = slide_html(pptx, driven=True)
        (WORK / "slide_driven.html").write_text(slide_driven)
        (WORK / "comp.html").write_text(components_html())
        (WORK / "end.html").write_text(end_html())
        want = [args.scene] if args.scene else list("ABCDEF")
        ports = {"A": 7871, "C": 7872, "D": 7873}
        tabs = {"A": "dashboard", "C": "update", "D": "assistant"}
        procs = [start_ui(tabs[k], ports[k], db) for k in want if k in ports]
        try:
            cfg = {"A": ("http://127.0.0.1:7871", scene_A(n_active_safety), None),
                   "B": ((WORK / "slide_driven.html").as_uri(), scene_B(), None),
                   "C": ("http://127.0.0.1:7872", scene_C(), lambda page: (pick(page, 0, 3), pick(page, 1, 1))),
                   "D": ("http://127.0.0.1:7873", scene_D(), warm_ask),
                   "E": ((WORK / "comp.html").as_uri(), scene_E(), None),
                   "F": ((WORK / "end.html").as_uri(), scene_F(), None)}
            parts, total = [], 0.0
            for k in want:
                texts = [fill(t) for _, t in script[k]]
                files, durs = zip(*[voice(t) for t in texts])
                plan = cfg[k][1]
                assert len(plan) == len(texts), "scene %s: %d beats scripted, %d choreographed" % (k, len(texts), len(plan))
                tail = 2.2 if k == "F" else 0.0
                v = record(pw, k, cfg[k][0], texts, list(durs), plan, cfg[k][2], tail)
                wav = WORK / (k + ".wav"); join_wavs(list(files), wav)
                m = WORK / ("m_" + k + ".mp4"); mux(v, wav, sum(durs) + tail, m); parts.append(m)
                total += sum(durs) + tail
                print("scene %s: %d beats, %.1f s" % (k, len(texts), sum(durs) + tail))
                if args.keep:
                    Path(args.keep).mkdir(parents=True, exist_ok=True); shutil.copy(m, Path(args.keep) / ("scene_%s.mp4" % k))
        finally:
            for p in procs:
                stop(p)
        if not args.scene:
            final = OUT / "demo-preview.mp4"
            concat(parts, final)
            print("demo-preview.mp4: %.0f s total, %.1f MB" % (total, final.stat().st_size / 1e6))


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
