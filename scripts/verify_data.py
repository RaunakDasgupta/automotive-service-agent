"""Verify the generated dataset is structurally real, not merely plausible."""
import sys, json
from collections import Counter
sys.path.insert(0, '.')
from app.state import db as dbm
from app.state.engine import fold
from app.data.vin import is_valid_vin
from app.data.catalog import OP_BY_CODE, DTC_CODES

con = dbm.connect()
fail = []

ros = con.execute("SELECT * FROM ros").fetchall()
bad_vin = [r["ro_number"] for r in ros if not is_valid_vin(r["vin"])]
print(f"VIN check digit      : {len(ros)-len(bad_vin)}/{len(ros)} valid")
if bad_vin: fail.append(f"invalid VINs: {bad_vin[:5]}")

ups = con.execute("SELECT * FROM updates").fetchall()
bad_ops, bad_dtc = set(), set()
for u in ups:
    gt = json.loads(u["ground_truth"])
    for key in ("completed", "pending", "correction"):
        for o in gt.get(key) or []:
            if o["op_code"] not in OP_BY_CODE: bad_ops.add(o["op_code"])
    for c in gt.get("dtc_codes") or []:
        if c not in DTC_CODES or c[0] not in "PBCU": bad_dtc.add(c)
print(f"op codes resolve     : {'ALL' if not bad_ops else bad_ops}")
print(f"DTC codes valid      : {'ALL' if not bad_dtc else bad_dtc}")
if bad_ops: fail.append(f"unknown op codes {bad_ops}")
if bad_dtc: fail.append(f"bad DTCs {bad_dtc}")

# Fold every RO - the engine must survive the entire generated history.
states, blocked, safety, conflicts, errs = Counter(), 0, 0, Counter(), []
from datetime import datetime
for r in ros:
    try:
        evs = dbm.events_for_ro(con, r["ro_number"])
        snap = fold(evs, promised_time=datetime.fromisoformat(r["promised_time"]))
        states[snap.state.value] += 1
        blocked += snap.is_blocked
        safety += snap.has_open_safety
        for c in snap.conflicts: conflicts[c.kind] += 1
    except Exception as e:
        errs.append((r["ro_number"], repr(e)))
print(f"\nfolded {len(ros)-len(errs)}/{len(ros)} ROs without error")
if errs:
    fail.append(f"fold errors: {errs[:3]}"); print("  ERRORS:", errs[:3])

print("\nRO state distribution:")
for s, n in states.most_common():
    print(f"  {n:4d}  {s}")
print(f"\nblocked now          : {blocked} ({blocked/len(ros)*100:.0f}%)")
print(f"open safety items    : {safety}")
print(f"conflicts detected   : {dict(conflicts) or 'none'}")

txt = [u["text"] for u in ups]
print(f"\nupdates              : {len(txt)}")
print(f"unique texts         : {len(set(txt))} ({len(set(txt))/len(txt)*100:.1f}% distinct)")
print(f"mean length          : {sum(len(t) for t in txt)//len(txt)} chars")
roles = Counter(r[0] for r in con.execute(
    "SELECT s.role FROM updates u JOIN staff s ON s.staff_id=u.staff_id").fetchall())
print(f"update authors       : {dict(roles)}")

print("\n" + ("FAILED: " + "; ".join(fail) if fail else "ALL REALISM CHECKS PASSED"))
sys.exit(1 if fail else 0)
