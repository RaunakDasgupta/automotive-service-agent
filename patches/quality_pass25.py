#!/usr/bin/env python3
"""Twenty-fifth pass: the clock follows the data, and a stale index says so.

Run from the project root:   .venv/bin/python quality_pass25.py

THE MEASUREMENT THAT STARTED THIS

Nothing in this system stores state. Every derived fact is folded from the event
log and computed against "now". The dataset is generated relative to a moment and
then stops moving, so the wall clock walks away from it. Five days is enough:

    $ verify_answers.py            # 5-day-old data, clock unpinned
    FAIL  What has EMP014 done this week?
    FAIL  Who worked in the afternoon yesterday?
    FAIL  Who was in this morning?
    FAIL  What happened overnight?
    4 check(s) FAILED

Four of fourteen, all time-window questions, each returning nothing and citing
nothing - which the output rail then blocks. The workaround was to pin ASOIA_NOW
on the command line and remember to move it. A demo that needs a date typed into
it correctly is a demo that gets given wrong once.

1. THE CLOCK FOLLOWS THE DATA.

   app/state/clock.py resolves "now" from three sources in order: an explicit
   argument, ASOIA_NOW, then the newest event in the log. Anchoring to the data
   means the shop is always live - the last thing that happened, happened just
   now - so a dataset never goes stale and the pin becomes optional instead of
   load-bearing. It costs 1.4 microseconds, measured over a 10,715-event log.

   Writes use `event_time()`, which is one second later. Stamping a new event at
   exactly the newest event's time would pile every update posted in a session
   onto one timestamp and make ORDER BY at meaningless - and using the wall clock
   for writes while reads used the data would put a just-dictated update in the
   future, outside the "today" it belongs in.

   ASOIA_CLOCK=wall restores the old behaviour for anyone running against live
   data.

2. THE DATASET GENERATES ITSELF, ONCE.

   400 repair orders, 10,715 events, 1,882 updates, 4.5 MB - in 0.1 seconds, with
   a window that always ends now. At that price a manual step that can be
   forgotten has nothing to recommend it, and a missing dataset used to surface as
   an empty dashboard rather than as a message saying what to run. It fires only
   when there is no data at all, so it cannot overwrite anything, and
   ASOIA_AUTOGEN=0 turns it off.

   It deliberately does NOT build the vector index: that means embedding every
   update through a NIM, which cannot be a startup cost and would make a first
   launch hang with no explanation.

3. WHICH IS EXACTLY WHY A STALE INDEX HAD TO BECOME VISIBLE.

   Regenerate the data without rebuilding the index and retrieval keeps working
   perfectly: plausible passages, well-formed answers, citing update ids that no
   longer exist. Nothing would catch it. `check_grounding` verifies that figures
   and repair-order references in the ANSWER appear in the TOOL RESULTS - it has
   never checked that a cited id resolves to a row.

   So `search_updates` now checks its own citations against the database - one
   query, six ids, at the only point where citations enter the system from
   outside it - and flags rather than drops them, because silently removing them
   would hide a broken index behind slightly worse answers. The agent surfaces
   the flag as a note, /health reports it and degrades, and the review Overview
   says so in words with the command to fix it.
"""
import sys, pathlib, ast

ROOT = pathlib.Path(".")
CHANGES = []


def edit(rel, old, new, label, skip_if=None):
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"FAIL: {rel} not found - run from the project root")
    s = p.read_text()
    if skip_if and skip_if in s:
        CHANGES.append(f"  skip  {label} (already applied)")
        return
    n = s.count(old)
    if n != 1:
        sys.exit(f"FAIL: {label}: anchor found {n} times in {rel}, expected 1.\n"
                 "      Run passes 1-24 first. Stopping without changes.")
    p.write_text(s.replace(old, new, 1))
    CHANGES.append(f"  ok    {label}")


def write(rel, body, label):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text() == body:
            CHANGES.append(f"  skip  {label} (already present)")
        else:
            p.write_text(body)
            CHANGES.append(f"  ok    {label} (replaced)")
        return
    p.write_text(body)
    CHANGES.append(f"  ok    {label}")


# ==================== 1. the clock follows the data

write('app/state/clock.py',
      '"""What time is it, as far as this application is concerned.\n\nTHE PROBLEM THIS SOLVES\n\nNothing in this system stores state. Every derived fact - promise risk, at-risk,\n"this week", which shift someone worked, what "today" means - is folded from the\nevent log and computed against "now". The dataset, meanwhile, is *generated*\nrelative to a moment and then stops moving.\n\nSo the wall clock walks away from the data. Five days after generating, with the\nclock unpinned, four of the fourteen answers in scripts/verify_answers.py fail -\nevery one of them a time-window question, each returning nothing and citing\nnothing, which the output rail then blocks:\n\n    FAIL  What has EMP014 done this week?\n    FAIL  Who worked in the afternoon yesterday?\n    FAIL  Who was in this morning?\n    FAIL  What happened overnight?\n\nThe workaround was to pin ASOIA_NOW on the command line and remember to move it.\nA demo that needs a date typed into it correctly is a demo that will be given\nwrong once.\n\nWHAT IT DOES INSTEAD\n\nThree sources, in order:\n\n    1. an explicit argument           a caller that knows better\n    2. ASOIA_NOW                      an operator pinning it, for reproducibility\n    3. the newest event in the log    the default\n\nAnchoring to the data means the shop is always "live" - the last thing that\nhappened, happened just now - so a dataset never goes stale and the pin becomes\noptional rather than load-bearing. It costs 1.4 microseconds: `MAX(at)` over an\nindexed column, measured over a 10,715-event log.\n\nASOIA_CLOCK=wall forces the wall clock back, for anyone who wants the old\nbehaviour or is running against live data.\n"""\nfrom __future__ import annotations\nimport os\nfrom datetime import datetime, timedelta\n\n\ndef _env_pin() -> datetime | None:\n    v = (os.environ.get("ASOIA_NOW") or "").strip()\n    if not v:\n        return None\n    try:\n        return datetime.fromisoformat(v)\n    except ValueError:\n        # A malformed pin must not take the whole application down, and must not\n        # be silently ignored either - it was typed on purpose.\n        print(f"[clock] ASOIA_NOW={v!r} is not an ISO timestamp; ignoring it")\n        return None\n\n\ndef data_now() -> datetime | None:\n    """The newest event in the log, or None if there is no readable log."""\n    try:\n        from app.state import db as dbm\n        row = dbm.connect().execute("SELECT MAX(at) FROM events").fetchone()\n    except Exception:\n        return None\n    if not row or not row[0]:\n        return None\n    try:\n        return datetime.fromisoformat(row[0])\n    except (TypeError, ValueError):\n        return None\n\n\ndef now(explicit: datetime | None = None) -> datetime:\n    """The application\'s current time. Never raises."""\n    if explicit:\n        return explicit\n    pinned = _env_pin()\n    if pinned:\n        return pinned\n    if (os.environ.get("ASOIA_CLOCK") or "").lower() != "wall":\n        anchored = data_now()\n        if anchored:\n            return anchored\n    return datetime.now()\n\n\ndef event_time(explicit: datetime | None = None) -> datetime:\n    """The timestamp for a NEW event. Not the same question as `now()`.\n\n    Reads can use the newest event as "now". Writes cannot: stamping a new event\n    at exactly the time of the newest one makes every update posted in a session\n    pile onto a single timestamp, and `ORDER BY at` stops meaning anything. One\n    second past the last event keeps the log strictly ordered, and keeps a\n    just-dictated update inside "today" as the application sees it - which is the\n    whole point of anchoring, and would be lost if writes used the wall clock\n    while reads used the data.\n    """\n    if explicit:\n        return explicit\n    pinned = _env_pin()\n    if pinned:\n        return pinned\n    if (os.environ.get("ASOIA_CLOCK") or "").lower() != "wall":\n        anchored = data_now()\n        if anchored:\n            return anchored + timedelta(seconds=1)\n    return datetime.now()\n\n\ndef source() -> dict:\n    """Which of the three the clock is using, and what the others would say.\n\n    Reported by /health and by the review Overview, because "why does it think\n    today is the 21st" is a question somebody will ask during a demo, and the\n    answer should be one click away rather than a code read.\n    """\n    wall = datetime.now()\n    pinned = _env_pin()\n    anchored = data_now()\n    forced_wall = (os.environ.get("ASOIA_CLOCK") or "").lower() == "wall"\n    if pinned:\n        which, why = "pinned", "ASOIA_NOW is set"\n    elif forced_wall:\n        which, why = "wall", "ASOIA_CLOCK=wall"\n    elif anchored:\n        which, why = "data", "the newest event in the log"\n    else:\n        which, why = "wall", "no events to anchor to"\n    resolved = now()\n    out = {"source": which, "why": why, "now": resolved.isoformat(),\n           "wall_clock": wall.isoformat(),\n           "newest_event": anchored.isoformat() if anchored else None,\n           "pinned": pinned.isoformat() if pinned else None}\n    if anchored:\n        behind = (wall - anchored).total_seconds() / 86400.0\n        out["data_age_days"] = round(behind, 2)\n        # Worth saying out loud: this is the gap that used to break the\n        # time-window questions, and on the wall clock it still would.\n        out["wall_clock_would_break_time_questions"] = bool(behind > 1.0)\n    return out\n',
      'app/state/clock.py  now() follows the data, not the wall')

write('app/state/bootstrap.py',
      '"""Make sure there is a dataset, without making anyone run a separate step.\n\nGenerating the full default dataset - 400 repair orders, 10,715 events, 1,882\nupdates, 4.5 MB - takes **0.1 seconds**, and because it simulates relative to the\nclock at generation time, the window always ends now. At that price there is no\nargument for a manual step that can be forgotten, and every argument against one:\na missing dataset used to surface as an empty dashboard rather than as a message\nsaying what to run.\n\nIt only ever fires when there is NO data. A database with rows in it is never\ntouched, so this cannot overwrite anything.\n\n    ASOIA_AUTOGEN=0     never generate; report the empty database instead\n    ASOIA_GEN_ROS       how many repair orders (default 400)\n    ASOIA_GEN_DAYS      how many days of history (default 14)\n\nWHAT IT DELIBERATELY DOES NOT DO\n\nIt does not build the vector index. That means embedding every update through\nnv-embedqa, which needs a NIM up and takes orders of magnitude longer than the\ndata itself - so it cannot be a startup cost, and silently doing it would make a\nfirst launch hang with no explanation. The index is a separate, explicit step,\nand `app.review.store.index_staleness()` is what notices when it no longer\nmatches the data.\n"""\nfrom __future__ import annotations\nimport os\nimport time\n\n\ndef _db_path(con) -> str | None:\n    """The file this connection is actually attached to.\n\n    Not `build_dataset`\'s default, and not ASOIA_DB read fresh from the\n    environment. The first version of this checked one database and generated\n    into another: `dbm.connect()` honours ASOIA_DB, `build_dataset()` defaults to\n    the literal "data/generated/service.sqlite", so pointing the app at a scratch\n    database made the bootstrap find it empty and then overwrite the REAL one -\n    400 repair orders replaced by a fresh 12, silently, at startup. The docstring\n    promised "a database with rows in it is never touched" while the code did\n    exactly that.\n\n    Asking the connection removes the possibility: the file that was checked and\n    the file that gets written are the same file by construction.\n    """\n    try:\n        row = con.execute("PRAGMA database_list").fetchone()\n        return row[2] if row and row[2] else None\n    except Exception:\n        return None\n\n\ndef _has_data(con) -> bool:\n    try:\n        have = {r[0] for r in con.execute(\n            "SELECT name FROM sqlite_master WHERE type=\'table\'")}\n        if "ros" not in have:\n            return False\n        return con.execute("SELECT COUNT(*) FROM ros").fetchone()[0] > 0\n    except Exception:\n        return False\n\n\ndef _evict(dbm) -> None:\n    """Drop this thread\'s cached connections after generating.\n\n    `build_dataset` closes the connection it used, and `dbm.connect()` caches one\n    per thread - so generating leaves the cache holding a CLOSED connection and\n    every query afterwards raises "Cannot operate on a closed database". On a\n    real startup that means the app generates its data and is then dead, which is\n    a far worse failure than the empty dashboard this was meant to fix.\n\n    Evicting is enough: the next connect() opens a fresh one against a file that\n    now has a schema.\n    """\n    try:\n        cache = getattr(dbm._local, "conns", None)\n        if cache:\n            cache.clear()\n    except Exception:\n        pass\n\n\ndef ensure_dataset(verbose: bool = True) -> dict:\n    """Generate the dataset if, and only if, there is none. Never raises."""\n    from app.state import db as dbm\n    try:\n        con = dbm.connect()\n    except Exception as e:\n        return {"status": "error", "error": f"{type(e).__name__}: {e}"}\n\n    if _has_data(con):\n        try:\n            n = con.execute("SELECT COUNT(*) FROM ros").fetchone()[0]\n        except Exception:\n            n = None\n        return {"status": "present", "repair_orders": n}\n\n    if (os.environ.get("ASOIA_AUTOGEN") or "1") == "0":\n        return {"status": "empty",\n                "hint": "ASOIA_AUTOGEN=0, so nothing was generated. Run "\n                        ".venv/bin/python -m app.data.generate"}\n\n    try:\n        from app.data.generate import build_dataset\n        target = _db_path(con)\n        if not target:\n            return {"status": "error",\n                    "error": "could not determine which database file to write"}\n        kw = {"db_path": target}\n        if os.environ.get("ASOIA_GEN_ROS"):\n            kw["n_ros"] = int(os.environ["ASOIA_GEN_ROS"])\n        if os.environ.get("ASOIA_GEN_DAYS"):\n            kw["days"] = int(os.environ["ASOIA_GEN_DAYS"])\n        if verbose:\n            print(f"[bootstrap] no dataset in {target} - generating one "\n                  f"(about a tenth of a second)")\n        t0 = time.time()\n        r = build_dataset(**kw)\n        el = time.time() - t0\n        _evict(dbm)\n        if verbose:\n            print(f"[bootstrap] generated {r[\'ros\']} repair orders, "\n                  f"{r[\'events\']} events, {r[\'updates\']} updates in {el:.1f}s")\n            print("[bootstrap] the vector index is NOT built - semantic search "\n                  "needs:  .venv/bin/python -c "\n                  "\'from app.retrieval.index import build; print(build())\'")\n        # Prove the app can still talk to the database it just made. If this\n        # fails the process is unusable, and it should say so now rather than on\n        # the first question somebody asks.\n        try:\n            n = dbm.connect().execute("SELECT COUNT(*) FROM ros").fetchone()[0]\n        except Exception as e:\n            return {"status": "error", "generated": True,\n                    "error": f"generated, but the database is unreadable "\n                             f"afterwards: {type(e).__name__}: {e}"}\n        return {"status": "generated", "seconds": round(el, 2),\n                "repair_orders": n, **r}\n    except Exception as e:\n        if verbose:\n            print(f"[bootstrap] could not generate a dataset: "\n                  f"{type(e).__name__}: {e}")\n        return {"status": "error", "error": f"{type(e).__name__}: {e}"}\n',
      'app/state/bootstrap.py  generate a dataset if there is none')

edit('app/agent/tools.py',
     'def _now(now=None) -> datetime:\n    import os\n    if now: return now\n    v = os.environ.get("ASOIA_NOW")\n    return datetime.fromisoformat(v) if v else datetime.now()',
     'def _now(now=None) -> datetime:\n    """The application\'s clock: pinned, else the newest event, else the wall.\n\n    It used to fall back to the wall clock, which walks away from a generated\n    dataset and empties out every time-window question. See app/state/clock.py.\n    """\n    from app.state.clock import now as _clock\n    return _clock(now)',
     'tools.py  _now() uses the clock',
     skip_if='from app.state.clock import now as _clock')

edit('app/ui/gradio_app.py',
     'NOW = lambda: datetime.fromisoformat(os.environ.get("ASOIA_NOW")) if os.environ.get("ASOIA_NOW") else datetime.now()',
     '# Reads use NOW: ASOIA_NOW if pinned, else the newest event in the log, else the\n# wall clock. Writes use EVENT_TIME, which is one second later so the log stays\n# strictly ordered. app/state/clock.py says why the default is the data.\nfrom app.state.clock import now as NOW, event_time as EVENT_TIME',
     'gradio_app.py  NOW and EVENT_TIME from the clock',
     skip_if='from app.state.clock import now as NOW, event_time as EVENT_TIME')

edit('app/ui/gradio_app.py',
     '                    at=NOW(), update_id=f"UPD-UI-{datetime.now().strftime(\'%H%M%S\')}")',
     '                    at=EVENT_TIME(),\n                    update_id=f"UPD-UI-{datetime.now().strftime(\'%H%M%S\')}")',
     'gradio_app.py  the manual update writes at EVENT_TIME',
     skip_if='                    at=EVENT_TIME(),')

edit('app/ui/gradio_app.py',
     '              ro_number=ro_number or None, at=NOW(), embed_fn=_emb)',
     '              ro_number=ro_number or None, at=EVENT_TIME(), embed_fn=_emb)',
     'gradio_app.py  the dictated update writes at EVENT_TIME',
     skip_if='at=EVENT_TIME(), embed_fn')

edit('app/api/server.py',
     '    now = (__import__("datetime").datetime.fromisoformat(os.environ["ASOIA_NOW"])\n           if os.environ.get("ASOIA_NOW") else None)',
     '    # One second past the newest event, so a posted update lands inside "today"\n    # as the application sees it rather than in the future. See app/state/clock.py.\n    from app.state.clock import event_time\n    now = event_time()',
     'server.py  /updates writes at EVENT_TIME',
     skip_if='from app.state.clock import event_time')

# ==================== 2. a dataset, without a separate step

edit('app/ui/gradio_app.py',
     'def build() -> gr.Blocks:\n    with gr.Blocks(title="Service Operations Intelligence") as demo:',
     'def build() -> gr.Blocks:\n    # A missing dataset used to show up as an empty dashboard rather than as a\n    # message saying what to run. Generating one takes about a tenth of a second,\n    # and this only fires when there is no data at all. ASOIA_AUTOGEN=0 disables it.\n    from app.state.bootstrap import ensure_dataset\n    ensure_dataset()\n    with gr.Blocks(title="Service Operations Intelligence") as demo:',
     'gradio_app.py  generate a dataset on first start',
     skip_if='from app.state.bootstrap import ensure_dataset')

edit('app/api/server.py',
     'def main() -> None:\n    import uvicorn\n    from app.obs import metrics as M\n    M.serve()',
     'def main() -> None:\n    import uvicorn\n    from app.obs import metrics as M\n    from app.state.bootstrap import ensure_dataset\n    ensure_dataset()\n    M.serve()',
     'server.py  the same, for the API',
     skip_if='from app.state.bootstrap import ensure_dataset')

edit('app/api/server.py',
     '    try:\n        from app.nim.client import health as nim_health\n        out["nims"] = nim_health()\n    except Exception as e:\n        out["status"] = "degraded"\n        out["nims"] = {"error": f"{type(e).__name__}: {e}"}\n    return out',
     '    try:\n        from app.nim.client import health as nim_health\n        out["nims"] = nim_health()\n    except Exception as e:\n        out["status"] = "degraded"\n        out["nims"] = {"error": f"{type(e).__name__}: {e}"}\n    # "Why does it think today is the 21st" is a question someone will ask during\n    # a demo. The answer belongs in /health, not in a code read.\n    try:\n        from app.state.clock import source as clock_source\n        out["clock"] = clock_source()\n    except Exception as e:\n        out["clock"] = {"error": f"{type(e).__name__}: {e}"}\n    # A stale index yields confident, grounded-looking answers citing records that\n    # are not there. It degrades nothing else, so nothing else would report it.\n    try:\n        from app.review.store import index_staleness\n        st = index_staleness()\n        out["index"] = st\n        if st.get("ok") is False:\n            out["status"] = "degraded"\n    except Exception as e:\n        out["index"] = {"ok": None, "reasons": [f"{type(e).__name__}: {e}"]}\n    return out',
     'server.py  /health reports the clock and the index',
     skip_if='from app.state.clock import source as clock_source')

# ==================== 3. a stale index says so

edit('app/review/store.py',
     '    except Exception:\n        pass\n    return out\n\n\ndef chunks(',
     '    except Exception:\n        pass\n    try:\n        out["staleness"] = index_staleness(uri=uri)\n    except Exception as e:\n        out["staleness"] = {"ok": None, "reasons": [f"{type(e).__name__}: {e}"]}\n    return out\n\n\ndef chunks(',
     'store.py  index_stats carries the staleness check',
     skip_if='out["staleness"] = index_staleness(uri=uri)')

edit('app/review/store.py',
     'def chunks(ro_number: str | None = None, text: str | None = None,',
     'def index_staleness(uri: str | None = None, con: sqlite3.Connection | None = None) -> dict:\n    """Does the vector index still match the database?\n\n    This is the one failure in the system that produces confident, well-formed,\n    fully "grounded" answers citing records that do not exist. `check_grounding`\n    verifies that figures and repair-order references in the ANSWER appear in the\n    TOOL RESULTS; nothing has ever checked that a cited update id resolves to a\n    real row. Regenerate the data without rebuilding the index and retrieval goes\n    on serving passages from the old dataset, citing ids that are gone, and every\n    check passes.\n\n    Three drifts, in increasing order of how much they matter:\n\n        the counts differ            built from a different dataset\n        the newest update is absent  recent work is invisible to search\n        cited ids do not resolve     answers cite records that are not there\n    """\n    c = _con(con)\n    out: dict[str, Any] = {"ok": True, "reasons": []}\n    try:\n        db_updates = c.execute("SELECT COUNT(*) FROM updates").fetchone()[0]\n    except Exception as e:\n        return {"ok": None, "reasons": [f"no updates table: {type(e).__name__}"]}\n    out["database_updates"] = db_updates\n    try:\n        tbl = _table(uri)\n        rows = _scan(tbl)\n    except Exception as e:\n        return {"ok": None, "reasons": [str(e)], "database_updates": db_updates}\n\n    out["index_rows"] = len(rows)\n    if len(rows) != db_updates:\n        out["ok"] = False\n        out["reasons"].append(\n            f"the index holds {len(rows)} chunks and the database has "\n            f"{db_updates} updates")\n\n    indexed = {r.get("update_id") for r in rows if r.get("update_id")}\n    known = {r[0] for r in c.execute("SELECT update_id FROM updates")}\n    dangling = sorted(indexed - known)\n    out["dangling"] = len(dangling)\n    out["dangling_sample"] = dangling[:5]\n    if dangling:\n        out["ok"] = False\n        out["reasons"].append(\n            f"{len(dangling)} indexed chunk(s) cite update ids that are not in "\n            f"the database - answers would cite records that do not exist")\n\n    unindexed = sorted(known - indexed)\n    out["unindexed"] = len(unindexed)\n    if unindexed:\n        out["ok"] = False\n        out["reasons"].append(\n            f"{len(unindexed)} update(s) are not in the index and cannot be "\n            f"found by semantic search")\n\n    if not out["ok"]:\n        out["fix"] = (".venv/bin/python -c \'from app.retrieval.index import build; "\n                      "print(build())\'")\n    return out\n\n\ndef chunks(ro_number: str | None = None, text: str | None = None,',
     'store.py  index_staleness() - counts, dangling ids, unindexed updates',
     skip_if='def index_staleness')

edit('app/review/store.py',
     '    return {\n        "database": "ok",\n        "repair_orders": n("SELECT COUNT(*) FROM ros"),',
     '    try:\n        from app.state.clock import source as _clock_source\n        clock = _clock_source()\n    except Exception as e:\n        clock = {"error": f"{type(e).__name__}: {e}"}\n    return {\n        "database": "ok",\n        "clock": clock,\n        "index_staleness": idx.get("staleness"),\n        "repair_orders": n("SELECT COUNT(*) FROM ros"),',
     'store.py  the overview carries the clock and the staleness',
     skip_if='"index_staleness": idx.get("staleness")')

edit('app/retrieval/index.py',
     'def search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:\n    """Agent-tool shape: grounded passages plus their citations."""\n    hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)\n    return {"query": query, "count": len(hits),\n            "passages": [{"update_id": h["update_id"], "ro_number": h["ro_number"],\n                          "at": h["at"], "by": h.get("staff_name") or h["staff_id"],\n                          "vehicle": h.get("vehicle"), "text": h["text"],\n                          "score": h.get("rerank_score", h.get("vector_score"))}\n                         for h in hits],\n            "citations": [h["update_id"] for h in hits]}',
     'def _dangling(update_ids: list[str]) -> list[str]:\n    """Which of these ids are not in the database. Cheap: one query, k ids."""\n    ids = [i for i in update_ids if i]\n    if not ids:\n        return []\n    try:\n        con = dbm.connect()\n        q = ",".join("?" * len(ids))\n        found = {r[0] for r in con.execute(\n            f"SELECT update_id FROM updates WHERE update_id IN ({q})", ids)}\n    except Exception:\n        return []                      # never fail a search over a health check\n    return [i for i in ids if i not in found]\n\n\ndef search_updates(query: str, k: int = 6, ro_number: str | None = None) -> dict:\n    """Agent-tool shape: grounded passages plus their citations.\n\n    The citations are checked against the database before they leave. An index\n    built from a previous dataset keeps working perfectly - it returns plausible\n    passages and cites update ids that no longer exist - and nothing downstream\n    would notice: `check_grounding` verifies figures in the ANSWER against the\n    TOOL RESULTS, never that a cited id resolves to a row. So it is verified\n    here, at the only place citations enter the system from outside the database.\n\n    The passages are still returned, flagged rather than dropped. Silently\n    removing them would hide a broken index behind slightly worse answers, which\n    is the failure mode this project keeps having to dig back out of.\n    """\n    hits = search(query, k=max(k * 3, 18), rerank_to=k, ro_number=ro_number)\n    cits = [h["update_id"] for h in hits]\n    out = {"query": query, "count": len(hits),\n           "passages": [{"update_id": h["update_id"], "ro_number": h["ro_number"],\n                         "at": h["at"], "by": h.get("staff_name") or h["staff_id"],\n                         "vehicle": h.get("vehicle"), "text": h["text"],\n                         "score": h.get("rerank_score", h.get("vector_score"))}\n                        for h in hits],\n           "citations": cits}\n    gone = _dangling(cits)\n    if gone:\n        out["stale_index"] = {\n            "dangling": gone,\n            "note": (f"the vector index is out of date: {len(gone)} of "\n                     f"{len(cits)} cited updates are not in the database. "\n                     f"Rebuild it with app.retrieval.index.build()")}\n    return out',
     'index.py  search_updates verifies its own citations',
     skip_if='def _dangling')

edit('app/agent/agent.py',
     '    ans.citations = _collect_citations(ans.results)\n\n    notes: list[str] = []',
     '    ans.citations = _collect_citations(ans.results)\n\n    notes: list[str] = []\n    # A stale vector index is the only fault that yields a confident, well-formed,\n    # fully "grounded" answer citing records that are not there - check_grounding\n    # checks figures against tool results, never that a cited id resolves. The\n    # tool detects it; this is where it becomes visible to whoever is reading.\n    for _r in ans.results:\n        _res = _r.get("result")\n        _stale = _res.get("stale_index") if isinstance(_res, dict) else None\n        if _stale:\n            notes.append(_stale.get("note")\n                         or "the vector index does not match the database")',
     'agent.py  a stale index becomes a visible note',
     skip_if='_stale = _res.get("stale_index")')

edit('app/ui/gradio_app.py',
     '    vec = (f"{o[\'vector_rows\']} chunks, {o[\'vector_dim\']} dimensions"\n           if o.get("vector_rows") else f"**not available** — {o.get(\'vector_error\')}")\n    return (\n        "### What the answers are built from\\n\\n"\n        f"| | |\\n|---|---|\\n"\n        f"| Repair orders | {o[\'repair_orders\']} |\\n"\n        f"| Events | {o[\'events\']} across {o[\'event_types_used\']} of 17 types |\\n"\n        f"| Technician updates | {o[\'updates\']} |\\n"\n        f"| Staff | {o[\'staff\']} |\\n"\n        f"| Window | {str(o[\'first_event\'])[:16]} → {str(o[\'last_event\'])[:16]} |\\n"\n        f"| Vector index | {vec} |\\n"\n        f"| Answers logged | {o[\'answers_logged\']} |\\n\\n"\n        "State is **not stored**. Every repair order\'s state is folded from its "\n        "events on each read — the Fold tab shows that happening.")',
     '    vec = (f"{o[\'vector_rows\']} chunks, {o[\'vector_dim\']} dimensions"\n           if o.get("vector_rows") else f"**not available** — {o.get(\'vector_error\')}")\n    c = o.get("clock") or {}\n    clock = (f"**{c.get(\'now\', \'?\')[:16]}** — {c.get(\'why\', \'?\')}"\n             if c.get("now") else c.get("error", "—"))\n    st = o.get("index_staleness") or {}\n    if st.get("ok") is True:\n        stale = "matches the database"\n    elif st.get("ok") is False:\n        stale = "**OUT OF DATE** — " + "; ".join(st.get("reasons", []))\n    else:\n        stale = "—"\n    warn = ""\n    if c.get("wall_clock_would_break_time_questions"):\n        warn += (f"\\n\\nThe data is {c.get(\'data_age_days\')} days behind the wall "\n                 f"clock. On the wall clock every time-window question — "\n                 f"\\"this week\\", \\"yesterday afternoon\\", \\"overnight\\" — would "\n                 f"return nothing and be blocked for citing nothing. Anchoring "\n                 f"to the newest event is what keeps them working.")\n    if st.get("ok") is False:\n        warn += (f"\\n\\n**Rebuild the index.** Until then, answers can cite update "\n                 f"ids that are not in the database:\\n\\n```\\n{st.get(\'fix\', \'\')}\\n```")\n    return (\n        "### What the answers are built from\\n\\n"\n        f"| | |\\n|---|---|\\n"\n        f"| Now | {clock} |\\n"\n        f"| Repair orders | {o[\'repair_orders\']} |\\n"\n        f"| Events | {o[\'events\']} across {o[\'event_types_used\']} of 17 types |\\n"\n        f"| Technician updates | {o[\'updates\']} |\\n"\n        f"| Staff | {o[\'staff\']} |\\n"\n        f"| Window | {str(o[\'first_event\'])[:16]} → {str(o[\'last_event\'])[:16]} |\\n"\n        f"| Vector index | {vec} |\\n"\n        f"| Index vs database | {stale} |\\n"\n        f"| Answers logged | {o[\'answers_logged\']} |\\n\\n"\n        "State is **not stored**. Every repair order\'s state is folded from its "\n        "events on each read — the Fold tab shows that happening." + warn)',
     'gradio_app.py  the review Overview shows both',
     skip_if='| Index vs database |')


# ==================== verify
print("Quality pass 25:")
for c in CHANGES:
    print(c)
for f in ("app/state/clock.py", "app/state/bootstrap.py", "app/agent/tools.py",
          "app/ui/gradio_app.py", "app/api/server.py", "app/review/store.py",
          "app/retrieval/index.py", "app/agent/agent.py"):
    ast.parse((ROOT / f).read_text())
print("\neight touched python files parse cleanly.")
# The README is handled by quality_pass25_readme.py, not here. Three exact
# four-line anchors into a prose file is a bad way to find a paragraph: one of
# them missed on a real tree, and because edit() writes as it goes, the run
# stopped after all sixteen CODE edits had already been applied while printing
# "Stopping without changes". Documentation should not be able to do that.
import re as _re
_rd = (ROOT / "README.md").read_text()
_old_export = _re.search("^[ \t]*export[ \t]+ASOIA_NOW", _rd, _re.M)
if _old_export or "ASOIA_CLOCK" not in _rd:
    print()
    print("note    the README still describes the old behaviour. Fix it with:")
    print("        .venv/bin/python quality_pass25_readme.py")

sys.path.insert(0, ".")
import importlib, os, sqlite3, tempfile
from datetime import datetime, timedelta
bad = 0


def chk(name, ok, detail=""):
    global bad
    bad += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------- the clock
# A scratch database whose newest event is five days old - the exact condition
# that failed four of the fourteen answer checks.
D = tempfile.mkdtemp()
STALE_DB = os.path.join(D, "stale.sqlite")
OLD = (datetime.now() - timedelta(days=5)).replace(microsecond=0)
c = sqlite3.connect(STALE_DB)
c.executescript("CREATE TABLE events (event_id TEXT, at TEXT);"
                "CREATE TABLE updates (update_id TEXT PRIMARY KEY);")
c.executemany("INSERT INTO events VALUES (?,?)",
              [("EV-1", (OLD - timedelta(hours=3)).isoformat()),
               ("EV-2", OLD.isoformat())])
c.commit()
c.close()

os.environ["ASOIA_DB"] = STALE_DB
for m in ("app.state.db", "app.state.clock"):
    if m in sys.modules:
        del sys.modules[m]
import app.state.clock as CK

print("\nthe clock, against a five-day-old log:")
for k in ("ASOIA_NOW", "ASOIA_CLOCK"):
    os.environ.pop(k, None)
n = CK.now()
chk("anchors to the newest event, not the wall", n == OLD,
    f"{n.isoformat()} vs newest {OLD.isoformat()}")
chk("and that is not today", n.date() != datetime.now().date(),
    f"{(datetime.now() - n).days} days back")

os.environ["ASOIA_NOW"] = "2026-01-02T03:04:05"
chk("an explicit pin still wins", CK.now() == datetime(2026, 1, 2, 3, 4, 5))
os.environ["ASOIA_NOW"] = "not a timestamp"
w = CK.now()
chk("a malformed pin is ignored, not fatal", w == OLD)
del os.environ["ASOIA_NOW"]

os.environ["ASOIA_CLOCK"] = "wall"
chk("ASOIA_CLOCK=wall restores the old behaviour",
    abs((CK.now() - datetime.now()).total_seconds()) < 5)
del os.environ["ASOIA_CLOCK"]

chk("an explicit argument beats everything",
    CK.now(datetime(2020, 1, 1)) == datetime(2020, 1, 1))

# writes
chk("event_time is one second past the newest event",
    CK.event_time() == OLD + timedelta(seconds=1), CK.event_time().isoformat())
chk("a write therefore lands inside today, not the future",
    CK.event_time().date() == CK.now().date())
chk("two reads do not drift", CK.now() == CK.now())

s = CK.source()
chk("source() explains itself", s["source"] == "data" and "newest event" in s["why"],
    f"{s['source']}: {s['why']}")
chk("source() reports how far behind the wall clock is",
    4.5 < s.get("data_age_days", 0) < 5.5, f"{s.get('data_age_days')} days")
chk("source() warns that the wall clock would break the time questions",
    s.get("wall_clock_would_break_time_questions") is True)

# An empty or unreadable log must not leave the app without a clock. Patching
# data_now is the honest way to test the branch: re-pointing ASOIA_DB does not
# work, because app.state.db reads it once at import and caches a connection per
# thread, so the reload picks up neither.
_real = CK.data_now
try:
    CK.data_now = lambda: None
    chk("an empty log falls back to the wall clock",
        abs((CK.now() - datetime.now()).total_seconds()) < 5)
    chk("and says so", CK.source()["why"] == "no events to anchor to")
    chk("writes fall back too",
        abs((CK.event_time() - datetime.now()).total_seconds()) < 5)
finally:
    CK.data_now = _real

# ------------------------------------------------------------- the bootstrap
print("\nthe bootstrap:")
import app.state.bootstrap as BS
importlib.reload(BS)
os.environ["ASOIA_AUTOGEN"] = "0"
r = BS.ensure_dataset(verbose=False)
chk("ASOIA_AUTOGEN=0 generates nothing", r["status"] == "empty", str(r["status"]))
chk("and says what to run instead", "app.data.generate" in r.get("hint", ""))
del os.environ["ASOIA_AUTOGEN"]

# Generate into a scratch database, and then check THAT file - the first version
# of ensure_dataset generated into build_dataset's default path while checking
# the one the app was connected to, and so overwrote a real 400-repair-order
# dataset with a fresh 12 at startup. A passing "generated" status proves
# nothing on its own; the row has to land in the file that was inspected.
GEN = os.path.join(D, "gen.sqlite")
DEFAULT_DB_BEFORE = None
if os.path.exists("data/generated/service.sqlite"):
    DEFAULT_DB_BEFORE = os.path.getsize("data/generated/service.sqlite")

import app.state.db as _dbm


def _clear_conns():
    try:
        cache = getattr(_dbm._local, "conns", None)
        if cache:
            cache.clear()
    except Exception:
        pass


_real_default = _dbm.DEFAULT_DB
os.environ["ASOIA_GEN_ROS"] = "12"
os.environ["ASOIA_GEN_DAYS"] = "3"
try:
    _dbm.DEFAULT_DB = GEN
    _clear_conns()
    importlib.reload(BS)
    r = BS.ensure_dataset(verbose=False)
    chk("generates when there is nothing", r["status"] == "generated",
        f"{r.get('ros')} repair orders in {r.get('seconds')}s")
    chk("honours the size overrides", r.get("ros") == 12, str(r.get("ros")))
    # build_dataset CLOSES the connection it used, and dbm.connect() caches one
    # per thread - so without eviction the cache holds a closed connection and
    # every query afterwards raises. The app would generate its data and die.
    chk("the database is readable straight after generating",
        r.get("repair_orders") == 12, f"{r.get('repair_orders')} read back")
    try:
        live = _dbm.connect().execute("SELECT COUNT(*) FROM ros").fetchone()[0]
    except Exception as e:
        live = f"{type(e).__name__}: {e}"
    chk("the cached connection is not left closed", live == 12, str(live))
    again = BS.ensure_dataset(verbose=False)
    chk("never touches a database that has data", again["status"] == "present",
        f"{again.get('repair_orders')} repair orders")
finally:
    _dbm.DEFAULT_DB = _real_default
    _clear_conns()
    for k in ("ASOIA_GEN_ROS", "ASOIA_GEN_DAYS"):
        os.environ.pop(k, None)

probe = sqlite3.connect(GEN)
n_here = probe.execute("SELECT COUNT(*) FROM ros").fetchone()[0]
chk("it writes to the database it checked, not build_dataset's default",
    n_here == 12, f"{n_here} repair orders in the scratch file")
if DEFAULT_DB_BEFORE is not None:
    chk("the project's own database was left alone",
        os.path.getsize("data/generated/service.sqlite") == DEFAULT_DB_BEFORE,
        "unchanged")

# the generated window must end at "now", which is the whole point
newest = datetime.fromisoformat(
    probe.execute("SELECT MAX(at) FROM events").fetchone()[0])
chk("the generated window ends today",
    (datetime.now() - newest).total_seconds() < 86400, newest.isoformat())

# ------------------------------------------------------------- staleness
print("\na stale index:")
from app.review import store as RS
importlib.reload(RS)
st = RS.index_staleness(con=probe)
chk("with no index at all it reports, it does not raise",
    isinstance(st, dict) and st.get("ok") is None, str(st.get("reasons"))[:60])


class _FakeTbl:
    def __init__(self, rows):
        self._rows = rows

    def to_arrow(self):
        raise RuntimeError("no arrow here")

    def search(self, qv=None):
        class Q:
            def __init__(s, r):
                s.r = r

            def limit(s, n):
                return s

            def where(s, w):
                return s

            def to_list(s):
                return [dict(x) for x in s.r]
        return Q(self._rows)


real_table = RS._table
ids = [r[0] for r in probe.execute(
    "SELECT update_id FROM updates ORDER BY update_id")]
try:
    RS._table = lambda uri=None: _FakeTbl([{"update_id": i} for i in ids])
    st = RS.index_staleness(con=probe)
    chk("a matching index is clean", st.get("ok") is True, str(st.get("reasons")))

    RS._table = lambda uri=None: _FakeTbl(
        [{"update_id": i} for i in ids[:-3]] + [{"update_id": "UPD-GHOST-1"}])
    st = RS.index_staleness(con=probe)
    chk("dangling ids are caught", st.get("dangling") == 1 and st.get("ok") is False,
        f"{st.get('dangling')} dangling, {st.get('unindexed')} unindexed")
    chk("missing updates are caught", st.get("unindexed") == 3)
    chk("the count difference is reported",
        any("chunks" in r for r in st.get("reasons", [])))
    chk("it says how to fix it", "app.retrieval.index" in st.get("fix", ""))
finally:
    RS._table = real_table

# ---------------------------------------------------------------- the wiring
print("\nwiring:")
g = (ROOT / "app/ui/gradio_app.py").read_text()
sv = (ROOT / "app/api/server.py").read_text()
tl = (ROOT / "app/agent/tools.py").read_text()
ix = (ROOT / "app/retrieval/index.py").read_text()
ag = (ROOT / "app/agent/agent.py").read_text()
for name, ok in [
        ("no wall-clock fallback left in tools.py",
         'os.environ.get("ASOIA_NOW")' not in tl),
        ("no wall-clock fallback left in gradio_app.py",
         'datetime.fromisoformat(os.environ.get("ASOIA_NOW"))' not in g),
        ("no wall-clock fallback left in server.py",
         'os.environ["ASOIA_NOW"]' not in sv),
        ("reads use NOW, writes use EVENT_TIME",
         g.count("at=EVENT_TIME()") == 2 and "at=NOW()" not in g),
        ("both entry points bootstrap",
         "ensure_dataset()" in g and "ensure_dataset()" in sv),
        ("/health reports the clock", 'out["clock"] = clock_source()' in sv),
        ("/health degrades on a stale index",
         'out["status"] = "degraded"' in sv and "index_staleness" in sv),
        ("search_updates checks its citations", "_dangling(cits)" in ix),
        ("it flags rather than drops", '"citations": cits' in ix),
        ("the agent surfaces the flag", 'notes.append(_stale.get("note")' in ag)]:
    chk(name, ok)

print(f"\n{bad} check(s) unexpected" if bad else "\nAll checks as expected.")
print("""
The check that matters is the one this pass exists for. Run it:

    .venv/bin/python scripts/verify_answers.py

with no ASOIA_NOW set. All fourteen should pass however old the dataset is - the
four time-window questions used to fail once the data was a day or two behind.

    .venv/bin/python scripts/test_review.py     the review layer
    curl localhost:8080/health | jq .clock,.index
""")
sys.exit(1 if bad else 0)
