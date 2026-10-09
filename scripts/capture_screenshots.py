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

WHAT THIS FIGHTS, ALL MEASURED ON THIS BOX

1. Headless Chromium HANGS on the Gradio page - goto, evaluate and click all
   time out, and a bare goto+evaluate ran past 300s. Headed Chromium under
   xvfb-run does not. The other four UIs are fine headless; only Gradio is not.

2. Even headed, it hangs without --disable-dev-shm-usage. /dev/shm has 73G free
   on this box, so this is not exhaustion - the flag changes Chromium's shared
   memory strategy and that is what unblocks the renderer. Without it: evaluate
   never returns. With it: 0.0s.

3. SWITCHING A GRADIO TAB puts the frontend into a Svelte effect loop, and that
   is what made four frames un-capturable for two days. Gradio 6.15.1 mounts
   only the selected tab's content; mounting one of these tabs throws
   `effect_update_depth_exceeded` about fifteen times a second and does not
   stop - a renderer pinned at 102% of a core, an evaluate that never answers
   (its own timeout does not fire either), and Page.screenshot timing out at
   60s. The earlier note here blamed "the third page in a browser session" and
   the microphone; both were wrong. Toy reproductions of the same components -
   the dataframes, the 200-item filterable dropdowns, the KPI flex strip, the
   whole Repair Order tab - all stay clean, so the trigger is specific to the
   full page and is not fixable from here.

   So NOTHING HERE SWITCHES TABS. Each Gradio frame starts a second copy of the
   app on CAP_PORT with ASOIA_UI_TAB set, which opens straight on that tab with
   the full tab bar intact: zero page errors, and the screenshot returns. The
   UI on :7860 is left running and untouched.

4. Each shot runs in its own child process and the parent kills the process
   group, on success as much as on timeout. Nothing calls browser.close():
   a wedged renderer never answers one and the call blocks with no timeout,
   which is how one failed frame used to take the rest of the run with it.
"""
from __future__ import annotations

import os, pathlib, re, signal, subprocess, sys, time, urllib.request
from contextlib import contextmanager

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh

OUT = pathlib.Path("docs/screenshots")
PROM = os.environ.get("ASOIA_PROM_URL", "http://127.0.0.1:9090")
GRAF = os.environ.get("ASOIA_GRAF_URL", "http://127.0.0.1:3000")
ATTU = os.environ.get("ASOIA_ATTU_URL", "http://127.0.0.1:8101")
SQLW = os.environ.get("ASOIA_SQLW_URL", "http://127.0.0.1:8102")
VIEW = {"width": 1600, "height": 1100}
# --use-fake-*-for-media-stream: the Technician Update tab mounts
# gr.Audio(sources=["microphone", ...]) and there is no audio device under xvfb.
# These hand it a synthetic one and auto-accept the permission prompt, so the
# frame shows the recorder rather than a permission dialog. They were once
# credited with fixing the hang on that tab; they did not - see note 3.
ARGS = ["--no-sandbox", "--disable-dev-shm-usage",
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required"]

# The port the capture copy of the app listens on. Not 7860: the running UI
# stays up, and a frame should never depend on having taken it down.
CAP_PORT = int(os.environ.get("ASOIA_CAPTURE_UI_PORT", "7869"))
TAB_SELECTED = """()=>[...document.querySelectorAll('button[role=tab]')]
    .filter(b=>b.getAttribute('aria-selected')==='true')
    .map(b=>b.textContent.trim()).join(',')"""


PROBE = [""]          # what the frame must visibly say; set by one_shot()


def shot(page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    try:
        # Park the pointer in the corner first. Left where it starts, it sits
        # over Prometheus's graph and the hover tooltip covers the expression
        # the frame exists to show.
        page.mouse.move(VIEW["width"] - 4, VIEW["height"] - 4)
        page.wait_for_timeout(500)
    except Exception:
        pass
    page.screenshot(path=str(p), type="jpeg", quality=88, timeout=60000)
    print("    saved %-34s %4d KB" % (name, p.stat().st_size // 1024), flush=True)
    if not PROBE[0]:
        return
    # After the save, never before: a page whose renderer is looping cannot
    # answer an evaluate, and a frame on disk beats a frame lost to a probe.
    try:
        txt = page.evaluate("document.body.innerText")
        found = PROBE[0].lower() in (txt or "").lower()
        print("    probe %-24r %s" % (PROBE[0], "found" if found else "MISSING"), flush=True)
    except Exception as e:
        print("    probe %-24r unavailable (%s)" % (PROBE[0], type(e).__name__), flush=True)


def keep(*_ignored) -> None:
    """Deliberately NOT page.close() / browser.close() - see note 4.

    A renderer stuck in the effect loop never answers a close and the call
    blocks with no timeout, which is what made whole runs look hung. The shot is
    on disk by the time this runs, so the process simply exits and the parent
    kills the process group, Chromium with it.
    """
    return None


@contextmanager
def ui_on_tab(tab_id: str):
    """A second copy of the app, opened on one tab, on CAP_PORT.

    This is how a Gradio tab gets photographed at all - see note 3. It is the
    same code and the same data as the UI on :7860, started with ASOIA_UI_TAB so
    the tab is already mounted and nothing has to be clicked. Metrics are off in
    this copy: the exporter Prometheus scrapes belongs to the API, and a second
    one on the same port would only fail to bind.
    """
    env = dict(os.environ, ASOIA_UI_TAB=tab_id, PORT=str(CAP_PORT),
               ASOIA_METRICS="0", SHARE="0")
    proc = subprocess.Popen([sys.executable, "-m", "app.ui.gradio_app"], env=env,
                            start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = "http://127.0.0.1:%d" % CAP_PORT
    t0 = time.time()
    try:
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError("the capture copy of the UI exited (rc=%s)" % proc.returncode)
            try:
                urllib.request.urlopen(url, timeout=2).read(1)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("the capture copy of the UI never answered on :%d" % CAP_PORT)
        print("    ui on %-10s up in %4.1fs" % (tab_id, time.time() - t0), flush=True)
        yield url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def gradio_tab(launch, tab_id: str, name: str, after=None) -> None:
    """One Gradio frame: a fresh app already open on the tab, no switching."""
    with ui_on_tab(tab_id) as url:
        browser = launch()
        pg = browser.new_page(viewport=VIEW)
        pg.set_default_timeout(30000)
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=90000)
            pg.wait_for_timeout(9000)
            print("    selected: %s" % pg.evaluate(TAB_SELECTED), flush=True)
            if after:
                try:
                    after(pg)
                except Exception as e:
                    print("    %s: interaction skipped (%s)" % (tab_id, type(e).__name__),
                          flush=True)
            shot(pg, name)
        finally:
            keep(pg, browser)


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
        keep(pg, browser)


def attu(launch, route: str, name: str, wait: int = 9000, query: bool = False) -> None:
    """One Attu frame. Connect first, then take the route.

    Attu asks for the Milvus address in every fresh browser profile, and each
    shot here gets a fresh one. The address is prefilled from the container's
    MILVUS_URL, so it is one click - but until it is clicked, every route
    renders the connect dialog, which is exactly what three frames of a previous
    run turned out to be. The frames that looked right came from a browser that
    had been connected by hand.

    The route itself matters too: #/databases/<db>/<collection>/<tab>, not
    #/databases/<db>/collections/<collection>, which renders the shell with
    every tab empty. See docs/screenshots/README.md.
    """
    browser = launch()
    pg = browser.new_page(viewport=VIEW)
    pg.set_default_timeout(30000)
    try:
        pg.goto(ATTU + "/", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        btn = pg.get_by_role("button", name="Connect", exact=True)
        if btn.count():
            btn.first.click(timeout=20000)
            pg.wait_for_timeout(6000)
            print("    attu: connected", flush=True)
        pg.goto(ATTU + "/" + route, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(wait)
        if query:
            # The Data tab starts empty: it shows rows only once a query runs.
            pg.get_by_role("button", name="Query", exact=True).first.click(timeout=20000)
            pg.wait_for_timeout(7000)
            print("    attu: queried", flush=True)
        shot(pg, name)
    finally:
        keep(pg, browser)


# --------------------------------------------------------------- interactions
# Playwright's own locators, not hand-written JS. The first version of this file
# used JS because a switched-to tab could not answer anything; now that no tab
# is ever switched (note 3) the page is responsive and the locators are both
# shorter and harder to get wrong - the JS button-finder quietly returned
# 'no-button' for a button plainly labelled "Ask".
#
# Each interaction is best-effort, and the caller wraps it: a frame of the tab
# as it loads is worth more than no frame, so a selector that has moved degrades
# to the un-interacted view rather than losing the capture.

def choose(nth: int = 0, settle: int = 7):
    """Pick a value from the tab's first dropdown, so the frame shows a real
    record instead of the empty "select something" state.

    Gradio's dropdown is an input plus a popup list, not a <select>, and the
    list is rendered only after the input is clicked.
    """
    def _(pg):
        pg.locator("input[role=listbox], .wrap input").first.click(timeout=15000)
        opt = pg.locator("li[role=option], ul[role=listbox] li").nth(nth)
        opt.wait_for(state="visible", timeout=15000)
        label = (opt.text_content() or "").strip()[:24]
        opt.click(timeout=15000)
        print("      chose %r, then %ds" % (label, settle), flush=True)
        time.sleep(settle)
    return _


def ask(question: str, settle: int = 60):
    """Type a question and submit it. settle seconds covers the model round trip."""
    def _(pg):
        pg.locator("textarea").first.fill(question, timeout=15000)
        pg.get_by_role("button", name="Ask", exact=True).first.click(timeout=15000)
        print("      asked, then %ds for the model" % settle, flush=True)
        time.sleep(settle)
    return _


def press(label: str, settle: int = 20):
    """Press a button by (partial, case-insensitive) label. settle is seconds."""
    def _(pg):
        pg.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=15000)
        print("      pressed %r, then %ds" % (label, settle), flush=True)
        time.sleep(settle)
    return _


# --------------------------------------------------------------------- the set
# `probe` is a string that must appear in the page's VISIBLE text. It is checked
# after the shot is saved, so a probe that cannot run never costs a capture - but
# the run prints found/MISSING for every frame, which is the only cheap way to
# know a screenshot shows what its caption claims.

def build_plan(b):
    return [
        ("01-app-dashboard.jpg",          "RO-26-",
         lambda: gradio_tab(b, "dashboard", "01-app-dashboard.jpg")),
        ("02-app-repair-order.jpg",       "Derived state",
         lambda: gradio_tab(b, "ro", "02-app-repair-order.jpg",
                            choose(1, 8))),
        ("03-app-technician-update.jpg",  "Submit structured update",
         lambda: gradio_tab(b, "update", "03-app-technician-update.jpg",
                            choose(1, 8))),
        ("04-app-shift-handover.jpg",     "Handover brief",
         lambda: gradio_tab(b, "handover", "04-app-shift-handover.jpg",
                            press("generate", 45))),
        ("05-app-manager-assistant.jpg",  "Assistant",
         lambda: gradio_tab(b, "assistant", "05-app-manager-assistant.jpg",
                            ask("Which vehicles cannot be released on safety grounds?", 70))),
        ("06-app-data-and-retrieval.jpg", "Event log",
         lambda: gradio_tab(b, "data", "06-app-data-and-retrieval.jpg")),
        ("07-prometheus-targets.jpg",     "dcgm",
         lambda: simple(b, PROM + "/targets", "07-prometheus-targets.jpg", 8000)),
        ("08-prometheus-tool-calls.jpg",  "asoia_tool_calls_total",
         lambda: simple(b, PROM + "/graph?g0.expr=rate(asoia_tool_calls_total%5B5m%5D)*60"
                                  "&g0.tab=0&g0.range_input=30m",
                        "08-prometheus-tool-calls.jpg", 12000)),
        ("09-grafana-dashboard.jpg",      "composed in Python",
         lambda: simple(b, GRAF + "/d/asoia/?kiosk&from=now-30m&to=now", "09-grafana-dashboard.jpg", 16000)),
        ("10-attu-collections.jpg",       "Loaded",
         lambda: attu(b, "#/databases/default/collections", "10-attu-collections.jpg", 10000)),
        ("11-attu-schema-1024.jpg",       "FloatVector",
         lambda: attu(b, "#/databases/default/updates/schema", "11-attu-schema-1024.jpg", 10000)),
        ("11b-attu-data.jpg",             "update_id",
         lambda: attu(b, "#/databases/default/updates/data", "11b-attu-data.jpg", 8000,
                      query=True)),
        ("12-sqlite-web.jpg",             "updates",
         lambda: simple(b, SQLW + "/", "12-sqlite-web.jpg", 6000)),
    ]


# Seconds a shot may take before the parent kills it. The two that wait on a
# real model round trip get more; everything else waits only on a page.
# A Gradio frame pays for an app start (~25s) on top of the page.
BUDGET = {"01": 200, "02": 200, "03": 200, "04": 240, "05": 280, "06": 200}
DEFAULT_BUDGET = 130


def one_shot(num: str) -> int:
    """Child: take exactly one shot and leave without unwinding anything."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        def b():
            return p.chromium.launch(headless=False, args=ARGS)
        for name, probe, fn in build_plan(b):
            if name.split("-")[0] != num:
                continue
            PROBE[0] = probe
            fn()
            sys.stdout.flush()
            os._exit(0)                      # see keep(): teardown is the parent's job
    print("    no such shot: %r" % num, flush=True)
    return 2


def _spawn(num: str, budget: int) -> str:
    """Run one shot in its own session, and kill the whole group when it ends.

    The kill is unconditional: a child that finished normally still leaves a
    Chromium behind, because it exits without closing one on purpose.
    """
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--shot", num],
                            start_new_session=True)
    try:
        proc.wait(timeout=budget)
        how = "rc=%d" % proc.returncode
    except subprocess.TimeoutExpired:
        how = "killed at %ds" % budget
        print("    over budget - killing the process group", flush=True)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # start_new_session: pgid == pid
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
    return how


def main() -> int:
    if "--shot" in sys.argv:
        return one_shot(sys.argv[sys.argv.index("--shot") + 1])

    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))

    shots = []
    for name, _probe, _fn in build_plan(None):
        num = name.split("-")[0]
        if only and num not in only:
            continue
        print("  %s" % name, flush=True)
        f, t0 = OUT / name, time.time()
        was = f.stat().st_mtime if f.exists() else 0.0
        how = _spawn(num, BUDGET.get(num, DEFAULT_BUDGET))
        fresh = f.exists() and f.stat().st_mtime > was
        shots.append((name, "ok" if fresh else "FAILED", how, time.time() - t0))

    ok = sum(1 for _, s, _, _ in shots if s == "ok")
    print("\n  %d/%d captured" % (ok, len(shots)), flush=True)
    for n, s, how, el in shots:
        print("    %-34s %-7s %5.1fs  %s" % (n, s, el, how), flush=True)
    return 0 if ok == len(shots) else 1


if __name__ == "__main__":
    raise SystemExit(main())
