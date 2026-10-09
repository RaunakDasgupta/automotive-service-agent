#!/usr/bin/env python
"""Capture docs/screenshots/ by driving the running stack.

    .venv/bin/playwright install chromium          # once
    xvfb-run -a .venv/bin/python scripts/capture_screenshots.py

WHY A SCRIPT

The first twelve were taken by hand, and three of them were lying by the time
anyone looked again: Attu showed FloatVector(2048) and 1,857 entities when the
store held 1,690 at 1024, and the Prometheus shot was captioned "dcgm down
because a Mac has no GPU" from a box that has one. A by-hand screenshot records
the day it was taken. This records the stack as it is, and can be re-run.

THREE THINGS THIS FIGHTS, ALL MEASURED ON THIS BOX

1. Headless Chromium HANGS on the Gradio page - goto, evaluate and click all
   time out, and a bare goto+evaluate ran past 300s. Headed Chromium under
   xvfb-run does not. The other four UIs are fine headless; only Gradio is not.

2. Even headed, it hangs without --disable-dev-shm-usage. /dev/shm has 73G free
   on this box, so this is not exhaustion - the flag changes Chromium's shared
   memory strategy and that is what unblocks the renderer. Without it: evaluate
   never returns. With it: 0.0s.

3. Playwright's own click() times out on any UNSELECTED Gradio tab, and a
   JS .click() works exactly ONCE per page session - the first switch lands and
   every later one is ignored. So each Gradio shot makes exactly one tab switch.

4. The THIRD page in a browser session hangs, whichever tab it is. Two runs,
   different orders: 01,02,03 hung on 03; 01,02,04 hung on 04. It is not the
   tab - notebook 03's microphone was a red herring - it is the browser after
   two pages. So every shot gets its own BROWSER, launched and closed. That is
   ~6s of startup per shot and it is the difference between 2 and 12.
"""
from __future__ import annotations

import sys, os, pathlib, time, traceback

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh

OUT = pathlib.Path("docs/screenshots")
UI   = os.environ.get("ASOIA_UI_URL",   "http://127.0.0.1:7860")
PROM = os.environ.get("ASOIA_PROM_URL", "http://127.0.0.1:9090")
GRAF = os.environ.get("ASOIA_GRAF_URL", "http://127.0.0.1:3000")
ATTU = os.environ.get("ASOIA_ATTU_URL", "http://127.0.0.1:8101")
SQLW = os.environ.get("ASOIA_SQLW_URL", "http://127.0.0.1:8102")
VIEW = {"width": 1600, "height": 1100}
# --use-fake-*-for-media-stream: the Technician Update tab mounts
# gr.Audio(sources=["microphone", ...]). Under xvfb there is no audio device, and
# Chromium blocks acquiring one - the capture sat on that one tab for minutes and
# never returned. These give it a synthetic device and auto-accept the permission
# prompt, so the tab renders instead of waiting for hardware that is not there.
ARGS = ["--no-sandbox", "--disable-dev-shm-usage",
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required"]

CLICK_TAB = """(t)=>{const b=[...document.querySelectorAll('button[role=tab]')]
    .find(x=>x.textContent.trim()===t); if(!b) return 'not-found'; b.click(); return 'ok';}"""
IS_SEL = """(t)=>{const b=[...document.querySelectorAll('button[role=tab]')]
    .find(x=>x.textContent.trim()===t); return b?b.getAttribute('aria-selected'):'gone';}"""


def shot(page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    page.screenshot(path=str(p), type="jpeg", quality=88, timeout=60000)
    print("    saved %-34s %4d KB" % (name, p.stat().st_size // 1024), flush=True)


def gradio_tab(launch, tab: str, name: str, after=None) -> None:
    """One fresh page, one tab switch - see note 3 in the docstring."""
    browser = launch()
    pg = browser.new_page(viewport=VIEW)
    pg.set_default_timeout(30000)
    try:
        pg.goto(UI, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(8000)
        if tab != "Dashboard":
            r = pg.evaluate(CLICK_TAB, tab)
            pg.wait_for_timeout(4000)
            sel = pg.evaluate(IS_SEL, tab)
            if sel != "true":
                print("    WARNING %s: click=%s selected=%s" % (tab, r, sel), flush=True)
        if after:
            try:
                after(pg)
            except Exception as e:
                print("    %s: interaction skipped (%s)" % (tab, type(e).__name__), flush=True)
        shot(pg, name)
    finally:
        pg.close(); browser.close()


def simple(launch, url: str, name: str, wait: int = 6000, after=None) -> None:
    browser = launch()
    pg = browser.new_page(viewport=VIEW)
    pg.set_default_timeout(30000)
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        pg.wait_for_timeout(wait)
        if after:
            try:
                after(pg)
            except Exception as e:
                print("    %s: interaction skipped (%s)" % (name, type(e).__name__), flush=True)
        shot(pg, name)
    finally:
        pg.close(); browser.close()


# --------------------------------------------------------------- interactions
# Best-effort, and each is wrapped by the caller: a shot of the tab as it loads
# is worth more than no shot at all, so a selector that moves degrades to the
# un-interacted view rather than losing the capture.

FILL = """([txt]) => {
  const t = [...document.querySelectorAll('textarea')].find(e => e.offsetParent !== null);
  if (!t) return 'no-textarea';
  const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(t, txt);                       // native setter, or Svelte ignores it
  t.dispatchEvent(new Event('input', {bubbles: true}));
  t.dispatchEvent(new Event('change', {bubbles: true}));
  return 'ok';
}"""

CLICK_BTN = """([label]) => {
  const b = [...document.querySelectorAll('button')]
      .filter(e => e.offsetParent !== null)
      .find(e => e.textContent.trim().toLowerCase().includes(label.toLowerCase()));
  if (!b) return 'not-found';
  b.click();
  return 'ok';
}"""


def ask(question: str, settle_ms: int = 45000):
    """Type a question and submit it. settle_ms covers a real model round trip."""
    def _(pg):
        print("      filling: %s" % pg.evaluate(FILL, [question]), flush=True)
        pg.wait_for_timeout(800)
        r = pg.evaluate(CLICK_BTN, ["ask"])
        if r != "ok":
            r = pg.evaluate(CLICK_BTN, ["send"])
        if r != "ok":
            r = pg.evaluate(CLICK_BTN, ["submit"])
        print("      submit: %s, waiting %ds for the model" % (r, settle_ms // 1000), flush=True)
        pg.wait_for_timeout(settle_ms)
    return _


def press(label: str, settle_ms: int = 20000):
    def _(pg):
        r = pg.evaluate(CLICK_BTN, [label])
        print("      click %r: %s" % (label, r), flush=True)
        pg.wait_for_timeout(settle_ms)
    return _


# --------------------------------------------------------------------- the set

def main() -> int:
    from playwright.sync_api import sync_playwright

    shots = []
    with sync_playwright() as p:
        def b():
            return p.chromium.launch(headless=False, args=ARGS)
        plan = [
            ("01-app-dashboard.jpg",         lambda: gradio_tab(b, "Dashboard", "01-app-dashboard.jpg")),
            ("02-app-repair-order.jpg",      lambda: gradio_tab(b, "Repair Order", "02-app-repair-order.jpg",
                                                                press("refresh list", 8000))),
            ("03-app-technician-update.jpg", lambda: gradio_tab(b, "Technician Update", "03-app-technician-update.jpg")),
            ("04-app-shift-handover.jpg",    lambda: gradio_tab(b, "Shift Handover", "04-app-shift-handover.jpg",
                                                                press("generate", 30000))),
            ("05-app-manager-assistant.jpg", lambda: gradio_tab(b, "Manager Assistant", "05-app-manager-assistant.jpg",
                                                                ask("Which vehicles cannot be released on safety grounds?"))),
            ("06-app-data-and-retrieval.jpg", lambda: gradio_tab(b, "Data & Retrieval", "06-app-data-and-retrieval.jpg")),
            ("07-prometheus-targets.jpg",    lambda: simple(b, PROM + "/targets", "07-prometheus-targets.jpg", 8000)),
            ("08-prometheus-tool-calls.jpg", lambda: simple(b, PROM + "/graph?g0.expr=asoia_tool_calls_total&g0.tab=1&g0.range_input=1h",
                                                            "08-prometheus-tool-calls.jpg", 9000)),
            ("09-grafana-dashboard.jpg",     lambda: simple(b, GRAF + "/d/asoia/?kiosk&refresh=10s", "09-grafana-dashboard.jpg", 14000)),
            ("10-attu-collections.jpg",      lambda: simple(b, ATTU + "/#/databases/default/collections", "10-attu-collections.jpg", 11000)),
            ("11-attu-schema-1024d.jpg",     lambda: simple(b, ATTU + "/#/databases/default/collections/updates/schema", "11-attu-schema-1024d.jpg", 11000)),
            ("12-sqlite-web.jpg",            lambda: simple(b, SQLW + "/", "12-sqlite-web.jpg", 6000)),
        ]
        only = None
        if "--only" in sys.argv:
            only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        for name, fn in plan:
            num = name.split("-")[0]
            if only and num not in only:
                continue
            print("  %s" % name, flush=True)
            t0 = time.time()
            try:
                fn()
                shots.append((name, "ok", time.time() - t0))
            except Exception as e:
                print("    FAILED %s: %s" % (type(e).__name__, str(e)[:90]), flush=True)
                traceback.print_exc(limit=1)
                shots.append((name, "FAILED", time.time() - t0))

    ok = sum(1 for _, s, _ in shots if s == "ok")
    print("\n  %d/%d captured" % (ok, len(shots)), flush=True)
    for n, s, el in shots:
        print("    %-34s %-7s %5.1fs" % (n, s, el), flush=True)
    return 0 if ok == len(shots) else 1


if __name__ == "__main__":
    raise SystemExit(main())
