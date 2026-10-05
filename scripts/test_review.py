#!/usr/bin/env python3
"""Check the review layer against the real database, and against the app itself.

    .venv/bin/python scripts/test_review.py          # offline checks
    .venv/bin/python scripts/test_review.py --live   # also the NIMs and the index

Exit 0 if everything checked out, 1 otherwise.

The two checks worth the file on their own:

  * The fold shown on the review screen must equal the state the analytics layer
    reports. They fold the same events through the same function, so a
    disagreement means one of them is passing different arguments - and the
    review screen is exactly where a wrong number would be believed.

  * `retrieval_trace` mirrors `search_updates` rather than sharing its code, so
    that it can keep the intermediate stage that `search` throws away. --live
    asserts the two still return the same citations. If retrieval is ever tuned
    in one place and not the other, this is what says so.
"""
from __future__ import annotations
import argparse, json, os, sys

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

BAD = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global BAD
    BAD += (not ok)
    print(f"  {'ok     ' if ok else 'WRONG  '} {name}" + (f"  ({detail})" if detail else ""))


def note(msg: str) -> None:
    print(f"  note    {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also exercise the vector index and the NIMs")
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/review")):
        print("Run from the project root:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/test_review.py")
        return 2

    from app.review import store as RS
    from app.state import db as dbm

    # ------------------------------------------------------------- the database
    print("\noverview:")
    o = RS.overview()
    if o.get("database") != "ok":
        print(f"  {o.get('database')}")
        return 2
    check("counts the repair orders", (o["repair_orders"] or 0) > 0, str(o["repair_orders"]))
    check("counts the events", (o["events"] or 0) > 0, str(o["events"]))
    check("counts the updates", (o["updates"] or 0) > 0, str(o["updates"]))
    check("knows the window", bool(o["first_event"] and o["last_event"]),
          f"{str(o['first_event'])[:10]} .. {str(o['last_event'])[:10]}")

    # --------------------------------------------------------------- event log
    print("\nevent log:")
    all_ev = RS.events(limit=1)
    check("totals independently of the page", all_ev["total"] == o["events"],
          f"{all_ev['total']} vs {o['events']}")
    types = RS.event_types()
    check("groups by type", len(types) == o["event_types_used"],
          f"{len(types)} types")
    check("type counts sum to the total",
          sum(t["n"] for t in types) == o["events"])

    t0 = types[0]["type"]
    filtered = RS.events(event_type=t0, limit=5)
    check(f"filters by type ({t0})",
          filtered["total"] == types[0]["n"] and
          all(e["type"] == t0 for e in filtered["events"]),
          f"{filtered['total']}")

    ro = RS.events(limit=1)["events"][0]["ro_number"]
    by_ro = RS.events(ro_number=ro, limit=500)
    check("filters by repair order",
          all(e["ro_number"] == ro for e in by_ro["events"]), f"{ro}")
    check("parses the payload", isinstance(by_ro["events"][0]["payload"], (dict, list)))
    check("orders newest first",
          [e["at"] for e in RS.events(limit=20)["events"]] ==
          sorted([e["at"] for e in RS.events(limit=20)["events"]], reverse=True))

    page1 = RS.events(limit=5, offset=0)["events"]
    page2 = RS.events(limit=5, offset=5)["events"]
    check("pages without repeating",
          not ({e["event_id"] for e in page1} & {e["event_id"] for e in page2}))

    # ---------------------------------------------------- the fold, cross-checked
    print("\nthe fold, against the analytics layer:")
    con = dbm.connect()
    from app.analytics.queries import get_ro_state
    checked = agreed = 0
    disagreements = []
    for ron in dbm.all_ro_numbers(con)[:25]:
        r = RS.ro_review(ron)
        if r.get("error") or r.get("fold_error"):
            continue
        try:
            theirs = get_ro_state(con, ron)
        except Exception:
            continue
        mine = r["state"]
        other = theirs.get("state")
        other = getattr(other, "value", other)
        checked += 1
        if mine == other:
            agreed += 1
        else:
            disagreements.append(f"{ron}: review={mine} analytics={other}")
    check("the review fold agrees with get_ro_state", checked and agreed == checked,
          f"{agreed}/{checked} repair orders")
    for d in disagreements[:5]:
        print(f"           {d}")

    sample = dbm.all_ro_numbers(con)[0]
    rv = RS.ro_review(sample)
    check("returns the events behind the state", len(rv["events"]) == rv["event_count"])
    check("the snapshot is JSON", _is_json(rv["snapshot"]))
    check("a missing repair order is an error, not a crash",
          "error" in RS.ro_review("RO-0000-0000"))

    # ------------------------------------------------------------------ updates
    print("\nupdates:")
    u = RS.updates(limit=1)
    check("totals the updates", u["total"] == o["updates"], str(u["total"]))
    check("joins the staff name", bool(u["updates"][0].get("staff_name")))
    word = (u["updates"][0]["text"].split() or ["a"])[0][:6]
    check(f"filters on text ('{word}')", RS.updates(text=word)["total"] >= 1)

    # ------------------------------------------------------------- vector store
    print("\nvector store:")
    idx = RS.index_stats()
    if not idx.get("exists"):
        note(f"no index: {idx.get('error')}")
        note("build it:  .venv/bin/python -c "
             "'from app.retrieval.index import build; print(build())'")
        check("a missing index is reported, not raised", "error" in idx)
        check("chunks() degrades the same way", "error" in RS.chunks())
    else:
        check("reports the row count", (idx.get("rows") or 0) > 0, str(idx.get("rows")))
        check("reports the dimension", bool(idx.get("dim")), str(idx.get("dim")))
        ch = RS.chunks(limit=5)
        check("browses chunks", ch["total"] > 0, f"{ch['total']}")
        check("list views carry no vectors",
              all("vector" not in r for r in ch["rows"]))
        one = RS.chunk(ch["rows"][0]["update_id"])
        check("one chunk carries its vector", bool(one.get("vector_preview")),
              f"dim {one.get('dim')}, norm {one.get('norm')}")
        h = RS.index_health()
        check("no zero vectors in the sample", h.get("ok") is True,
              f"{h.get('zero_norm')} of {h.get('sampled')}")
        check("a missing chunk is an error, not a crash",
              "error" in RS.chunk("UPD-does-not-exist"))

    # ------------------------------------------------------------- answer log
    print("\nanswer log:")
    from app.agent.agent import Answer
    before = RS.answers(limit=1)["total"]
    probe = Answer(question="__test_review probe__", text="probe",
                   citations=["UPD-PROBE-1", "UPD-PROBE-2"], grounded=True,
                   route="keyword", composed="python",
                   tool_calls=[{"name": "list_ros"}])
    RS.log_answer(probe, 0.123)
    after = RS.answers(limit=5)
    check("an answer is recorded", after["total"] == before + 1,
          f"{before} -> {after['total']}")
    row = after["answers"][0]
    check("citations round-trip", row["citations"] == ["UPD-PROBE-1", "UPD-PROBE-2"])
    check("tools round-trip", row["tools"] == ["list_ros"])
    check("grounded is a bool", row["grounded"] is True)
    check("the elapsed time is kept", row["seconds"] == 0.123)
    cb = RS.cited_by("UPD-PROBE-1")
    check("cited_by finds it", cb["count"] >= 1)
    check("cited_by does not match a different id",
          RS.cited_by("UPD-PROBE")["count"] == 0,
          "a LIKE would have matched the prefix")
    check("filters to ungrounded", all(not a["grounded"]
                                       for a in RS.answers(grounded=False)["answers"]))

    class _Broken:
        question = "x"
        def __getattr__(self, n):
            raise RuntimeError("boom")
    try:
        RS.log_answer(_Broken(), 1.0)
        check("logging can never break an answer", True)
    except Exception as e:
        check("logging can never break an answer", False, f"raised {type(e).__name__}")

    # --------------------------------------------------------------------- live
    if args.live:
        print("\nlive - the NIMs and the index:")
        t = RS.retrieval_trace("grinding noise from the front under braking")
        if t.get("error"):
            check("retrieval trace runs", False, t["error"])
        else:
            check("both stages are returned",
                  len(t["retrieved"]) > 0 and len(t["reranked"]) > 0,
                  f"{len(t['retrieved'])} retrieved, {len(t['reranked'])} kept")
            missing = [k for k in ("citations", "promoted", "dropped",
                                   "reranked", "rerank_applied") if k not in t]
            check("a degraded trace has the same shape as a healthy one",
                  not missing, str(missing) or
                  "a fallback must not change which keys exist")
            if t.get("rerank_applied"):
                check("the reranker reordered the vector results",
                      any(r["moved"] != 0 for r in t["reranked"]),
                      f"{len(t.get('promoted', []))} promoted, "
                      f"{len(t.get('dropped', []))} dropped")
            else:
                note(f"the second stage did not run: {t.get('rerank_error')}")
                note("the vector order stands. There is no hosted reranking "
                     "model - run the container (scripts/start_nims.sh run) and "
                     "set NIM_MODE_RERANK=local, which leaves the hosted "
                     "embedder and the 2048-dim index alone.")
            check("every kept passage knows where it came from",
                  all("vector_rank" in r and "moved" in r for r in t["reranked"]),
                  "required on the degraded path too")
            check("timings are reported",
                  all(t.get(k) is not None for k in ("embed_ms", "search_ms")),
                  f"embed {t.get('embed_ms')}ms, search {t.get('search_ms')}ms, "
                  f"rerank {t.get('rerank_ms')}ms")
            from app.retrieval.index import search_updates
            theirs = search_updates("grinding noise from the front under braking")
            # .get() and not [], because this comparison is the LAST thing that
            # should fail here: a missing key is already reported above as the
            # shape problem it is, rather than raised as a traceback over it.
            mine, hers = t.get("citations", []), theirs.get("citations", [])
            check("the trace cites exactly what search_updates cites",
                  mine == hers, f"{len(mine)} vs {len(hers)}")
            if mine != hers:
                print(f"           trace:  {mine}")
                print(f"           search: {hers}")
    else:
        note("skipped the index and the NIMs - re-run with --live for those")

    print(f"\n{BAD} check(s) unexpected" if BAD else "\nAll checks as expected.")
    return 1 if BAD else 0


def _is_json(v) -> bool:
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
