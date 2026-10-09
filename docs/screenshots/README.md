# Screenshots

**All thirteen are from 2026-10-09, from one box with all three NIMs local.**
They were taken in four runs between 18:12 and 18:33 UTC, every one by
`scripts/capture_screenshots.py` against the running stack — none by hand.

```bash
xvfb-run -a .venv/bin/python scripts/capture_screenshots.py            # all of them
xvfb-run -a .venv/bin/python scripts/capture_screenshots.py --only 09  # just one
```

Every frame declares a string that must appear in the page's visible text, and
the run prints `found` or `MISSING` for each. That is the cheap version of
checking a screenshot says what its caption claims, and it is what caught three
frames of an Attu dialog being passed off as the vector store.

| | | shows |
|---|---|---|
| 01 | Dashboard | **66 open repair orders** — 11 safety, 43 promise missed, 51 blocked, 14 waiting — and the 59 that need a decision, each row giving the measurement against its limit |
| 02 | Repair Order | RO-26-08074 folded from its events: `AWAITING_AUTHORISATION`, promise **breached**, 1.7 h booked against 1.5 flat rate, ops done and outstanding, DTCs, the safety finding, **12 source events cited** — beside the three updates as written |
| 03 | Technician Update | the same RO's context *before* anything is typed: what is unsafe, what blocks it, what is already done with hours. That is what stops work being logged twice |
| 04 | Shift Handover | the afternoon brief — 66 open, 51 blocked, 11 safety, 49 at risk — safety first, each entry carrying its measurement and the next action |
| 05 | Manager Assistant | a cited answer: `Tools: list_ros · computed from the records · Sources: RO-26-08031, RO-26-08074, RO-26-08062, RO-26-08052, RO-26-08165, RO-26-08274` — the same six ids as `docs/EXAMPLES.md` |
| 06 | Data & Retrieval | what the answers are built from: 400 repair orders, 10,022 events, 1,690 technician updates, 50 staff, 476 answers logged |
| 07 | Prometheus targets | `asoia` on :9400 **and `dcgm` on :9401**, both UP — the second is what puts real GPU telemetry on the dashboard |
| 08 | Prometheus tool calls | `rate(asoia_tool_calls_total[5m])*60` over 30 minutes, **six series**, two load bursts, `list_ros` peaking at 10.3/min and `search_updates` the rare one |
| 09 | Grafana | **90.9% composed in Python**, ungrounded **0**, cut short **0**, guardrail blocks and NIM errors flat at zero, p50 llm ~3s against python ~0s, and SM util hitting **100%** on the semantic queries |
| 10 | Attu collections | `updates`, **Loaded**, approx count 1,690 |
| 11 | Attu schema | **`vector` FloatVector(1024), AUTOINDEX(COSINE)**, Loaded, replica 1, 1,690 entities, 13 declared fields plus the dynamic `$meta` |
| 11b | Attu data | real rows — `pk`, the **1024-float vectors themselves**, `update_id`, `ro_number`, `staff_id`, `staff_name`, timestamps |
| 12 | sqlite-web | the system of record: 9 tables, 12 indexes, 6.4 MB, `events` and `updates` beside `answer_log` |

## Switching a Gradio tab is what made four frames impossible

03, 04, 05 and 06 sat at an older date for two days, and the reason given here
twice was wrong both times — first "the third page in a browser session", then
"the microphone on the Technician Update tab". Neither.

**Clicking from one tab to another throws `effect_update_depth_exceeded` — a
Svelte reactive loop — about fifteen times a second and never stops.** The
renderer pins 102% of a core, an `evaluate` never returns (and its own timeout
does not fire either, which is why runs looked hung rather than failed), and
`Page.screenshot` times out at 60s. Gradio is 6.15.1.

It is the **switch**, not any tab: a fresh page load on any tab is clean, zero
page errors, screenshot in 0.4s. Rebuilt in toy apps, the suspects all stay
clean — 400-row dataframes, 200-item filterable dropdowns, the KPI flex strip,
the whole Repair Order tab. So the trigger needs the full page, and it is not
something this repo can fix.

**What fixed the frames was not switching.** `ASOIA_UI_TAB` opens the app on a
chosen tab, and each Gradio frame now starts a second copy of the app on :7869
already open on the tab it wants, with the whole tab bar intact. The UI on
:7860 is left running and untouched. See `docs/OPERATING.md`.

Two things fell out of this that are not about screenshots at all:

- **Each shot runs in its own process**, and the parent kills the process group
  when it finishes or runs over budget. Nothing calls `browser.close()` — a
  wedged renderer never answers one and the call blocks forever, which is how a
  single bad frame used to take the other twelve with it.
- **Two tabs showed nothing until you changed the dropdown.** Repair Order and
  Technician Update both come up with the first repair order selected, but their
  content was wired to `.change()` only — so a person arriving saw an RO
  selected and an empty panel under it. Both now also fill on load. 02 and 03
  are the first frames to show what those tabs are for.

## Attu asks to connect in every fresh browser

A run before this one produced three Attu frames that were all the same 45 KB
picture of **the connect dialog**. Attu keeps the Milvus connection in browser
state, and every shot here gets a clean profile, so every route rendered the
dialog instead. The frames that had looked right came from a browser someone
had connected by hand.

The address is prefilled from the container's `MILVUS_URL`, so the fix is one
click before taking the route. The route matters too:

    #/databases/default/updates/overview      <- loads the collection into state
    #/databases/default/collections/updates   <- renders the shell, tabs stay empty

and the **Data** tab starts empty by design: it shows rows only after `Query` is
pressed, which is why 11b used to be a picture of an empty table.

## Capturing them under load, which is the whole point

**08, 09 and 10 were wrong twice before they were right.** The first re-take
showed the stack up and the application idle: `asoia_tool_calls_total` returned
*Empty query result* and every Grafana application panel read *No data*.

The reason is worth writing down. Traffic was driven by calling
`app.agent.agent.ask()` from a standalone Python process. Prometheus counters
are **per-process**, and the exporter Prometheus scrapes on :9400 belongs to the
API server — so those calls incremented counters in a process that then exited,
and the dashboard never saw them. Driving the same questions through
`POST /ask` on :8080 put the series on the exporter and filled every panel.

So: **exercise the app through the API, then capture.** A screenshot taken
straight after `stack.sh up` shows an idle dashboard no matter how healthy the
box is. The panels in 08 and 09 run over 30 minutes rather than an hour for the
same reason — an hour of mostly-idle axis tells you less than the bursts do.

## A healthy zero is not "No data"

Four panels read *No data* no matter how well the stack was running:
**Ungrounded answers**, **Compose notes**, **Answers cut short** and
**Guardrail blocks**. Prometheus returns an empty vector for a counter whose
labelled child has never been created, and `asoia_grounding_warnings_total` has
no child precisely *because* nothing was ever ungrounded. Grafana renders that
identically to the exporter being down.

The dashboard wraps those queries in `(...) or vector(0)`, so a healthy zero
says **0**. That is a dashboard fix, not a metric change — the underlying
counters are untouched.

## What a run surfaced: a retry bug, not a slow model

Driving real load once put **42 `asoia_nim_errors_total{cause="ReadTimeout",
service="llm"}`** on the exporter while the LLM NIM itself stayed healthy.

`_post` retried **every** exception four times, so one `POST /updates` whose
extraction exceeded the 120s budget occupied the LLM for up to eight minutes;
everything queued behind it timed out too, and each of those was retried four
times. Fixed in `b9a80f9`: read timeouts now fail on the first attempt. The
frames here were taken across two load bursts with **no NIM error series at
all** — the panel is flat at zero because nothing failed.

**The model itself is fast.** Measured on an idle box: 100 tokens in 1.39s, 215
in 2.99s, a real semantic question end to end in 3.52s. An earlier note here
claimed ~0.37 tok/s and blamed guided-decoding FSM compilation — that was
measured while a load generator of mine was still running, and was wrong. See
`docs/OPERATING.md`.

## The Python-share panel was wrong twice

It read 87.5% in one capture and 100% in the next, and 0% while idle:

    100 * sum(rate(asoia_answers_total{compose="python"}[5m]))
        / clamp_min(sum(rate(asoia_answers_total[5m])), 0.0001)

**A 5-minute rate** reflects only the last handful of questions, and `clamp_min`
turned an undefined ratio into a confident **0%** whenever nothing was
happening — indistinguishable from the deterministic path collapsing.

The second attempt subtracted `asoia_compose_fallbacks_total` from the numerator
to get "Python by design", and **that was wrong too**. Every one of those notes
reads *"the answer names the records; the retry was uncited and was discarded"*
— they are discarded **narration retries on LLM answers**, not answers that fell
back to Python. Subtracting them understated the figure badly (74.7% against a
true 89.8% at the time).

The panel is now the plain ratio over an hour, with no clamp and nothing
subtracted:

    100 * sum(increase(asoia_answers_total{compose="python"}[1h]))
        / sum(increase(asoia_answers_total[1h]))

and the fallbacks panel is retitled **"Compose notes (retries discarded)"**,
because a non-zero number there is the citation guard working, not a failure.

One caveat that still stands: `compose` records the path that **finished**, not
the path that was chosen. An answer that called the model, timed out and fell
back to Python counts as Python — so a failing LLM pushes this number up. With
no NIM errors in the window, 90.9% is a clean reading; with errors in it, it
would not be.
