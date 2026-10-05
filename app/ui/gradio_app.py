"""Gradio front end for the Automotive Service Operations Intelligence Agent.

Runs entirely on the deterministic engine - no GPU or LLM required. The voice
and agent layers plug into the same surfaces once the NIMs are up.

Five surfaces, not six: Dashboard folds the shop floor, the cross-RO patterns
and technician activity into one screen, so the detail is reachable without
three tabs of it competing for attention.
"""
from __future__ import annotations
import os, json
from datetime import datetime
import gradio as gr
import pandas as pd

from app.state import db as dbm
from app.analytics.queries import get_ro_state, get_ro_timeline, list_ros, get_technician_activity
from app.analytics.insights import generate_handover, detect_anomalies, diff_ro
from app.pipeline.reconcile import reconcile
from app.pipeline.diffcard import render as render_diff
from app.data.catalog import LABOUR_OPS, OP_BY_CODE


def CON_() -> 'dbm.sqlite3.Connection':
    """Per-thread connection - Gradio handlers run in a worker pool."""
    return dbm.connect()


class _ConProxy:
    def __getattr__(self, name):
        return getattr(dbm.connect(), name)


CON = _ConProxy()
# Reads use NOW: ASOIA_NOW if pinned, else the newest event in the log, else the
# wall clock. Writes use EVENT_TIME, which is one second later so the log stays
# strictly ordered. app/state/clock.py says why the default is the data.
from app.state.clock import now as NOW, event_time as EVENT_TIME
OP_CHOICES = [f"{o.op_code} · {o.description}" for o in LABOUR_OPS]
_code = lambda s: s.split(" · ")[0] if s else None

FILTERS = ["active", "blocked", "at_risk", "safety", "waiter", "all"]


def _staff_choices():
    rows = CON.execute("SELECT staff_id,name,role FROM staff WHERE role='TECHNICIAN' ORDER BY staff_id").fetchall()
    return [f"{r['staff_id']} · {r['name']}" for r in rows]


def _ro_choices(filter="active"):
    return [r["ro_number"] for r in list_ros(CON, filter, limit=200, now=NOW())["ros"]]


def _hhmm(v) -> str:
    return str(v or "")[11:16]


def _title(v) -> str:
    return str(v or "").replace("_", " ").title()


# ==========================================================================
# Dashboard
# ==========================================================================
# Counting happens here, in Python, exactly as everywhere else in this app.

_CRIT = "#c0392b"
_WARN = "#b9770e"


def _kpi_html(rows: list[dict]) -> str:
    """Headline counts as tiles. Colour is used only to mark severity, and only
    on the foreground, so it survives both light and dark themes."""
    tiles = [
        ("Open repair orders", len(rows), None),
        ("Safety - do not release", sum(1 for r in rows if r.get("safety")), _CRIT),
        ("Promise missed", sum(1 for r in rows if r.get("promise_risk") == "BREACHED"), _CRIT),
        ("Promise at risk", sum(1 for r in rows if r.get("promise_risk") == "AT_RISK"), _WARN),
        ("Blocked", sum(1 for r in rows if r.get("blocked")), _WARN),
        ("Customer waiting", sum(1 for r in rows if r.get("wait_type") == "WAITER"), None),
        ("Operations outstanding", sum(int(r.get("pending_count") or 0) for r in rows), None),
    ]
    cells = []
    for label, value, colour in tiles:
        style = f"color:{colour};" if colour and value else ""
        cells.append(
            "<div style='flex:1 1 140px;min-width:140px;border:1px solid rgba(128,128,128,.35);"
            "border-radius:10px;padding:12px 14px;'>"
            f"<div style='font-size:1.9rem;font-weight:650;line-height:1.1;{style}'>{value}</div>"
            f"<div style='font-size:.78rem;opacity:.72;margin-top:4px;'>{label}</div></div>")
    return ("<div style='display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 2px;'>"
            + "".join(cells) + "</div>")


def _action_df(rows: list[dict]) -> pd.DataFrame:
    """Only the repair orders that need a decision, with the reason spelled out.
    Safety findings are the measurement against spec, not the customer's words."""
    out = []
    for r in rows:
        why = []
        if r.get("safety"):
            why += (r.get("safety_detail") or ["safety flag raised"])
        if r.get("promise_risk") == "BREACHED":
            why.append("promised time already missed")
        elif r.get("promise_risk") == "AT_RISK":
            why.append("at risk of missing promised time")
        if r.get("blocked") and r.get("blocked_on"):
            why.append(f"waiting on {r['blocked_on']}")
        if not why:
            continue
        out.append({
            "RO": r.get("ro_number"),
            "Vehicle": r.get("vehicle") or "",
            "Why it needs attention": " · ".join(why),
            "State": _title(r.get("state")),
            "Promised": _hhmm(r.get("promised_time")),
            "Customer": "waiting on site" if r.get("wait_type") == "WAITER" else "",
            "To do": r.get("pending_count") or 0,
        })
    return pd.DataFrame(out)


def _shop_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "RO": r.get("ro_number"), "Vehicle": r.get("vehicle") or "",
        "Reg": r.get("registration") or "",
        "State": _title(r.get("state")), "Risk": _title(r.get("promise_risk")),
        "Safety": "YES" if r.get("safety") else "",
        "Blocked on": r.get("blocked_on") or "",
        "Promised": _hhmm(r.get("promised_time")),
        "Type": _title(r.get("wait_type")), "To do": r.get("pending_count") or 0,
    } for r in rows])


def _insight_md(a: dict, days) -> str:
    """Cross-RO patterns, in prose a service manager can act on."""
    L = [f"Patterns across the last **{days} days**."]
    s = a.get("summary") or {}
    if isinstance(s, dict) and s:
        L.append("  ·  ".join(f"{_title(k)}: **{v}**" for k, v in s.items()))

    if a.get("shared_part_holds"):
        L.append("\n**One part blocking several jobs** - order once, clear several")
        for x in a["shared_part_holds"]:
            L.append(f"- `{x['part_no']}` is holding **{x['ro_count']}** repair orders: "
                     f"{', '.join(x['ros'])}")
    if a.get("authorisation_delays"):
        L.append("\n**Waiting on customer authorisation**")
        for x in a["authorisation_delays"]:
            tag = " - customer waiting on site" if x.get("wait_type") == "WAITER" else ""
            L.append(f"- {x['ro_number']} {x['vehicle']} - **{x['waiting_hours']}h** "
                     f"without a decision{tag}")
    if a.get("stalled_ros"):
        L.append("\n**Stalled - nothing logged for over a day**")
        for x in a["stalled_ros"]:
            L.append(f"- {x['ro_number']} {x['vehicle']} - idle **{x['idle_hours']}h** "
                     f"in {_title(x['state'])}, last touched by {x['last_actor']}")
    if a.get("comebacks"):
        L.append("\n**Comebacks and rework**")
        for x in a["comebacks"]:
            det = x.get("detail")
            det = "; ".join(det) if isinstance(det, list) else (det or "")
            L.append(f"- {x['ro_number']} {x['vehicle']} - **{x['count']}** "
                     f"{'occurrence' if x['count'] == 1 else 'occurrences'}"
                     + (f": {det}" if det else ""))
    if a.get("repeat_visits"):
        L.append("\n**Same vehicle back again**")
        for x in a["repeat_visits"]:
            L.append(f"- VIN `{x['vin']}` - **{x['visits']}** visits: {', '.join(x['ros'])}")
    if len(L) <= 2:
        L.append("\nNothing unusual in this window.")
    return "\n".join(L)


def ui_dashboard(filt, days):
    """One screen: headline counts, what needs a decision, the full shop, patterns."""
    live = list_ros(CON, "active", limit=500, now=NOW())["ros"]
    shop = list_ros(CON, filt, limit=200, now=NOW())
    anomalies = detect_anomalies(CON, days=int(days), now=NOW())
    action = _action_df(live)
    note = ("Nothing needs a decision right now." if action.empty
            else f"**{len(action)}** repair orders need a decision, most urgent first.")
    return (_kpi_html(live), note, action,
            f"**{shop['count']}** repair orders  ·  filter `{filt}`",
            _shop_df(shop["ros"]), _insight_md(anomalies, days))


# ==========================================================================
# Repair order detail
# ==========================================================================
def ui_ro_detail(ro_number):
    if not ro_number:
        return "Select a repair order.", pd.DataFrame()
    s = get_ro_state(CON, ro_number, now=NOW())
    if not s.get("found"):
        return s.get("error", "Not found"), pd.DataFrame()
    L = [f"{s['ro_number']} · {s['vehicle']} · {s['odometer_miles']:,} mi",
         f"VIN {s['vin']}   Reg {s['registration']}", "",
         f"Concern      : {s['concern']}",
         f"State        : {s['state']}" + (f"   BLOCKED ON: {s['blocked_on']}" if s["blocked"] else ""),
         f"Promised     : {_hhmm(s['promised_time'])}   Risk: {s['promise_risk']}",
         f"Pay / Wait   : {s['pay_type']} / {s['wait_type']}",
         f"Hours booked : {s['hours_booked']}  (flat rate earned {s['flat_rate_total']}"
         + (f", proficiency {s['proficiency']})" if s["proficiency"] else ")"), ""]
    if s["completed"]:
        L.append("COMPLETED"); L += [f"  ✓ {c['description']}  {c['actual_hrs'] or ''} hr" for c in s["completed"]]
    if s["pending"]:
        L.append(""); L.append("PENDING"); L += [f"  ○ {p['description']}" for p in s["pending"]]
    if s["recommended"]:
        L.append(""); L.append("RECOMMENDED (needs authorisation)"); L += [f"  + {r['description']}" for r in s["recommended"]]
    if s["parts"]:
        L.append(""); L.append("PARTS"); L += [f"  · {p}: {d.get('availability')}" for p, d in s["parts"].items()]
    if s["dtc_codes"]:
        L.append(""); L.append(f"DTCs: {', '.join(s['dtc_codes'])}")
    if s["safety_flags"]:
        L.append(""); L.append("SAFETY"); L += [f"  ⚠ {f['detail']}" for f in s["safety_flags"]]
    if s["conflicts"]:
        L.append(""); L.append("CONFLICTS"); L += [f"  ⚠ {c['detail']}" for c in s["conflicts"]]
    L += ["", f"Source events: {len(s['citations'])} cited"]
    tl = get_ro_timeline(CON, ro_number)
    df = pd.DataFrame([{"At": e["at"][5:16].replace("T", " "), "Shift": e["shift"],
                        "By": e["by"], "Role": e["role"], "Update": e["text"]}
                       for e in tl["entries"]]) if tl.get("found") else pd.DataFrame()
    return "\n".join(L), df


# ==========================================================================
# Technician update
# ==========================================================================
def ui_tech_context(ro_number):
    """What is already logged against the selected repair order.

    Without this the technician picks from the whole catalogue with no sight of
    what the RO already says - which is how work gets logged twice or missed.
    The RO's own outstanding operations are also lifted to the top of each
    picker, so the common case is one click rather than a search.
    """
    blank = gr.update(choices=OP_CHOICES)
    if not ro_number:
        return ("Select a repair order to see what is already logged against it.",
                blank, blank, blank)
    s = get_ro_state(CON, ro_number, now=NOW())
    if not s.get("found"):
        return (s.get("error", "Not found"), blank, blank, blank)

    L = [f"**{s['ro_number']}** - {s['vehicle']}, {s['registration']}  ·  "
         f"**{_title(s['state'])}**  ·  promised {_hhmm(s['promised_time'])}"
         f" ({_title(s['promise_risk'])})",
         f"Customer reported: {s['concern']}"]
    if s.get("safety_flags"):
        L.append("\n**Safety - do not release**")
        L += [f"- {f['detail']}" for f in s["safety_flags"]]
    if s.get("blocked") and s.get("blocked_on"):
        L.append(f"\n**Blocked** - waiting on {s['blocked_on']}")

    def section(key, label, mark):
        items = s.get(key) or []
        if not items:
            return [f"\n**{label}:** none recorded yet"]
        out = [f"\n**{label}**"]
        for o in items:
            hrs = f" - {o['actual_hrs']} h" if o.get("actual_hrs") else ""
            out.append(f"- {mark} {o.get('description') or o.get('op_code')}{hrs}")
        return out

    L += section("completed", "Already completed", "✓")
    L += section("pending", "Still outstanding", "○")
    L += section("recommended", "Recommended, awaiting authorisation", "+")
    if s.get("parts"):
        L.append("\n**Parts**")
        L += [f"- {p}: {_title((d or {}).get('availability'))}" for p, d in s["parts"].items()]

    # This RO's own operations first, then the rest of the catalogue.
    relevant = [f"{o['op_code']} · {o['description']}"
                for o in (s.get("pending") or []) + (s.get("recommended") or [])
                if o.get("op_code")]
    ordered = list(dict.fromkeys(relevant + OP_CHOICES))
    upd = gr.update(choices=ordered)
    return "\n".join(L), upd, upd, upd


def ui_submit(ro_number, tech, completed, hrs, pending, recommended,
              meas_type, meas_val, meas_min, note):
    if not ro_number:
        return "Select a repair order first."
    gt = {"completed": [], "pending": [], "correction": [], "parts": [],
          "measurements": [], "dtc_codes": [], "state_signal": None, "_text": note or ""}
    for c in completed or []:
        gt["completed"].append({"op_code": _code(c), "actual_hrs": float(hrs) if hrs else None})
    for p in pending or []:
        gt["pending"].append({"op_code": _code(p)})
    for r in recommended or []:
        gt["correction"].append({"op_code": _code(r), "status": "RECOMMENDED"})
    if meas_type and meas_val is not None:
        oos = float(meas_val) < float(meas_min or 0)
        gt["measurements"].append({"type": meas_type, "value": float(meas_val), "unit": "mm",
                                   "spec_min": float(meas_min or 0), "out_of_spec": oos,
                                   "safety_related": oos})
    rec = reconcile(CON, ro_number, gt, _code(tech) or "EMP001",
                    at=EVENT_TIME(),
                    update_id=f"UPD-UI-{datetime.now().strftime('%H%M%S')}")
    return render_diff(rec, dbm.get_ro(CON, ro_number), now=NOW())


# ==========================================================================
# Handover
# ==========================================================================
def ui_handover(shift):
    h = generate_handover(CON, shift, now=NOW())
    t = h["totals"]
    L = [f"SHIFT HANDOVER → {shift}    generated {_hhmm(h['generated_at'])}",
         "=" * 62,
         f"Open ROs {t['open']}   Blocked {t['blocked']}   Safety {t['safety']}   "
         f"Promise at risk {t['at_risk']}   Open items {t['pending_ops']}", ""]
    titles = {"SAFETY": "SAFETY - ACTION REQUIRED", "BREACHED": "PROMISE BREACHED",
              "AT_RISK": "PROMISE AT RISK", "BLOCKED": "BLOCKED", "IN_FLIGHT": "IN FLIGHT"}
    for g, items in h["groups"].items():
        L.append(f"{titles.get(g,g)}  ({len(items)})"); L.append("-" * 62)
        for it in items:
            L.append(f"  {it['ro_number']}  {it['vehicle']}  [{it['state']}]")
            L.append(f"      concern : {it['concern']}")
            if it["safety"]: L.append(f"      safety  : {'; '.join(it['safety'])}")
            if it["blocked_on"]: L.append(f"      blocked : {it['blocked_on']}")
            if it["pending"]: L.append(f"      pending : {', '.join(it['pending'])}")
            L.append(f"      NEXT    : {it['next_action']}")
        L.append("")
    return "\n".join(L)


def ui_tech_activity(tech, days):
    r = get_technician_activity(CON, _code(tech) or "", days=int(days), now=NOW())
    if not r.get("found"):
        return r.get("error", "not found")
    L = [f"**{r['name']}** ({r['staff_id']})  ·  {_title(r['role'])}  ·  "
         f"{_title(r['skill'])}  ·  {_title(r['shift'])} shift",
         f"\nOver the last **{r['window_days']} days**: **{r['ops_completed']}** operations "
         f"across **{r['ros_touched']}** repair orders, **{r['updates_posted']}** updates posted.",
         f"\nBooked **{r['hours_booked']} hours** against **{r['flat_rate_earned']}** "
         f"flat-rate hours allowed"
         + (f" - a ratio of **{r['proficiency']}**." if r.get("proficiency") else ".")]
    if r.get("top_categories"):
        L.append("\n" + "  ·  ".join(f"{c}: **{n}**" for c, n in r["top_categories"]))
    if r.get("completed"):
        L.append("\n**Work completed**")
        for c in r["completed"]:
            L.append(f"- {c.get('description') or c.get('op_code')} on {c['ro_number']}"
                     f" - {c.get('actual_hrs')} h"
                     + ("  **safety-critical**" if c.get("safety_critical") else ""))
    return "\n".join(L)


# ==========================================================================
# Voice and free text
# ==========================================================================
def ui_transcribe(audio_path):
    """Speech -> editable transcript. The technician always reviews before submit."""
    if not audio_path:
        return "", "No audio captured."
    from app.pipeline.asr import transcribe
    t = transcribe(audio_path)
    if not t.ok:
        # Put the reason IN the transcript box. It used to go only to the status
        # line beside the button, while the box kept showing its grey placeholder
        # - which read as a filled-in update, so the failure was invisible.
        return (f"[ Transcription failed - type the update here instead ]\n\n"
                f"{t.error}",
                f"**Transcription failed.** {t.error}")
    dur = f" ({t.duration_s:.1f}s)" if t.duration_s else ""
    return t.text, f"Transcribed{dur}. Check it, correct anything, then submit."


def ui_submit_nl(ro_number, tech, text):
    """Free-text or transcribed update through the full pipeline."""
    if not (text or "").strip():
        from app.pipeline.asr import health as asr_health
        h = asr_health()
        hint = ("" if h["ready"] else
                f"\n\nSpeech to text is not ready: {h['mode']} via "
                f"{h['endpoint']}"
                + ("" if h["riva_client_installed"] or h["mode"] == "rest"
                   else ", and nvidia-riva-client is not installed."))
        return ("The transcript box is empty, so there is nothing to apply.\n\n"
                "The grey text in it is a placeholder, not content - click into "
                "the box and type or paste the update, or press Transcribe to "
                "fill it from audio." + hint), ""
    from app.pipeline.run import run
    try:
        from app.nim.client import embed as _emb
    except Exception:
        _emb = None
    res = run(CON, text=text, actor_id=_code(tech) or "EMP001",
              ro_number=ro_number or None, at=EVENT_TIME(), embed_fn=_emb)
    if res.error:
        return f"Pipeline error: {res.error}", ""
    qs = "\n".join(f"- {q}" for q in res.questions)
    if not res.applied and res.questions:
        return "Not applied - needs clarification:\n" + qs, _extract_summary(res.extraction)
    return res.diff_card + (("\n\nAlso needs clarification:\n" + qs) if qs else ""), \
           _extract_summary(res.extraction)


def _extract_summary(e):
    if e is None:
        return ""
    import json as _j
    return _j.dumps({"concern": e.concern, "cause": e.cause,
                     "completed": e.completed, "pending": e.pending,
                     "recommended": e.correction, "parts": e.parts,
                     "measurements": e.measurements, "dtc_codes": e.dtc_codes,
                     "severity": e.severity, "state_signal": e.state_signal,
                     "confidence": e.confidence}, indent=2)


# ==========================================================================
# Manager assistant
# ==========================================================================
def _warm_nims() -> None:
    """Take the cold start off the first question of a demo.

    The first request to a NIM after idle pays engine and cache warm-up, so
    without this the opening question of a demo is always the slowest one. Runs
    in a background thread and swallows everything: a workshop with no GPU
    endpoints must still get a UI.
    """
    def go():
        try:
            from app.nim.client import chat, embed_query
            embed_query("warm up")
            chat([{"role": "user", "content": "ok"}], max_tokens=1)
        except Exception:
            pass
    import threading
    threading.Thread(target=go, daemon=True).start()


def _footer(a) -> str:
    """The provenance line under an answer: which tools, which path, what sources.

    "Narrated by the model" needs its reason attached. On a free-text search that
    is the design; anywhere else it means a renderer was missing or broke, and the
    two should not read the same to someone deciding whether to trust the answer.
    """
    from app.agent.agent import _NARRATED
    tools = {c["name"] for c in a.tool_calls}
    if getattr(a, "composed", "") == "python":
        how = "computed from the records"
    elif tools and tools <= _NARRATED:
        how = "narrated by the model - free-text search, as designed"
    else:
        how = "narrated by the model"
    foot = (f"\n\n---\nTools: {', '.join(c['name'] for c in a.tool_calls)}"
            f"  ·  {how}")
    cites = ", ".join(a.citations[:6])
    if cites:
        foot += f"  ·  Sources: {cites}"
    notes = list(getattr(a, "compose_notes", None) or [])
    if notes:
        # A truncation note is not a fallback - it is a warning about an answer
        # that reached the reader incomplete, and it belongs at the front.
        cut = [n for n in notes if "cut short" in n]
        rest = [n for n in notes if "cut short" not in n]
        if cut:
            foot += "\n\n**" + cut[0] + "**"
        if rest:
            foot += ("\n\n_Fell back to the model: "
                     + "; ".join(rest[:2]) + "_")
    return foot


def ui_ask(question, history):
    """Manager assistant. Guardrails on the way in and on the way out.

    A generator, so the reader sees the stage the pipeline is in rather than a
    still screen. A deterministic answer needs no model call and arrives whole;
    only narration streams.
    """
    from app.guardrails.rails import check_input, check_output
    history = history or []
    q = (question or "").strip()
    if not q:
        yield history, ""
        return
    gate = check_input(q)
    if not gate.allowed:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant",
                        "content": f"{gate.text}\n\n_(blocked by {gate.rail})_"})
        yield history, ""
        return

    history = history + [{"role": "user", "content": q},
                         {"role": "assistant", "content": "_Reading the records..._"}]
    yield history, ""

    stream = os.environ.get("ASOIA_STREAM", "1") == "1"
    if stream:
        try:
            for h, done in _ask_streaming(q, history):
                history = h
                if not done:
                    yield history, ""
            yield history, ""
            return
        except Exception as e:
            history[-1]["content"] = f"_Streaming unavailable ({type(e).__name__}), " \
                                     f"answering in one piece..._"
            yield history, ""

    try:
        from app.agent.agent import ask
        a = ask(q)
        out_gate = check_output(a)
        if not out_gate.allowed:
            # The narrative is withheld, but the computed figures were never in
            # doubt - show them rather than handing back a dead end.
            from app.agent.agent import _figures
            body = f"{out_gate.text}\n\n_(blocked by {out_gate.rail})_"
            fig = _figures(a.results)
            if fig:
                body += ("\n\nThese figures come straight from the record and "
                         "are unaffected:\n" + fig)
            if a.citations:
                body += "\n\nSources: " + ", ".join(a.citations[:6])
        else:
            body = a.text + _footer(a)
    except Exception as e:
        body = (f"The assistant needs a reachable LLM endpoint. "
                f"({type(e).__name__}: {str(e)[:160]})")
    history[-1]["content"] = body
    yield history, ""


def _ask_streaming(q, history):
    """Run the pipeline, yielding (history, done) as each stage completes.

    The plan and the tools run first, so by the time anything is streamed the
    facts are already fixed - only the wording is still arriving. A deterministic
    answer therefore never streams: it is already complete.
    """
    from app.agent.agent import (plan_for, _summarise, _collect_citations,
                                 check_grounding, check_negations,
                                 _narration_system, _render, _figures, Answer)
    from app.agent.tools import call
    from app.guardrails.rails import check_output
    from app.nim.client import chat, chat_stream

    a = Answer(question=q)
    a.tool_calls, a.route = plan_for(q)
    history[-1]["content"] = ("_Reading the records: "
                              + ", ".join(c["name"] for c in a.tool_calls) + "..._")
    yield history, False

    for step in a.tool_calls:
        a.results.append({"tool": step["name"], "args": step.get("args", {}),
                          "result": call(step["name"], **step.get("args", {}))})
    a.citations = _collect_citations(a.results)

    notes: list = []
    summary = (_summarise(a.results, notes)
               if os.environ.get("ASOIA_DETERMINISTIC", "1") == "1" else None)
    a.compose_notes = notes
    if summary:
        a.composed, a.text = "python", summary
        a.warnings = check_grounding(a.text, a.results)
    else:
        a.composed = "llm"
        payload = _render(a.results)[:22000]
        msgs = [{"role": "system", "content": _narration_system(a.results)},
                {"role": "user", "content": f"Question: {q}\n\nRECORDS:\n{payload}"}]
        history[-1]["content"] = "_Writing..._"
        yield history, False
        acc, meta = "", {}
        try:
            for piece in chat_stream(msgs, temperature=0.0, max_tokens=400,
                                     meta=meta):
                acc += piece
                history[-1]["content"] = acc
                yield history, False
        except Exception:
            if not acc:                      # nothing shown yet - fall back cleanly
                acc = chat(msgs, temperature=0.0, max_tokens=400, meta=meta)
        a.text = acc
        if meta.get("finish_reason") == "length":
            a.compose_notes = list(a.compose_notes) + [
                "the model ran out of room at 400 tokens - the answer is cut short"]
        if os.environ.get("ASOIA_FIGURES", "1") == "1":
            fig = _figures(a.results)
            if fig:
                a.text = (a.text.rstrip() + "\n\n**Figures** (computed from the "
                          "record, not generated):\n" + fig)
        a.warnings = check_grounding(a.text, a.results)
        if os.environ.get("ASOIA_NEGATION_RAIL", "1") == "1":
            a.warnings += check_negations(a.text)
    a.grounded = not a.warnings

    g = check_output(a)
    if not g.allowed:
        body = f"{g.text}\n\n_(blocked by {g.rail})_"
        fig = _figures(a.results)
        if fig:
            body += ("\n\nThese figures come straight from the record and "
                     "are unaffected:\n" + fig)
        if a.citations:
            body += "\n\nSources: " + ", ".join(a.citations[:6])
    else:
        body = a.text + _footer(a)
    history[-1]["content"] = body
    yield history, True


# ==========================================================================
# Layout
# ==========================================================================
# ----------------------------------------------------------------- review views
from app.state.events import EventType as _EventType

_EVENT_TYPES = list(_EventType)

# Every one of these calls app/review/store.py and formats what comes back. No
# query lives here: the API serves the same numbers from the same functions, and
# two implementations of "how many events are there" would eventually disagree.

def _df(rows: list[dict], cols: list[str], trunc: dict | None = None) -> pd.DataFrame:
    """Selected columns, in order, with long text cut to keep a row one line high."""
    trunc = trunc or {}
    if not rows:
        return pd.DataFrame(columns=cols)
    out = []
    for r in rows:
        d = {}
        for c in cols:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)
            if c in trunc and isinstance(v, str) and len(v) > trunc[c]:
                v = v[:trunc[c]] + "…"
            d[c] = v
        out.append(d)
    return pd.DataFrame(out, columns=cols)


def ui_review_overview():
    from app.review import store as RS
    o = RS.overview()
    if o.get("database") != "ok":
        return f"### No data\n\n{o.get('database')}"
    vec = (f"{o['vector_rows']} chunks, {o['vector_dim']} dimensions"
           if o.get("vector_rows") else f"**not available** — {o.get('vector_error')}")
    c = o.get("clock") or {}
    clock = (f"**{c.get('now', '?')[:16]}** — {c.get('why', '?')}"
             if c.get("now") else c.get("error", "—"))
    st = o.get("index_staleness") or {}
    if st.get("ok") is True:
        stale = "matches the database"
    elif st.get("ok") is False:
        stale = "**OUT OF DATE** — " + "; ".join(st.get("reasons", []))
    else:
        stale = "—"
    warn = ""
    if c.get("wall_clock_would_break_time_questions"):
        warn += (f"\n\nThe data is {c.get('data_age_days')} days behind the wall "
                 f"clock. On the wall clock every time-window question — "
                 f"\"this week\", \"yesterday afternoon\", \"overnight\" — would "
                 f"return nothing and be blocked for citing nothing. Anchoring "
                 f"to the newest event is what keeps them working.")
    if st.get("ok") is False:
        warn += (f"\n\n**Rebuild the index.** Until then, answers can cite update "
                 f"ids that are not in the database:\n\n```\n{st.get('fix', '')}\n```")
    return (
        "### What the answers are built from\n\n"
        f"| | |\n|---|---|\n"
        f"| Now | {clock} |\n"
        f"| Repair orders | {o['repair_orders']} |\n"
        f"| Events | {o['events']} across {o['event_types_used']} of 17 types |\n"
        f"| Technician updates | {o['updates']} |\n"
        f"| Staff | {o['staff']} |\n"
        f"| Window | {str(o['first_event'])[:16]} → {str(o['last_event'])[:16]} |\n"
        f"| Vector index | {vec} |\n"
        f"| Index vs database | {stale} |\n"
        f"| Answers logged | {o['answers_logged']} |\n\n"
        "State is **not stored**. Every repair order's state is folded from its "
        "events on each read — the Fold tab shows that happening." + warn)


def ui_review_events(ro, etype, actor, hours, limit):
    from app.review import store as RS
    r = RS.events(ro_number=ro or None, event_type=(etype or None) if etype != "all" else None,
                  actor_id=actor or None, since_hours=int(hours) if hours else None,
                  limit=int(limit))
    df = _df(r["events"], ["at", "type", "ro_number", "actor_id", "shift",
                           "source_update_id", "payload", "event_id"],
             {"payload": 110})
    return f"{r['returned']} of {r['total']} matching events", df


def ui_review_event_types():
    from app.review import store as RS
    return _df(RS.event_types(), ["type", "n", "first_at", "last_at"])


def ui_review_fold(ro_number):
    from app.review import store as RS
    if not ro_number:
        return "Pick a repair order.", pd.DataFrame(), pd.DataFrame(), {}
    r = RS.ro_review(ro_number)
    if r.get("error"):
        return f"**{r['error']}**", pd.DataFrame(), pd.DataFrame(), {}
    if r.get("fold_error"):
        return (f"**The fold failed:** {r['fold_error']}", pd.DataFrame(),
                pd.DataFrame(), {})
    ro = r["ro"]
    md = (f"### {ro_number} — {r['state']}\n\n"
          f"{ro.get('model_year','')} {ro.get('make','')} {ro.get('model','')} · "
          f"{ro.get('category','')}\n\n"
          f"**Concern:** {ro.get('concern','')}\n\n"
          f"{r['event_count']} events folded into the state on the right. "
          f"Nothing below was read from a state column — there isn't one.")
    evs = _df(r["events"], ["at", "type", "actor_id", "shift",
                            "source_update_id", "payload"], {"payload": 90})
    ups = _df(r["updates"], ["at", "update_id", "staff_id", "shift", "text"],
              {"text": 160})
    return md, evs, ups, r["snapshot"]


def ui_review_index():
    from app.review import store as RS
    s = RS.index_stats()
    if not s.get("exists"):
        return (f"### No vector index\n\n{s.get('error')}\n\n"
                "Build it with:\n\n"
                "```\n.venv/bin/python -c 'from app.retrieval.index import build; "
                "print(build())'\n```")
    h = RS.index_health()
    size = f"{s['bytes'] / 1e6:.1f} MB" if s.get("bytes") else "—"
    health = (f"{h['sampled']} sampled, {h['zero_norm']} with a zero norm, "
              f"norms {h.get('min_norm')}–{h.get('max_norm')}"
              if "sampled" in h else h.get("error", "—"))
    warn = ("" if h.get("ok", True) else
            "\n\n**Some vectors are zero.** Those chunks can never be retrieved; "
            "rebuild the index.")
    # `collection`, not `table`: pass 27 put Milvus and LanceDB behind one
    # interface and the shared vocabulary is Milvus's. This line still said
    # `s['table']` after that change and took the whole Vector store tab down
    # with a KeyError - the cost of changing a dict's shape without grepping for
    # who reads it. `.get` everywhere below for the same reason.
    st = s.get("staleness") or {}
    if st.get("ok") is False:
        warn += ("\n\n**The index does not match the database.** "
                 + "; ".join(st.get("reasons", []))
                 + f"\n\n```\n{st.get('fix', '')}\n```")
    return (f"### Vector index\n\n"
            f"| | |\n|---|---|\n"
            f"| Store | **{s.get('backend', '?')}** ({s.get('mode', '?')}) |\n"
            f"| Location | `{s.get('uri', '?')}` / `{s.get('collection', '?')}` |\n"
            f"| Chunks | {s.get('rows')} |\n"
            f"| Dimensions | {s.get('dim')} |\n"
            f"| Built | {s.get('built_at', '—')} |\n"
            f"| Size | {size} |\n"
            f"| Health | {health} |\n"
            f"| Matches the database | "
            f"{'yes' if st.get('ok') else ('no' if st.get('ok') is False else '—')} |"
            f"{warn}")


def ui_review_chunks(ro, text, limit):
    from app.review import store as RS
    r = RS.chunks(ro_number=ro or None, text=text or None, limit=int(limit))
    if r.get("error"):
        return f"**{r['error']}**", pd.DataFrame()
    return (f"{r['returned']} of {r['total']} chunks",
            _df(r["rows"], ["update_id", "ro_number", "at", "staff_name",
                            "vehicle", "category", "text"], {"text": 150}))


def ui_review_chunk(update_id):
    """Load one chunk: what is indexed, what is on file, and its edit history."""
    from app.review import store as RS
    from app.retrieval import edit as E
    blank = ("Paste an update id from the table above.", {}, "", pd.DataFrame())
    if not update_id:
        return blank
    uid = update_id.strip()
    c = RS.chunk(uid)
    if c.get("error"):
        # Not in the index is not the same as not existing. An excluded chunk,
        # or one added since the last build, is still a real update.
        src = E.get_update(uid)
        if src:
            return (f"**Not in the index** — but the update is on file.\n\n"
                    f"**{src['ro_number']}** · {src['at']} · {src['staff_name']}\n\n"
                    f"> {src['text']}\n\n"
                    f"Use **Re-embed** to put it back into the index.",
                    src, src["text"], _df(E.history(uid),
                                          ["at", "kind", "actor_id"]))
        return f"**{c['error']}**", {}, "", pd.DataFrame()

    cb = RS.cited_by(uid)
    drift = ("" if c.get("matches_source", True) else
             "\n\n**This chunk's text differs from the update on file.** An edit "
             "was written but not re-embedded, so answers would quote wording "
             "that is not in the database. Press **Re-embed** to fix it.\n\n"
             f"On file: _{(c.get('source_text') or '')[:200]}_")
    lines = [f"### {c.get('update_id')}",
             f"**{c.get('ro_number')}** · {c.get('at')} · "
             f"{c.get('staff_name') or c.get('staff_id')} · {c.get('vehicle','')}",
             "", "> " + (c.get("text") or ""), "",
             f"Vector: {c.get('dim')} dimensions, norm {c.get('norm')}",
             f"First values: `{c.get('vector_preview')}`", ""]
    if cb.get("count"):
        lines.append(f"**Cited by {cb['count']} answer(s):**")
        lines += [f"- #{a['answer_id']} {a['at']} — {a['question']}"
                  for a in cb["answers"][:10]]
    else:
        lines.append("_No logged answer has cited this chunk yet._")
    lines.append(drift)
    hist = _df(E.history(uid), ["at", "kind", "actor_id"])
    return "\n".join(lines), c, (c.get("source_text") or c.get("text") or ""), hist


# --------------------------------------------------------------- editing
# Every one of these writes to the UPDATE and re-embeds. Nothing writes to the
# vector store alone: a chunk that disagrees with the record it cites is the one
# failure that produces confident, well-formed, fully "grounded" answers quoting
# text that is not on file. See app/retrieval/edit.py.

def _edit_result(r: dict, uid: str, done: str):
    """One status line plus a reloaded view, for every edit button.

    `done` is what actually happened. The first version said "Saved." for all
    four buttons, so excluding a chunk reported that the record and the index now
    agreed - which is true, and not what the button did.
    """
    if not r.get("ok"):
        status = f"**Not done.** {r.get('error')}"
    elif r.get("changed") is False:
        status = r.get("note", "Nothing changed.")
    else:
        status = f"**{done}**" + (f" {r['warning']}" if r.get("warning") else "")
    md, js, text, hist = ui_review_chunk(uid)
    return status, md, js, text, hist


def ui_chunk_save(update_id, new_text, actor):
    from app.retrieval import edit as E
    uid = (update_id or "").strip()
    if not uid:
        return "Load a chunk first.", "", {}, "", pd.DataFrame()
    return _edit_result(
        E.edit_text(uid, new_text or "", actor_id=(actor or "REVIEWER").strip()),
        uid, "Saved and re-embedded — the record and the index now agree.")


def ui_chunk_reindex(update_id):
    from app.retrieval import edit as E
    uid = (update_id or "").strip()
    if not uid:
        return "Load a chunk first.", "", {}, "", pd.DataFrame()
    r = E.reindex_one(uid)
    r.setdefault("changed", True)
    return _edit_result(r, uid, "Re-embedded from the record as it stands.")


def ui_chunk_exclude(update_id, reason, actor):
    from app.retrieval import edit as E
    uid = (update_id or "").strip()
    if not uid:
        return "Load a chunk first.", "", {}, "", pd.DataFrame()
    r = E.exclude(uid, reason=reason or "", actor_id=(actor or "REVIEWER").strip())
    return _edit_result(r, uid, "Removed from the index. The update is still "
                                "on file and can be restored.")


def ui_chunk_restore(update_id, actor):
    from app.retrieval import edit as E
    uid = (update_id or "").strip()
    if not uid:
        return "Load a chunk first.", "", {}, "", pd.DataFrame()
    r = E.restore(uid, actor_id=(actor or "REVIEWER").strip())
    return _edit_result(r, uid, "Back in the index and searchable again.")


def ui_edit_log():
    from app.retrieval import edit as E
    rows = []
    for r in E.recent_edits(200):
        p = r.get("payload") or {}
        rows.append({**r, "before": (p.get("before") or "")[:90],
                     "after": (p.get("after") or p.get("reason") or "")[:90]})
    return _df(rows, ["at", "kind", "update_id", "ro_number", "actor_id",
                      "before", "after"])


def ui_review_trace(query, retrieve_n, rerank_n, ro):
    from app.review import store as RS
    if not (query or "").strip():
        return ("Type a question. It runs the real embedding, the real vector "
                "search and the real reranker.", pd.DataFrame(), pd.DataFrame())
    t = RS.retrieval_trace(query, retrieve_n=int(retrieve_n), rerank_n=int(rerank_n),
                           ro_number=ro or None)
    if t.get("error"):
        return f"**{t['error']}**", pd.DataFrame(), pd.DataFrame()
    got = _df(t["retrieved"], ["rank", "vector_score", "update_id", "ro_number",
                               "at", "by", "text"], {"text": 130})
    rr = _df(t["reranked"], ["rank", "vector_rank", "moved", "rerank_score",
                             "update_id", "ro_number", "by", "text"], {"text": 130})
    if t.get("rerank_error"):
        head = (f"**The reranker failed:** {t['rerank_error']}. The right-hand "
                f"table is the vector order, untouched.")
    else:
        moved = [f"#{r['vector_rank']}→#{r['rank']}" for r in t["reranked"]
                 if r["moved"] != 0]
        dropped = [r["update_id"] for r in t["dropped"]]
        head = (f"Embedded in {t.get('embed_ms')} ms ({t.get('query_dim')} dims), "
                f"searched in {t.get('search_ms')} ms, reranked in "
                f"{t.get('rerank_ms')} ms.\n\n"
                f"**The reranker moved {len(moved)} of {len(t['reranked'])}**"
                + (f": {', '.join(moved)}. " if moved else ". ")
                + (f"It dropped {', '.join(dropped)}, which the vector search had "
                   f"in its top {len(t['reranked'])}."
                   if dropped else "It kept the vector order's top results.")
                + "\n\nThese six ids are exactly what `search_updates` would cite.")
    return head, got, rr


def ui_review_answers(which, limit):
    from app.review import store as RS
    g = {"all": None, "grounded": True, "ungrounded": False}[which]
    r = RS.answers(limit=int(limit), grounded=g)
    if r.get("error"):
        return f"**{r['error']}**", pd.DataFrame()
    return (f"{r['returned']} of {r['total']} logged answers",
            _df(r["answers"], ["answer_id", "at", "route", "composed", "grounded",
                               "seconds", "tools", "citations", "warnings",
                               "question", "answer"],
                {"question": 90, "answer": 140}))

def build() -> gr.Blocks:
    # A missing dataset used to show up as an empty dashboard rather than as a
    # message saying what to run. Generating one takes about a tenth of a second,
    # and this only fires when there is no data at all. ASOIA_AUTOGEN=0 disables it.
    from app.state.bootstrap import ensure_dataset
    ensure_dataset()
    with gr.Blocks(title="Service Operations Intelligence") as demo:
        gr.Markdown("# Automotive Service Operations Intelligence Agent\n"
                    "Voice and text shift updates → continuously derived repair-order state.")

        # ---------------------------------------------------- Dashboard
        with gr.Tab("Dashboard"):
            kpi = gr.HTML()
            with gr.Row():
                refresh = gr.Button("Refresh", variant="primary", scale=0)
                win = gr.Slider(1, 14, value=7, step=1, label="Pattern window (days)")

            act_note = gr.Markdown()
            act = gr.Dataframe(interactive=False, wrap=True)

            with gr.Accordion("All repair orders", open=False):
                filt = gr.Radio(FILTERS, value="active", label="Filter")
                shop_note = gr.Markdown()
                shop = gr.Dataframe(interactive=False, wrap=True)

            with gr.Accordion("Patterns across repair orders", open=False):
                patterns = gr.Markdown()

            with gr.Accordion("Technician activity", open=False):
                with gr.Row():
                    a_who = gr.Dropdown(_staff_choices(), label="Technician", filterable=True)
                    a_days = gr.Slider(1, 14, value=7, step=1, label="Days")
                a_out = gr.Markdown()
                a_who.change(ui_tech_activity, [a_who, a_days], a_out)
                a_days.release(ui_tech_activity, [a_who, a_days], a_out)

            dash_out = [kpi, act_note, act, shop_note, shop, patterns]
            refresh.click(ui_dashboard, [filt, win], dash_out)
            filt.change(ui_dashboard, [filt, win], dash_out)
            win.release(ui_dashboard, [filt, win], dash_out)
            demo.load(ui_dashboard, [filt, win], dash_out)

        # ---------------------------------------------------- Repair order
        with gr.Tab("Repair Order"):
            with gr.Row():
                ro = gr.Dropdown(_ro_choices("all"), label="Repair Order", filterable=True)
                rf = gr.Button("Refresh list", scale=0)
            detail = gr.Textbox(label="Derived state", lines=22, max_lines=30)
            hist = gr.Dataframe(label="Update history (as written)", interactive=False, wrap=True)
            ro.change(ui_ro_detail, ro, [detail, hist])
            rf.click(lambda: gr.update(choices=_ro_choices("all")), None, ro)

        # ---------------------------------------------------- Technician update
        with gr.Tab("Technician Update"):
            gr.Markdown("Log work against a repair order. What the RO already says is "
                        "shown below, so nothing gets logged twice or missed.")
            with gr.Row():
                t_ro = gr.Dropdown(_ro_choices("active"), label="Repair Order", filterable=True)
                t_who = gr.Dropdown(_staff_choices(), label="Technician", filterable=True)
            t_ctx = gr.Markdown("Select a repair order to see what is already logged "
                                "against it.")
            with gr.Row():
                t_done = gr.Dropdown(OP_CHOICES, label="Completed", multiselect=True, filterable=True)
                t_hrs = gr.Number(label="Actual hours", value=None)
            with gr.Row():
                t_pend = gr.Dropdown(OP_CHOICES, label="Still pending", multiselect=True, filterable=True)
                t_rec = gr.Dropdown(OP_CHOICES, label="Recommend (needs auth)", multiselect=True, filterable=True)
            with gr.Row():
                m_t = gr.Textbox(label="Measurement", placeholder="e.g. rotor_thickness")
                m_v = gr.Number(label="Value", value=None)
                m_m = gr.Number(label="Spec minimum", value=None)
            t_note = gr.Textbox(label="Note (free text)", lines=2)
            go = gr.Button("Submit structured update", variant="primary")
            card = gr.Textbox(label="What changed", lines=16)

            t_ro.change(ui_tech_context, t_ro, [t_ctx, t_done, t_pend, t_rec])
            go.click(ui_submit,
                     [t_ro, t_who, t_done, t_hrs, t_pend, t_rec, m_t, m_v, m_m, t_note],
                     card).then(ui_tech_context, t_ro, [t_ctx, t_done, t_pend, t_rec])

            gr.Markdown("---\n### Voice or free text\n"
                        "Speak or type the update as you would write it on the RO. "
                        "The transcript is always editable before it is applied.")
            with gr.Row():
                v_audio = gr.Audio(sources=["microphone", "upload"], type="filepath",
                                   label="Record or upload")
                with gr.Column():
                    v_btn = gr.Button("Transcribe")
                    v_status = gr.Markdown()
            v_text = gr.Textbox(label="Transcript / free-text update", lines=4,
                                placeholder="Type the update here, or press "
                                            "Transcribe to fill it from audio. "
                                            "Example: C/S grinding from the front "
                                            "under braking, front pads 1.8mm "
                                            "against a 3mm minimum...")
            v_go = gr.Button("Extract and apply", variant="primary")
            with gr.Row():
                v_card = gr.Textbox(label="What changed", lines=16)
                v_json = gr.Code(label="Extracted 3 C's structure", language="json")
            v_btn.click(ui_transcribe, v_audio, [v_text, v_status])
            v_go.click(ui_submit_nl, [t_ro, t_who, v_text], [v_card, v_json]) \
                .then(ui_tech_context, t_ro, [t_ctx, t_done, t_pend, t_rec])

        # ---------------------------------------------------- Handover
        with gr.Tab("Shift Handover"):
            sh = gr.Radio(["MORNING", "AFTERNOON"], value="AFTERNOON", label="Handing over to")
            hb = gr.Button("Generate handover", variant="primary")
            hout = gr.Textbox(label="Handover brief", lines=30, max_lines=40)
            hb.click(ui_handover, sh, hout)

        # ---------------------------------------------------- Assistant
        with gr.Tab("Manager Assistant"):
            gr.Markdown("Ask about the shop. Answers are built from tool results and "
                        "cite their sources. The assistant reports and advises - it "
                        "never authorises work, orders parts or closes a repair order.")
            chat = gr.Chatbot(label="Assistant")
            qbox = gr.Textbox(label="Question", placeholder="Which vehicles cannot be released on safety grounds?")
            with gr.Row():
                askb = gr.Button("Ask", variant="primary")
                clrb = gr.Button("Clear", scale=0)
            gr.Examples([
                "Which vehicles cannot be released on safety grounds?",
                "Give me the afternoon handover, worst first.",
                "Are any parts holding up more than one job at once?",
                "Which jobs will miss their promised time?",
                "What has EMP014 done this week?",
                "Who worked in the afternoon yesterday?",
                "Go ahead and order the parts for RO-26-08165",
            ], inputs=qbox, label="Try these (the last one is refused by the action rail)")
            askb.click(ui_ask, [qbox, chat], [chat, qbox])
            qbox.submit(ui_ask, [qbox, chat], [chat, qbox])
            clrb.click(lambda: ([], ""), None, [chat, qbox])

        with gr.Tab("Data & Retrieval"):
            gr.Markdown(
                "Everything an answer is built from, open to inspection: the event "
                "log, the fold that derives state from it, what is in the vector "
                "index, what retrieval actually did, and which chunks each answer "
                "cited. Read only — nothing on this tab changes anything.")

            with gr.Tab("Overview"):
                rv_over = gr.Markdown(ui_review_overview)
                gr.Button("Refresh").click(ui_review_overview, None, rv_over)

            with gr.Tab("Event log"):
                gr.Markdown("The append-only log. Nothing here is ever updated or "
                            "deleted — corrections arrive as later events.")
                with gr.Row():
                    ev_ro = gr.Textbox(label="Repair order", scale=2,
                                       placeholder="RO-26-08165")
                    ev_type = gr.Dropdown(label="Type", scale=2, value="all",
                                          choices=["all"] + [t.value for t in _EVENT_TYPES])
                    ev_actor = gr.Textbox(label="Actor", scale=2, placeholder="EMP014")
                    ev_hours = gr.Number(label="Last N hours", scale=1, value=None)
                    ev_limit = gr.Number(label="Limit", scale=1, value=200)
                ev_btn = gr.Button("Search the log", variant="primary")
                ev_count = gr.Markdown()
                ev_df = gr.Dataframe(wrap=True, max_height=460)
                gr.Markdown("#### Every type, and how often it occurs")
                ev_types = gr.Dataframe(value=ui_review_event_types, wrap=True)
                for _t in (ev_btn.click, ev_ro.submit, ev_actor.submit):
                    _t(ui_review_events, [ev_ro, ev_type, ev_actor, ev_hours, ev_limit],
                       [ev_count, ev_df])

            with gr.Tab("Fold"):
                gr.Markdown("State is derived, not stored. Pick a repair order and "
                            "see the events on the left and what they fold into on "
                            "the right.")
                fo_ro = gr.Dropdown(label="Repair order", choices=_ro_choices("all"),
                                    value=None, allow_custom_value=True)
                fo_md = gr.Markdown()
                with gr.Row():
                    fo_ev = gr.Dataframe(label="Events, in order", wrap=True,
                                         max_height=420, scale=3)
                    fo_snap = gr.JSON(label="Folded snapshot", scale=2)
                fo_up = gr.Dataframe(label="Technician updates on this repair order",
                                     wrap=True, max_height=260)
                fo_ro.change(ui_review_fold, fo_ro, [fo_md, fo_ev, fo_up, fo_snap])

            with gr.Tab("Vector store"):
                rv_idx = gr.Markdown(ui_review_index)
                gr.Button("Refresh index stats").click(ui_review_index, None, rv_idx)
                with gr.Row():
                    ch_ro = gr.Textbox(label="Repair order", scale=2)
                    ch_text = gr.Textbox(label="Text contains", scale=3,
                                         placeholder="brake")
                    ch_limit = gr.Number(label="Limit", scale=1, value=100)
                ch_btn = gr.Button("Browse chunks", variant="primary")
                ch_count = gr.Markdown()
                ch_df = gr.Dataframe(wrap=True, max_height=380)
                gr.Markdown("#### One chunk, in full — and editable")
                ch_id = gr.Textbox(label="Update id",
                                   placeholder="paste an update_id from the table")
                ch_md = gr.Markdown()
                with gr.Accordion("Edit this update", open=False):
                    gr.Markdown(
                        "Editing changes the **update on file** and re-embeds its "
                        "chunk, so the record and the index stay in step. Editing "
                        "the index alone would leave answers quoting text that is "
                        "not in the database — and nothing downstream would catch "
                        "it. Every change is kept, with its before and after.")
                    ch_edit = gr.Textbox(label="Update text", lines=6)
                    with gr.Row():
                        ch_actor = gr.Textbox(label="Your id", value="REVIEWER",
                                              scale=1)
                        ch_reason = gr.Textbox(label="Reason (for exclude)", scale=2)
                    with gr.Row():
                        ch_save = gr.Button("Save and re-embed", variant="primary")
                        ch_re = gr.Button("Re-embed only")
                        ch_excl = gr.Button("Exclude from index")
                        ch_rest = gr.Button("Restore to index")
                    ch_status = gr.Markdown()
                    ch_hist = gr.Dataframe(label="What has been changed here",
                                           wrap=True, max_height=200)
                ch_json = gr.JSON(label="The stored record")
                ch_btn.click(ui_review_chunks, [ch_ro, ch_text, ch_limit],
                             [ch_count, ch_df])
                ch_text.submit(ui_review_chunks, [ch_ro, ch_text, ch_limit],
                               [ch_count, ch_df])
                _load_out = [ch_md, ch_json, ch_edit, ch_hist]
                ch_id.submit(ui_review_chunk, ch_id, _load_out)
                ch_id.change(ui_review_chunk, ch_id, _load_out)
                _edit_out = [ch_status, ch_md, ch_json, ch_edit, ch_hist]
                ch_save.click(ui_chunk_save, [ch_id, ch_edit, ch_actor], _edit_out)
                ch_re.click(ui_chunk_reindex, ch_id, _edit_out)
                ch_excl.click(ui_chunk_exclude, [ch_id, ch_reason, ch_actor],
                              _edit_out)
                ch_rest.click(ui_chunk_restore, [ch_id, ch_actor], _edit_out)

            with gr.Tab("Edit log"):
                gr.Markdown(
                    "Every change made to an update through this screen, with what "
                    "it said before. Deliberately separate from the event log: a "
                    "data correction is not something that happened in the "
                    "workshop, and putting these in the lifecycle log breaks the "
                    "fold — which is exactly how it broke the first time.")
                el_df = gr.Dataframe(value=ui_edit_log, wrap=True, max_height=460)
                gr.Button("Refresh").click(ui_edit_log, None, el_df)

            with gr.Tab("Retrieval"):
                gr.Markdown(
                    "What retrieval actually did, both stages. The left table is "
                    "what the vector search returned; the right is what the "
                    "reranker did to it. `search_updates` returns only the right "
                    "one, so this is the only place the difference is visible.")
                with gr.Row():
                    tr_q = gr.Textbox(label="Query", scale=4,
                                      placeholder="has anyone seen this fault before")
                    tr_ro = gr.Textbox(label="Limit to RO", scale=1)
                    tr_n = gr.Slider(label="Retrieve", minimum=4, maximum=50,
                                     step=1, value=18, scale=1)
                    tr_k = gr.Slider(label="Keep", minimum=1, maximum=20,
                                     step=1, value=6, scale=1)
                tr_btn = gr.Button("Trace it", variant="primary")
                tr_md = gr.Markdown()
                with gr.Row():
                    tr_got = gr.Dataframe(label="1. Vector search", wrap=True,
                                          max_height=420)
                    tr_rr = gr.Dataframe(label="2. After reranking", wrap=True,
                                         max_height=420)
                gr.Examples(["grinding noise from the front under braking",
                             "intermittent electrical fault, no codes stored",
                             "part on back order, customer chasing"],
                            inputs=tr_q, label="Try these")
                for _t in (tr_btn.click, tr_q.submit):
                    _t(ui_review_trace, [tr_q, tr_n, tr_k, tr_ro],
                       [tr_md, tr_got, tr_rr])

            with gr.Tab("Answers"):
                gr.Markdown("Every answer the assistant has given, with the chunks "
                            "it cited and whether the grounding check passed. Set "
                            "`ASOIA_LOG_ANSWERS=0` to stop recording.")
                with gr.Row():
                    an_which = gr.Radio(["all", "grounded", "ungrounded"],
                                        value="all", label="Show", scale=2)
                    an_limit = gr.Number(label="Limit", value=100, scale=1)
                an_btn = gr.Button("Load", variant="primary")
                an_count = gr.Markdown()
                an_df = gr.Dataframe(wrap=True, max_height=460)
                an_btn.click(ui_review_answers, [an_which, an_limit],
                             [an_count, an_df])
                an_which.change(ui_review_answers, [an_which, an_limit],
                                [an_count, an_df])

    _warm_nims()
    from app.obs import metrics as _M
    _M.serve()
    return demo


if __name__ == "__main__":
    # SHARE=1 publishes a gradio.live URL and there is NO login in front of it.
    #
    # That is a deliberate decision, taken knowingly, and it is recorded here
    # rather than left to be discovered: anyone who has the URL can use every tab,
    # including Technician Update, which WRITES to the event log, and every model
    # call runs on this box's NVIDIA key. A random subdomain is not a credential.
    #
    # So treat a shared link as published: take it down with
    # `bash scripts/stack.sh down` when you are finished, and rotate the NVIDIA key
    # afterwards. The warning below is not a control, it is a reminder in the log
    # that this is how the process was started.
    _share = os.environ.get("SHARE", "0") == "1"
    if _share:
        print("[ui] SHARE=1 and NO login: anyone with the gradio.live URL can "
              "write to the event log and spend this box's NVIDIA key. Take the "
              "link down with `scripts/stack.sh down` when you are done.")
    build().launch(server_name="0.0.0.0",
                   server_port=int(os.environ.get("PORT", 7860)),
                   share=_share,
                   theme=gr.themes.Soft())
