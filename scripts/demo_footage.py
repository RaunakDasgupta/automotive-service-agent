#!/usr/bin/env python
"""Capture the live application ONCE, as raw footage, so the demo video never needs a GPU box again.

    python scripts/demo_footage.py --box <ssh-alias>            # all four live scenes, on a running Brev box
    python scripts/demo_footage.py --box <ssh-alias> --scene C  # one scene
    python scripts/demo_footage.py --local --scene AD           # against UIs already running on this machine
    python scripts/demo_footage.py --check                      # is the footage still current? (no box, no network)
    python scripts/demo_footage.py --restamp                    # the app changed but nothing on screen did: accept it

Run it with the throwaway venv in docs/demo/README.md (playwright, websockets, imageio-ffmpeg, nvidia-riva-client).

WHAT IS RECORDED

docs/demo/footage/raw/<scene>.mp4 is the page exactly as the app draws it: 3840x2160 (a 2x screenshot loop, so a
camera zoom later is still sharp), with NO camera move, ring, caption, callout or cursor in it. Everything that is
added to it is added by scripts/make_demo_preview.py, offline.

docs/demo/footage/timeline.json says what is where and when: for every step of a scene, its time window, the
clicks, the moment its result appeared, and the on-screen rectangle of every element the camera may aim at (the
TARGETS below). Editing the script, the pacing, the zoom, the callouts or the cursor needs only these two files.

WHEN A BOX IS NEEDED AGAIN

Only when what the app puts on screen changes. Each scene is stamped with a fingerprint of the app's code, the
Grafana dashboard definition and the inputs typed into it (CAPTURE); `--check` compares it with the tree, and
make_demo_preview.py prints the same verdict. A changed fingerprint is a prompt to look, not proof: if the change
does not touch the screen, `--restamp` accepts the footage.
"""
from __future__ import annotations

import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time, urllib.request, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT)]
FOOT = ROOT / "docs" / "demo" / "footage"
W, H, K, FPS = 1920, 1080, 2, 30            # the page is laid out at W x H and captured K times larger
TTS_CACHE = Path.home() / ".cache" / "asoia-demo-tts"
DEBUG_PORT = 9333


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError("%s failed:\n%s" % (cmd[0], r.stderr[-600:]))
    return r


# ------------------------------------------------------------------ what is typed in, and what the camera may aim at
CAPTURE = {
    "dictation": "Grinding under braking. Rotor thickness measured twenty one point nine millimetres, minimum twenty three.",
    "ro_rule": "first repair order in PARTS_HOLD with no safety flag yet", "technician": 1,
    "q1": "Which vehicles cannot be released on safety grounds?",
    "q2": "Has anyone seen a whistling noise on a Passat?",
    "type_ms": 80, "viewport": [W, H], "scale": K,
    "page_height": {"A": H, "C": 3000, "D": H, "G": H},     # the Technician Update page is ~2.8k px tall: all of it is captured
}
_P = lambda t: {"text": t, "up": ".react-grid-item"}
_CARD = "()=>[...document.querySelectorAll('textarea')].find(t=>t.value.includes('SAFETY_RELATED'))"
TARGETS = {
    "A": {"ROW": {"text": "below minimum"},
          "TILE": {"text": "Safety - do not release", "up": 'div[style*="border-radius:10px"]'}},
    "C": {"VOICE": [{"text": "Voice or free text"}, {"text": "Record or upload", "grow": [0, 0, 900, 150]}],
          "TRANS": [{"text": "Transcribe", "up": "button"}, {"text": "Transcript / free-text update", "grow": [0, 0, 1700, 110]}],
          "EXTR": [{"text": "Extract and apply", "up": "button"}, {"text": "Extracted 3 C's structure", "grow": [0, 0, 900, 230]}],
          "MEAS": {"text": "safety_related", "grow": [330, 240, 330, 24]},
          "CARD120": {"fn": _CARD, "top": 120}, "CARD280": {"fn": _CARD, "top": 280}},
    "D": {"Q": {"fn": "()=>[...document.querySelectorAll('textarea')].find(t=>t.offsetParent)"},
          "ANS": {"text": "repair orders cannot be released"},
          "LAST": {"fn": "()=>[...document.querySelectorAll('*')].filter(e=>e.children.length==0&&e.textContent.includes('whistling')).pop()",
                   "grow": [30, 40, 900, 230]}},
    "G": {"GPU": _P("GPU utilisation and framebuffer"), "POWER": _P("GPU power, temperature and clock")},
}

# finds an element by text / selector / function and returns its rectangle in page pixels (the same descriptors the
# old in-page camera used); also keeps the page from scrolling, which would move everything under the capture
FIND_JS = r"""
(() => {
  if (window.__find) return;
  document.documentElement.style.overflow = 'hidden'; document.body.style.margin = '0';
  addEventListener('scroll', () => scrollTo(0, 0), true);
  window.__find = d => {
    if (Array.isArray(d)) { const rs = d.map(window.__find).filter(Boolean); if (!rs.length) return null;
      const x0 = Math.min(...rs.map(r => r.x)), y0 = Math.min(...rs.map(r => r.y)), x1 = Math.max(...rs.map(r => r.x + r.w)), y1 = Math.max(...rs.map(r => r.y + r.h));
      return {x: x0, y: y0, w: x1 - x0, h: y1 - y0}; }
    let el = null;
    if (d.fn) el = (new Function('return (' + d.fn + ')'))()();
    else if (d.sel) el = document.querySelectorAll(d.sel)[d.nth || 0];
    else if (d.text) { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
      while ((n = w.nextNode())) if (n.textContent.includes(d.text)) { const e = n.parentElement, r = e.getBoundingClientRect(); if (r.width > 0 && r.height > 0) { el = e; break; } } }
    if (!el) return null;
    if (d.up) el = el.closest(d.up) || el;
    const r = el.getBoundingClientRect(), o = {x: r.left, y: r.top, w: r.width, h: r.height};
    if (d.top) o.h = Math.min(o.h, d.top);
    if (d.grow) { const g = d.grow; o.x -= g[0]; o.y -= g[1]; o.w += g[0] + g[2]; o.h += g[1] + g[3]; }
    return o;
  };
  window.__rects = ds => Object.fromEntries(Object.entries(ds).map(([k, d]) => { try { return [k, window.__find(d)]; } catch (e) { return [k, null]; } }));
})();
"""


# ------------------------------------------------------------------ fingerprint: has what is on screen changed?
def fingerprint() -> dict:
    """Hashes of everything that decides what the recorded pages show. Read the verdict as a prompt to look."""
    def sha(paths):
        h = hashlib.sha1()
        for p in sorted(paths):
            h.update(str(p.relative_to(ROOT)).encode()); h.update(p.read_bytes())
        return h.hexdigest()[:12]
    app = [p for p in (ROOT / "app").rglob("*.py")]
    grafana = [p for p in (ROOT / "configs" / "grafana").rglob("*") if p.is_file()]
    return {"app": sha(app), "grafana": sha(grafana),
            "inputs": hashlib.sha1(json.dumps([CAPTURE, TARGETS], sort_keys=True).encode()).hexdigest()[:12]}


def load_timeline() -> dict:
    return json.loads((FOOT / "timeline.json").read_text())


def check(scenes: str = "ACDG") -> list[str]:
    """Scenes whose footage no longer matches the tree (empty = nothing needs recording)."""
    try:
        tl = load_timeline()
    except FileNotFoundError:
        return list(scenes)
    now = fingerprint()
    return [s for s in scenes if tl["scenes"].get(s, {}).get("fingerprint") != now]


# ------------------------------------------------------------------ the box
PORTS = [7871, 7872, 7873, 3000, 8101, 8080]
BOX_UP = r"""
cd /home/ubuntu/automotive-service-agent || exit 1
for f in /tmp/demo_ui_*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
sleep 1; rm -f /home/ubuntu/demo.sqlite*
python3 -c "import sqlite3; d=sqlite3.connect('/home/ubuntu/demo.sqlite'); sqlite3.connect('data/generated/service.sqlite').backup(d)"
set -a; . ./.env; set +a
start(){ PORT=$1 ASOIA_UI_TAB=$2 ASOIA_DB=/home/ubuntu/demo.sqlite ASOIA_METRICS=0 SHARE=0 ASOIA_LOG_ANSWERS=0 \
  setsid nohup .venv/bin/python -m app.ui.gradio_app > /tmp/demo_ui_$1.log 2>&1 & echo $! > /tmp/demo_ui_$1.pid; }
start 7871 dashboard; start 7872 update; start 7873 assistant
for p in 7871 7872 7873; do for i in $(seq 1 60); do curl -s -o /dev/null localhost:$p && break; sleep 1; done; done
"""
BOX_DOWN = 'for f in /tmp/demo_ui_*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done; true'
TRAFFIC = r"""
Q=("Which vehicles cannot be released on safety grounds?" "Give me the afternoon handover, worst first." "Are any parts holding up more than one job at once?" "Which jobs will miss their promised time?" "Go ahead and order the parts for RO-26-08165" "Has anyone seen a whistling noise on a Passat?" "Any reports of brake judder when stopping?" "Customers complaining about a knocking noise from the front suspension" "Which repair orders are blocked on parts?")
end=$((SECONDS+%d))
while [ $SECONDS -lt $end ]; do
  for q in "${Q[@]}"; do curl -s -m 60 -X POST localhost:8080/ask -H 'content-type: application/json' -d "{\"question\":\"$q\"}" >/dev/null & done
  wait; sleep 3
done
"""


def ssh(alias: str, script: str, timeout=900) -> str:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", alias, "bash -s"], input=script, text=True, capture_output=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError("ssh %s failed:\n%s" % (alias, r.stderr[-500:]))
    return r.stdout


# The dataset is generated relative to the date, so repair order numbers differ from box to box: the one the technician
# updates is picked from the data, by the rule in CAPTURE["ro_rule"].
PICK_RO = """
from app.state import db as dbm
from app.analytics.queries import _snapshot
con = dbm.connect()
for n in sorted(dbm.all_ro_numbers(con)):
    ro, snap = _snapshot(con, n)
    if snap and snap.state.value == "PARTS_HOLD" and not snap.safety_flags and snap.pending_ops:
        print(n); break
"""


def pick_ro(alias: str | None) -> str:
    if alias:
        out = ssh(alias, "cd /home/ubuntu/automotive-service-agent && set -a && . ./.env && set +a && "
                         "ASOIA_DB=/home/ubuntu/demo.sqlite .venv/bin/python - <<'EOF'\n" + PICK_RO + "EOF\n")
    else:
        out = subprocess.run([str(ROOT / ".venv" / "bin" / "python"), "-c", PICK_RO], capture_output=True, text=True, cwd=ROOT).stdout
    if not out.strip():
        raise RuntimeError("no repair order matches: " + CAPTURE["ro_rule"])
    return out.strip().splitlines()[-1]


def forwards(alias: str):
    """Forward whichever of PORTS is not already reachable locally. Returns the ssh processes."""
    import socket
    procs = []
    for p in PORTS:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", p)) == 0:
                continue
        procs.append(subprocess.Popen(["ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-L", "%d:127.0.0.1:%d" % (p, p), alias],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(3)
    return procs


def dictation() -> Path:
    """The technician's spoken update, voiced once (16 kHz mono, as a microphone would give)."""
    import _env  # noqa: F401  - .env like stack.sh; the key is never printed
    text = CAPTURE["dictation"]
    out = TTS_CACHE / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".wav")
    if not out.exists():
        import riva.client as rc
        auth = rc.Auth(uri="grpc.nvcf.nvidia.com:443", use_ssl=True, metadata_args=[
            ["function-id", "877104f7-e885-42b9-8de8-f6e4c6303969"],
            ["authorization", "Bearer " + os.environ["NVIDIA_API_KEY"]]])
        r = rc.SpeechSynthesisService(auth).synthesize(text, voice_name="Magpie-Multilingual.EN-US.Jason", language_code="en-US",
                                                        sample_rate_hz=16000, encoding=rc.AudioEncoding.LINEAR_PCM)
        TTS_CACHE.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(r.audio)
    return out


def live_counts(pw, ask_url="http://127.0.0.1:8080/ask", dash="http://127.0.0.1:7871", api=True):
    """The numbers the narration quotes, read from the running app rather than written into the script."""
    n_ask = None
    if api:
        req = urllib.request.Request(ask_url, json.dumps({"question": CAPTURE["q1"]}).encode(), {"content-type": "application/json"})
        ans = json.loads(urllib.request.urlopen(req, timeout=60).read())["answer"]
        n_ask = int(re.search(r"(\d+) repair orders?", ans).group(1))
    br = pw.chromium.launch(); pg = br.new_page(viewport={"width": W, "height": H})
    pg.goto(dash, wait_until="load", timeout=90000)
    pg.get_by_text("Safety - do not release").first.wait_for(timeout=90000)
    tiles = pg.evaluate("""() => ['Safety - do not release', 'Open repair orders'].map(t => document.evaluate("//*[text()='" + t + "']", document, null, 9, null)
        .singleNodeValue.closest('div[style*="border-radius:10px"]').innerText.split('\\n')[0])""")
    br.close()
    return int(tiles[0]), (n_ask if n_ask is not None else int(tiles[0])), int(tiles[1])


# ------------------------------------------------------------------ the capture itself
class Grabber:
    """Takes a 2x screenshot of the page in a loop over a SECOND DevTools connection, so the script driving the page is
    never held up by it. The page changes in steps (a keystroke, a result), so ~12 frames a second loses nothing."""

    def __init__(self, port: int, outdir: Path, page_h: int = H):
        self.port, self.dir, self.stamps, self.page_h = port, outdir, [], page_h
        self.t0 = None
        self.first = threading.Event()
        self.stop = threading.Event()
        self.err = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _page_ws(self):
        for _ in range(50):
            tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port, timeout=5).read())
            pages = [t for t in tabs if t["type"] == "page" and not t["url"].startswith("about:")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
            time.sleep(0.2)
        raise RuntimeError("no page to capture")

    def _loop(self):
        try:
            from websockets.sync.client import connect
            with connect(self._page_ws(), max_size=None, open_timeout=20) as ws:
                params = {"format": "jpeg", "quality": 90, "optimizeForSpeed": True, "captureBeyondViewport": self.page_h > H,
                          "clip": {"x": 0, "y": 0, "width": W, "height": self.page_h, "scale": K}}
                n = 0
                while not self.stop.is_set():
                    n += 1
                    a = time.perf_counter()
                    ws.send(json.dumps({"id": n, "method": "Page.captureScreenshot", "params": params}))
                    while True:
                        msg = json.loads(ws.recv())
                        if msg.get("id") == n:
                            break
                    b = time.perf_counter()
                    if "result" not in msg:
                        raise RuntimeError(str(msg)[:200])
                    (self.dir / ("f%06d.jpg" % n)).write_bytes(base64.b64decode(msg["result"]["data"]))
                    if self.t0 is None:
                        self.t0 = (a + b) / 2
                        self.first.set()
                    self.stamps.append((a + b) / 2 - self.t0)
        except Exception as e:                       # surfaced by Take.finish
            self.err = e
            self.first.set()


class Take:
    """One scene's capture. Steps are run in order; each one's time window, clicks and result moment are written to
    the timeline together with the on-screen rectangle of every target at its start and its end."""

    def __init__(self, pw, scene: str, url: str, ready=None, prep=None):
        self.scene, self.tmp, self.ph, self.tallest = scene, Path(tempfile.mkdtemp(prefix="asoia-raw-")), CAPTURE["page_height"][scene], 0
        self.browser = pw.chromium.launch(args=["--remote-debugging-port=%d" % DEBUG_PORT])
        ctx = self.browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=K)
        self.page = ctx.new_page()
        self.page.goto(url, wait_until="load", timeout=90000)
        if ready:
            ready(self.page)
        self.page.wait_for_timeout(1500)
        self.page.add_script_tag(content=FIND_JS)
        if prep:
            prep(self.page)                           # done before the first frame: dropdowns are not part of the story
        self.page.wait_for_timeout(800)
        self.grab = Grabber(DEBUG_PORT, self.tmp, self.ph)
        self.grab.thread.start()
        self.grab.first.wait(60)
        if self.grab.err:
            raise self.grab.err
        self.steps, self.cur = [], None

    def now(self) -> float:
        return time.perf_counter() - self.grab.t0

    def rects(self) -> dict:
        r = self.page.evaluate("ds => window.__rects(ds)", TARGETS[self.scene])
        self.tallest = max(self.tallest, self.page.evaluate("() => document.documentElement.scrollHeight"))
        for k, v in r.items():
            if v and v["y"] + v["h"] > self.ph + 2:
                print("  WARNING: %s/%s is below the %d px that is captured; raise page_height in CAPTURE" % (self.scene, k, self.ph))
        return r

    def click(self, loc, show: bool = True):
        """Click an element and note where and when, so a cursor can be drawn there later if the shot needs one."""
        bb = loc.first.bounding_box()
        if bb:
            self.cur["clicks"].append({"t": round(self.now(), 3), "x": round(bb["x"] + bb["width"] / 2, 1),
                                       "y": round(bb["y"] + bb["height"] / 2, 1), "show": show})
        loc.first.evaluate("e => e.click()")

    def mark(self, name: str):
        self.cur["marks"][name] = round(self.now(), 3)

    def until(self, js: str, timeout_ms: int = 25000, stable: float = 0.0):
        """Wait for a page condition and note the moment it became true as the step's `done`; with `stable`, then wait
        until the page text stops changing for that long (an answer that streams in)."""
        self.page.wait_for_function(js, timeout=timeout_ms)
        self.mark("done")
        last, since = -1, time.perf_counter()
        while stable and time.perf_counter() - since < stable and time.perf_counter() - since < 30:
            n = self.page.evaluate("() => document.body.innerText.length")
            if n != last:
                last, since = n, time.perf_counter()
            self.page.wait_for_timeout(150)

    def step(self, sid: str, act=None, settle: float = 0.8):
        st = {"id": sid, "t0": round(self.now(), 3), "clicks": [], "marks": {}, "rects0": self.rects()}
        self.cur = st
        if act:
            act(self)
        self.page.wait_for_timeout(int(settle * 1000))
        st["t1"] = round(self.now(), 3)
        st["rects1"] = self.rects()
        self.steps.append(st)
        print("  %s: %.1f s%s" % (sid, st["t1"] - st["t0"], "  (result at +%.1f s)" % (st["marks"]["done"] - st["t0"]) if "done" in st["marks"] else ""))

    def finish(self) -> dict:
        self.grab.stop.set(); self.grab.thread.join(30)
        if self.grab.err:
            raise self.grab.err
        self.browser.close()
        stamps, n = self.grab.stamps, len(self.grab.stamps)
        end = self.steps[-1]["t1"] + 0.3
        lst = self.tmp / "list.txt"
        with open(lst, "w") as f:
            for i in range(n):
                nxt = stamps[i + 1] if i + 1 < n else max(end, stamps[i] + 0.1)
                f.write("file 'f%06d.jpg'\nduration %.4f\n" % (i + 1, max(0.001, nxt - stamps[i])))
            f.write("file 'f%06d.jpg'\n" % n)
        out = FOOT / "raw" / (self.scene + ".mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        run(ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf", "fps=%d,format=yuv420p" % FPS, "-c:v", "libx264",
            "-crf", "20", "-preset", "slow", "-movflags", "+faststart", out)
        shutil.rmtree(self.tmp, ignore_errors=True)
        print("  %s: %d screenshots (%.1f/s), %.1f MB, page %d px tall (captured %d)" % (self.scene, n, n / max(end, 0.1), out.stat().st_size / 1e6,
                                                                                         self.tallest, self.ph))
        if self.tallest > self.ph + 2:
            print("  WARNING: the page grew taller than what was captured; raise page_height[%s] in CAPTURE and capture again" % self.scene)
        return {"file": "raw/%s.mp4" % self.scene, "page": [W, self.ph], "duration": round(end, 3), "fingerprint": fingerprint(), "steps": self.steps}


# ------------------------------------------------------------------ one capture per scene
def cap_A(pw, url):
    t = Take(pw, "A", url, ready=lambda p: p.get_by_text("Open repair orders").first.wait_for(timeout=120000))
    t.step("A", settle=3.0)
    return t.finish()


def cap_C(pw, url, wav: Path, ro: str):
    def choose(page, nth, text=None, idx=0):
        page.locator("input[role=listbox], .wrap input").nth(nth).click()
        lis = page.locator("li[role=option], ul[role=listbox] li")
        lis.first.wait_for(state="visible", timeout=20000)
        if text:
            idx = next(i for i, x in enumerate(lis.all_inner_texts()) if text in x)
        lis.nth(idx).click()
        page.wait_for_timeout(500)

    def prep(page):
        choose(page, 0, text=ro); choose(page, 1, idx=CAPTURE["technician"])
        page.get_by_text("Parts Hold").first.wait_for(timeout=15000)

    t = Take(pw, "C", url, ready=lambda p: p.get_by_label("Measurement").wait_for(timeout=120000), prep=prep)
    ROT = "() => [...document.querySelectorAll('textarea')].some(t => t.value.toLowerCase().includes('rotor'))"
    SAF = "() => [...document.querySelectorAll('textarea')].some(t => t.value.includes('SAFETY_RELATED'))"

    def c1(s):
        s.page.wait_for_timeout(500)
        s.click(s.page.get_by_label("Upload file"), show=False)
        s.page.wait_for_timeout(500)
        s.page.locator("input[type=file]").first.set_input_files(str(wav))
        s.page.wait_for_timeout(1800)                # the waveform appears

    def c2(s):
        s.page.wait_for_timeout(600)
        s.click(s.page.get_by_role("button", name="Transcribe"))
        s.until(ROT)

    def c3(s):
        s.page.wait_for_timeout(600)
        s.click(s.page.get_by_role("button", name="Extract and apply"))
        s.until(SAF)

    t.step("C1", c1, settle=0.8)
    t.step("C2", c2, settle=1.0)
    t.step("C3", c3, settle=1.2)
    t.step("C4", settle=2.0)
    return t.finish()


def answer_to_top(s):
    """The answer to the structured question, then the chat scrolled to where that answer starts."""
    s.until("() => document.body.innerText.includes('computed from the records')", 30000)
    s.page.wait_for_timeout(900)                     # the chat re-scrolls to the bottom while the message is still being laid out
    s.page.evaluate("() => { const e = document.querySelector('[role=log]'); if (e) e.scrollTop = 0; }")


def cap_D(pw, url):
    t = Take(pw, "D", url, ready=lambda p: p.get_by_text("Try these").first.wait_for(timeout=120000))

    def ask(q, to_bottom=False):
        def f(s):
            if to_bottom:                                  # the chat follows a new answer only if it is already at the bottom
                s.page.evaluate("() => { const e = document.querySelector('[role=log]'); if (e) e.scrollTo({top: e.scrollHeight, behavior: 'smooth'}); }")
                s.page.wait_for_timeout(900)
            box = s.page.locator("textarea").first
            box.evaluate("e => e.focus()")
            s.page.keyboard.press("Meta+A"); s.page.keyboard.press("Delete")
            s.page.keyboard.type(q, delay=CAPTURE["type_ms"])
            s.page.wait_for_timeout(350)
            s.click(s.page.get_by_role("button", name="Ask", exact=True))
        return f

    t.step("D1", lambda s: s.page.locator("textarea").first.evaluate("e => e.focus()"), settle=1.4)
    t.step("D2", ask(CAPTURE["q1"]), settle=0.2)
    t.step("D3", answer_to_top, settle=1.6)
    t.step("D5", ask(CAPTURE["q2"], to_bottom=True), settle=0.2)
    t.step("D6", lambda s: s.until("() => (document.body.innerText.match(/whistling/g) || []).length > 1", 60000, stable=1.5), settle=1.2)
    return t.finish()


def cap_G(pw, url):
    def ready(p):
        p.get_by_text("GPU utilisation and framebuffer").first.wait_for(timeout=120000)
        p.wait_for_timeout(4500)
    t = Take(pw, "G", url, ready=ready)
    t.step("G1", settle=7.0)
    return t.finish()


def main():
    ap = argparse.ArgumentParser(description="Capture the live app as raw footage.")
    ap.add_argument("--box", help="ssh alias of a running Brev instance (docs/BREV_RUNBOOK.md)")
    ap.add_argument("--local", action="store_true", help="use UIs already running on this machine (A on 7871, C 7872, D 7873)")
    ap.add_argument("--scene", default="ACDG", help="which scenes to capture, e.g. C or AD")
    ap.add_argument("--no-traffic", action="store_true", help="with --box: skip the warm-up traffic that fills Grafana")
    ap.add_argument("--check", action="store_true", help="say whether the footage still matches the app; touches nothing")
    ap.add_argument("--restamp", action="store_true", help="stamp the footage as current (the app changed, the screen did not)")
    a = ap.parse_args()

    if a.check or a.restamp:
        if a.restamp:
            tl = load_timeline()
            for s in tl["scenes"].values():
                s["fingerprint"] = fingerprint()
            (FOOT / "timeline.json").write_text(json.dumps(tl, indent=1))
        stale = check()
        print("footage is current: no box needed." if not stale else
              "footage is STALE for scenes %s - the app code, Grafana dashboard or capture inputs changed since it was recorded.\n"
              "  If the change does not alter what is on screen: python scripts/demo_footage.py --restamp\n"
              "  Otherwise re-capture on a box:                   python scripts/demo_footage.py --box <alias> --scene %s" % (stale, "".join(stale)))
        sys.exit(1 if stale else 0)

    if not (a.box or a.local):
        ap.error("--box <alias> or --local is needed to capture")
    from playwright.sync_api import sync_playwright
    FOOT.mkdir(parents=True, exist_ok=True)
    tl = load_timeline() if (FOOT / "timeline.json").exists() else {"scenes": {}, "subs": {}}
    fwd = []
    with sync_playwright() as pw:
        try:
            if a.box:
                print("box: starting the recording UIs on a copy of the database")
                ssh(a.box, BOX_UP)
                fwd = forwards(a.box)
                if "G" in a.scene and not a.no_traffic:
                    print("box: 100 s of mixed questions through /ask so Grafana has real data")
                    ssh(a.box, TRAFFIC % 100)
            n_safety, n_ask, n_open = live_counts(pw, api=bool(a.box))
            tl["subs"] = {"{safety}": str(n_safety), "{ask_n}": str(n_ask), "{open}": str(n_open)}
            print("live numbers:", tl["subs"])
            graf = "http://127.0.0.1:3000/d/asoia/service-operations-agent?kiosk&from=now-30m&to=now&refresh=10s"
            jobs = {"A": lambda: cap_A(pw, "http://127.0.0.1:7871"), "C": lambda: cap_C(pw, "http://127.0.0.1:7872", dictation(), pick_ro(a.box)),
                    "D": lambda: cap_D(pw, "http://127.0.0.1:7873"), "G": lambda: cap_G(pw, graf)}
            for s in a.scene:
                print("capturing scene %s" % s)
                tl["scenes"][s] = jobs[s]()
                tl["size"] = [W * K, H * K]
                tl["fps"] = FPS
                (FOOT / "timeline.json").write_text(json.dumps(tl, indent=1))
        finally:
            for p in fwd:
                p.terminate()
            if a.box:
                try:
                    ssh(a.box, BOX_DOWN, timeout=60)
                except Exception:
                    pass
    print("done. footage:", ", ".join(sorted(tl["scenes"])), "| now: python scripts/make_demo_preview.py")


if __name__ == "__main__":
    main()
