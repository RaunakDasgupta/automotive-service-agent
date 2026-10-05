"""Render what changed - the technician's immediate feedback after submitting.

This is the component that makes updates feel useful rather than like filing a
form: it shows what the system understood, what it inferred, what it disputes,
and what that means for the promised time.
"""
from __future__ import annotations
from datetime import datetime
from app.state.engine import ROSnapshot
from app.pipeline.reconcile import Reconciliation

TICK, PLUS, OPEN, WARN, BLOCK, CLOCK = "✓", "+", "○", "⚠", "⛔", "⏰"


def render(rec: Reconciliation, ro: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if not rec.accepted:
        lines = [f"{WARN} Update NOT applied to {rec.ro_number}", ""]
        lines += [f"  {c}" for c in rec.clarifications]
        if rec.conflicts:
            lines += ["", "  Conflicts:"] + [f"   - {c['detail']}" for c in rec.conflicts]
        return "\n".join(lines)

    b, a = rec.before, rec.after
    head = (f"{rec.ro_number} · {ro['model_year']} {ro['make']} {ro['model']} "
            f"· {ro['odometer_miles']:,} mi")
    lines = [head, "=" * len(head)]

    done_before = {o.op_code for o in b.completed_ops} if b else set()
    for o in a.completed_ops:
        if o.op_code not in done_before:
            fr = f"   (flat rate {o.flat_rate})" if o.flat_rate else ""
            hrs = f"{o.actual_hrs} hr" if o.actual_hrs else ""
            lines.append(f"  {TICK} {o.description:<38} {hrs:>7}{fr}")

    prior = set(b.ops) if b else set()
    for code, o in a.ops.items():
        if code not in prior and o.status == "RECOMMENDED":
            lines.append(f"  {PLUS} {o.description:<38} RECOMMENDED - needs authorisation")

    prior_flags = {f.get("event_id") for f in (b.safety_flags if b else [])}
    for f in a.safety_flags:
        if f.get("event_id") not in prior_flags:
            lines.append(f"  {WARN} {f['detail']} → SAFETY_RELATED")

    if b and a.state != b.state:
        why = f" ({a.blocked_on})" if a.blocked_on else ""
        lines.append(f"  {BLOCK} State → {a.state.value}{why}")

    for o in a.pending_ops:
        lines.append(f"  {OPEN} {o.description} still pending")

    for c in rec.conflicts:
        lines.append(f"  {WARN} Conflict: {c['detail']}")

    risk = a.promise_risk(now)
    if a.promised_time:
        pt = a.promised_time.strftime("%H:%M")
        if risk == "BREACHED":
            lines.append(f"  {CLOCK} Promised {pt} - BREACHED")
        elif risk == "AT_RISK":
            lines.append(f"  {CLOCK} Promised {pt} - AT RISK")
        else:
            lines.append(f"  {CLOCK} Promised {pt} - on track")

    n_open = len(a.pending_ops) + len(a.recommended_ops)
    if n_open:
        lines.append(f"  → {n_open} item(s) remain open on this RO.")
    return "\n".join(lines)
