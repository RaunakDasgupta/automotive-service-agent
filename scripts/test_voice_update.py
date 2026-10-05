#!/usr/bin/env python3
"""Exercise the voice-update pipeline one stage at a time.

    .venv/bin/python scripts/test_voice_update.py                 # list the samples
    .venv/bin/python scripts/test_voice_update.py 1               # dry run sample 1
    .venv/bin/python scripts/test_voice_update.py 1 --apply       # write it for real
    .venv/bin/python scripts/test_voice_update.py --text "..."    # your own transcript
    .venv/bin/python scripts/test_voice_update.py 1 --no-llm      # skip extraction
    .venv/bin/python scripts/test_voice_update.py --audio note.wav

A DRY RUN IS GENUINELY DRY. It copies the database to a temporary file and
reconciles against the copy, so you get the real diff card, the real conflict
detection and the real state transition with nothing written to your data. Only
`--apply` touches the live file.

The samples carry a placeholder repair order, `{RO}`, which is replaced with a
real one from your database - picked to suit what each sample says, since an
update reporting brake work against a vehicle that is already invoiced tells you
nothing useful.

`--no-llm` feeds the validator a hand-written payload instead of calling the
model. That tests the deterministic half - op-code resolution, measurement
validation, conflict detection, the event write - with the NIMs down, and it is
the half where a silent failure would matter most.
"""
from __future__ import annotations
import argparse, json, os, shutil, sqlite3, sys, tempfile
from datetime import datetime

sys.path.insert(0, ".")
import _env  # noqa: E402,F401  - .env, like stack.sh; see scripts/_env.py

# --------------------------------------------------------------- the samples
# Each is written the way a technician actually dictates: concern, then what was
# found, then what was done and what is left. Every figure, code and part number
# here is one the catalogue really has, so a drop is a pipeline bug and not a
# typo in the test.
SAMPLES = [
    {
        "name": "clean update - work done, work left, hours, a measurement",
        "needs": "open",
        "text": (
            "Update for repair order {RO}. Customer states a grinding noise from "
            "the front of the car under braking, worse when cold. Road tested and "
            "confirmed the noise. Front brake inspection shows front pad thickness "
            "at one point eight millimetres against a three millimetre minimum, and "
            "the discs are scored. I have completed the front brake pads and rotors "
            "R and R, that took one point nine hours. Rear brake inspection still to "
            "do. Recommending a brake fluid flush and bleed as the fluid is dark, "
            "that needs customer authorisation."
        ),
        "raw": {
            "concern": "Grinding noise from the front under braking, worse when cold",
            "cause": "Front pads at 1.8mm against a 3.0mm minimum; discs scored",
            "verified": True,
            "completed": [{"work": "front brake pads and rotors R&R", "hours": 1.9}],
            "pending": [{"work": "rear brake inspection and measure"}],
            "recommended": [{"work": "brake fluid flush and bleed"}],
            "parts": [], "dtc_codes": [],
            "measurements": [{"type": "front_pad_thickness", "value": 1.8,
                              "unit": "mm", "spec_min": 3.0}],
            "ro_hint": "{RO}", "state_hint": "REPAIR_IN_PROGRESS",
            "safety_concern": True,
        },
    },
    {
        "name": "parts hold - a part number, availability, and a state change",
        "needs": "open",
        "text": (
            "This is for repair order {RO}. Customer reports the engine management "
            "light on and a rough idle. Scanned the vehicle and pulled fault code "
            "P zero one seven one, system too lean bank one. Found a split in the "
            "intake boot. Completed the system scan and code retrieval, zero point "
            "four hours. Part number zero nine one dash four four two dash A is on "
            "back order, so the job is on parts hold until it lands. Nothing else "
            "outstanding from me."
        ),
        "raw": {
            "concern": "Engine management light on with a rough idle",
            "cause": "Split intake boot; P0171 system too lean bank 1",
            "verified": True,
            "completed": [{"work": "system scan and code retrieval", "hours": 0.4}],
            "pending": [], "recommended": [],
            "parts": [{"part_no": "091-442-A", "description": "intake boot",
                       "availability": "BACKORDER"}],
            "dtc_codes": ["P0171"], "measurements": [],
            "ro_hint": "{RO}", "state_hint": "PARTS_HOLD",
            "safety_concern": False,
        },
    },
    {
        # Also the honest case: "vehicle health check" is one of the most common
        # things a technician dictates, and the catalogue has no operation for it -
        # only four specific inspections. So the pipeline asks which one. Before
        # pass 15 it silently picked a different wrong answer each time the phrase
        # was worded differently: TYR-INSP-TREAD, BRK-INSP, SUS-INSP.
        "name": "safety finding, plus a phrase the catalogue has no operation for",
        "needs": "open",
        "text": (
            "Repair order {RO}. In for a service. Vehicle health check done, that "
            "is zero point four hours. Nearside front tyre tread is down to one "
            "point two millimetres, minimum is one point six, so that is below the "
            "legal limit and the car should not be released. Offside front is fine "
            "at four point one. Recommending two front tyres, needs authorising "
            "before I fit them. Service itself is complete, one point one hours."
        ),
        "raw": {
            "concern": "In for scheduled service",
            "cause": "NSF tyre tread 1.2mm, below the 1.6mm legal minimum",
            "verified": True,
            "completed": [{"work": "vehicle health check", "hours": 0.4},
                          {"work": "lube oil and filter service", "hours": 1.1}],
            "pending": [],
            "recommended": [{"work": "tyre replacement front"}],
            "parts": [], "dtc_codes": [],
            "measurements": [
                {"type": "tyre_tread_nsf", "value": 1.2, "unit": "mm", "spec_min": 1.6},
                {"type": "tyre_tread_osf", "value": 4.1, "unit": "mm", "spec_min": 1.6}],
            "ro_hint": "{RO}", "state_hint": None,
            "safety_concern": True,
        },
    },
    {
        "name": "deliberately vague - should ask rather than guess",
        "needs": "open",
        "text": (
            "Yeah so I had a look at that one, sorted the thing out at the front, "
            "took about an hour. Still needs the other bit doing. Let the customer "
            "know."
        ),
        "raw": {
            "concern": None, "cause": None, "verified": False,
            "completed": [{"work": "sorted the thing out at the front", "hours": 1.0}],
            "pending": [{"work": "the other bit"}],
            "recommended": [], "parts": [], "dtc_codes": [], "measurements": [],
            "ro_hint": None, "state_hint": None, "safety_concern": False,
        },
    },
]


def _pick_ro(con, want: str) -> str | None:
    """A repair order the sample makes sense against: open, with history."""
    from app.state import db as dbm
    from app.state.engine import fold
    from app.state.transitions import ROState
    best = None
    for ro_no in dbm.all_ro_numbers(con):
        evs = dbm.events_for_ro(con, ro_no)
        if not evs:
            continue
        ro = dbm.get_ro(con, ro_no)
        snap = fold(evs, promised_time=datetime.fromisoformat(ro["promised_time"]))
        if want == "open" and snap.state == ROState.INVOICED:
            continue
        # Prefer one that is not already awaiting authorisation: reporting work
        # complete on such an RO is a blocking conflict, which sample 4 can show
        # on purpose but the others should not trip over by accident.
        if snap.state == ROState.AWAITING_AUTHORISATION:
            best = best or ro_no
            continue
        return ro_no
    return best


def _print_extraction(e) -> None:
    print("\n-- 3 C's extraction " + "-" * 55)
    print(f"  concern      : {e.concern}")
    print(f"  cause        : {e.cause}")
    print(f"  verified     : {e.verified}")
    for label, items in (("completed", e.completed), ("pending", e.pending),
                         ("recommended", e.correction)):
        for it in items:
            extra = f"  {it['actual_hrs']}h" if it.get("actual_hrs") else ""
            print(f"  {label:13s}: {it['op_code']}{extra}")
    for p in e.parts:
        print(f"  part         : {p['part_no']}  {p['availability']}")
    for m in e.measurements:
        flag = "  OUT OF SPEC" if m.get("out_of_spec") else ""
        print(f"  measurement  : {m['type']} = {m['value']}{m['unit']}"
              f" (min {m['spec_min']}){flag}")
    if e.dtc_codes:
        print(f"  fault codes  : {', '.join(e.dtc_codes)}")
    print(f"  state signal : {e.state_signal}")
    print(f"  severity     : {e.severity}")
    print(f"  confidence   : {e.confidence}")
    r = e.ro_resolution
    if r:
        verdict = "accepted" if r.certain else f"TOO LOW (needs {r.RO_THRESHOLD})"
        print(f"  repair order : {r.value}  confidence {r.confidence}"
              f"  [{r.reason}]  {verdict}")
    if e.unresolved:
        print("\n  did not resolve - the pipeline will ask instead of guessing:")
        for u in e.unresolved:
            cands = ", ".join(f"{c}({s:.2f})" for c, s in u["candidates"][:3])
            print(f"    \"{u['work']}\" ({u['kind']})  closest: {cands}")
    for q in e.clarifying_questions():
        print(f"    Q: {q}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample", nargs="?", type=int, help="1-%d" % len(SAMPLES))
    ap.add_argument("--text", help="your own transcript instead of a sample")
    ap.add_argument("--audio", help="a wav file, to exercise the ASR leg too")
    ap.add_argument("--apply", action="store_true",
                    help="write to the real database (default is a dry run on a copy)")
    ap.add_argument("--no-llm", action="store_true",
                    help="use the sample's hand-written payload, no model call")
    ap.add_argument("--tech", default="EMP001")
    ap.add_argument("--ro", help="force a repair order instead of picking one")
    args = ap.parse_args()

    if not (os.path.exists("pyproject.toml") and os.path.isdir("app/pipeline")):
        print("Run from the project root:\n"
              "  cd ~/automotive-service-agent && "
              ".venv/bin/python scripts/test_voice_update.py 1")
        return 2

    from app.state import db as dbm
    live = dbm.connect()

    if not (args.sample or args.text or args.audio):
        print("Samples (each is a full spoken update; say `1` to run one):\n")
        for i, s in enumerate(SAMPLES, 1):
            print(f"  {i}. {s['name']}")
        print(f"\nA repair order will be chosen from your database. "
              f"{len(dbm.all_ro_numbers(live))} on file.")
        print("\nDry run writes nothing:  scripts/test_voice_update.py 1")
        print("Then for real:           scripts/test_voice_update.py 1 --apply")
        return 0

    sample = None
    if args.sample:
        if not 1 <= args.sample <= len(SAMPLES):
            print(f"Sample must be 1-{len(SAMPLES)}")
            return 2
        sample = SAMPLES[args.sample - 1]

    ron = args.ro or _pick_ro(live, (sample or {}).get("needs", "open"))
    if not ron:
        print("No suitable repair order found - regenerate the dataset?")
        return 2

    # ---------------------------------------------------------------- the text
    if args.audio:
        from app.pipeline.asr import transcribe
        print(f"-- ASR {'-' * 66}")
        t = transcribe(args.audio)
        if not t.ok:
            print(f"  transcription failed: {t.error}")
            return 1
        print(f"  {t.duration_s or 0:.1f}s of audio, confidence {t.confidence}")
        text = t.text
    elif args.text:
        text = args.text
    else:
        text = sample["text"].replace("{RO}", ron)

    print(f"-- transcript {'-' * 61}")
    print("  " + "\n  ".join(_wrap(text, 74)))

    # ------------------------------------------------------------- extraction
    from app.pipeline.extract import extract, validate
    known = dbm.all_ro_numbers(live)
    try:
        from app.nim.client import embed as embed_fn
    except Exception:
        embed_fn = None

    if args.no_llm:
        if not sample:
            print("\n--no-llm needs a sample: there is no hand-written payload for "
                  "your own text.")
            return 2
        raw = json.loads(json.dumps(sample["raw"]).replace("{RO}", ron))
        print("\n  (no model call - using the sample's hand-written payload)")
        e = validate(raw, text, known, embed_fn=embed_fn)
    else:
        try:
            e = extract(text, known, embed_fn=embed_fn)
        except Exception as ex:
            print(f"\n  extraction failed: {type(ex).__name__}: {str(ex)[:200]}")
            print("  The NIMs must be up for this leg. For the deterministic half:")
            print(f"    scripts/test_voice_update.py {args.sample or 1} --no-llm")
            return 1
    _print_extraction(e)

    # ------------------------------------------------------------- reconcile
    from app.pipeline.reconcile import reconcile
    from app.pipeline.diffcard import render as render_diff
    at = datetime.fromisoformat(os.environ["ASOIA_NOW"]) if os.environ.get("ASOIA_NOW") \
        else datetime.now()

    tmp = None
    if args.apply:
        con, where = live, "the LIVE database"
    else:
        tmp = tempfile.mkdtemp(prefix="voicetest-")
        src = os.environ.get("ASOIA_DB", "data/generated/service.sqlite")
        copy = os.path.join(tmp, "service.sqlite")
        shutil.copy(src, copy)
        con = sqlite3.connect(copy)
        con.row_factory = sqlite3.Row
        where = "a throwaway copy - your data is untouched"

    print(f"\n-- reconcile into {where} " + "-" * max(0, 44 - len(where)))
    try:
        rec = reconcile(con, ron, e.to_ground_truth(text), args.tech, at=at,
                        update_id=f"UPD-TEST-{at.strftime('%Y%m%d%H%M%S')}")
        ro = dbm.get_ro(live, ron)
        print(f"  accepted: {rec.accepted}   events written: {len(rec.events)}")
        for ev in rec.events:
            print(f"    {ev.type.value:20s} {json.dumps(ev.payload, default=str)[:90]}")
        for c in rec.conflicts:
            print(f"    CONFLICT {c['kind']}: {c['detail']}")
        print("\n-- diff card, as the technician sees it " + "-" * 35)
        print(render_diff(rec, ro, now=at))
    finally:
        if tmp:
            con.close()
            shutil.rmtree(tmp, ignore_errors=True)

    if not args.apply:
        print("\nNothing was written. Re-run with --apply to commit it, then ask the "
              "assistant \"what changed on " + ron + " since last shift?\"")
    return 0


def _wrap(s: str, w: int) -> list[str]:
    out, line = [], ""
    for word in s.split():
        if len(line) + len(word) + 1 > w:
            out.append(line); line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
