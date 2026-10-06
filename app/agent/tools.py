"""Agent tools: plain typed Python functions over the deterministic layer.

Written as ordinary functions first so they are testable and reusable, then
wrapped by NeMo Agent Toolkit in workflow.yml. Every tool returns data plus the
event/update ids that produced it, so any claim built on it can be cited.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Callable

from app.state import db as dbm
from app.analytics import queries as Q
from app.analytics import insights as I

def con():
    """The connection for THIS thread.

    This used to cache one connection in a module global, which defeated the
    whole point of dbm.connect() being thread-local - and SQLite refuses a
    connection used from a thread other than the one that made it. Gradio and
    uvicorn both run handlers in a worker pool, so the failure was intermittent:
    whichever thread got there first worked, and the rest raised ProgrammingError
    inside a tool, where call() turned it into a result dict and the answer came
    back looking fine. dbm.connect() already caches per thread.
    """
    return dbm.connect()


def _now(now=None) -> datetime:
    """The application's clock: pinned, else the newest event, else the wall.

    It used to fall back to the wall clock, which walks away from a generated
    dataset and empties out every time-window question. See app/state/clock.py.
    """
    from app.state.clock import now as _clock
    return _clock(now)


# ------------------------------------------------------------------ tools
def get_ro_state(ro_number: str) -> dict:
    """Current derived state of one repair order: work done, outstanding,
    recommended, parts, safety findings, promise risk."""
    return Q.get_ro_state(con(), ro_number.strip().upper(), now=_now())


def get_ro_timeline(ro_number: str, limit: int = 20) -> dict:
    """Chronological technician updates for a repair order, as written."""
    return Q.get_ro_timeline(con(), ro_number.strip().upper(), limit=limit)


def list_ros(filter: str = "active", limit: int = 25) -> dict:
    """List repair orders. filter: active|blocked|at_risk|safety|waiter|all
    or any lifecycle state such as PARTS_HOLD."""
    return Q.list_ros(con(), filter=filter, limit=limit, now=_now())


def get_technician_activity(staff_id: str, days: int = 7) -> dict:
    """What one technician completed over a window, with proficiency."""
    return Q.get_technician_activity(con(), staff_id.strip().upper(), days=days, now=_now())


def generate_handover(shift: str = "AFTERNOON") -> dict:
    """Prioritised shift handover: safety, breached, at-risk, blocked, in-flight,
    each with a concrete next action."""
    return I.generate_handover(con(), shift=shift.upper(), now=_now())


def detect_anomalies(days: int = 7) -> dict:
    """Cross-repair-order patterns: shared part holds, stalled work,
    authorisation delays, comebacks, repeat visits."""
    return I.detect_anomalies(con(), days=days, now=_now())


def diff_ro(ro_number: str, since_hours: int = 12) -> dict:
    """What changed on a repair order within a window."""
    return I.diff_ro(con(), ro_number.strip().upper(), since_hours=since_hours, now=_now())


def search_updates(query: str, k: int = 4, ro_number: str | None = None) -> dict:
    """Semantic search across technician updates. Use for narrative questions
    ('has anyone seen this fault before'), not for current state."""
    from app.retrieval.index import search_updates as _s
    try:
        return _s(query, k=k, ro_number=ro_number)
    except Exception as e:
        return {"query": query, "count": 0, "passages": [], "citations": [],
                "error": f"retrieval unavailable: {type(e).__name__}"}


def get_op_code_info(op_code: str) -> dict:
    """Look up a labour operation: description, flat-rate hours, category, skill."""
    from app.data.catalog import OP_BY_CODE
    o = OP_BY_CODE.get(op_code.strip().upper())
    if not o:
        return {"found": False, "error": f"No labour operation {op_code}."}
    return {"found": True, "op_code": o.op_code, "description": o.description,
            "flat_rate_hrs": o.flat_rate_hrs, "category": o.category,
            "min_skill": o.min_skill, "safety_critical": o.safety_critical}


def get_shift_activity(day_offset: int = 0, shift: str = "",
                       view: str = "people", days: int = 1,
                       brief: bool = False) -> dict:
    """What was WORKED ON over a day or a window. day_offset 0 is today, -1
    yesterday; days 1 that day alone, 7 the week ending there. shift MORNING or
    AFTERNOON, or omit for the whole day. view "people" for who worked,
    "vehicles" for which cars were worked on and what was done to each. Not the
    same as what was booked in, which is get_intake.
    """
    return Q.get_shift_activity(con(), day_offset=day_offset, shift=shift,
                                view=view, days=days, brief=brief, now=_now())



def get_intake(days: int = 7) -> dict:
    """How many vehicles came INTO the shop over the last `days`, and what
    became of them: still open, completed, blocked, open safety, waiters, the
    busiest day and the split by category. Use for "how many cars came in this
    week", "how busy were we", "how much work did we take in". Arrival is a
    recorded column, so this is exact. Not the same as which cars were WORKED
    ON, which is get_shift_activity.
    """
    return Q.get_intake(con(), days=days, now=_now())


TOOLS: dict[str, Callable[..., dict]] = {
    "get_ro_state": get_ro_state,
    "get_ro_timeline": get_ro_timeline,
    "list_ros": list_ros,
    "get_technician_activity": get_technician_activity,
    "generate_handover": generate_handover,
    "detect_anomalies": detect_anomalies,
    "diff_ro": diff_ro,
    "search_updates": search_updates,
    "get_op_code_info": get_op_code_info,
    "get_shift_activity": get_shift_activity,
    "get_intake": get_intake,
}

# OpenAI-style schemas, used both for NIM function calling and by NAT.
SPECS = [
 {"type":"function","function":{"name":"get_ro_state",
  "description":get_ro_state.__doc__,
  "parameters":{"type":"object","properties":{"ro_number":{"type":"string"}},
                "required":["ro_number"]}}},
 {"type":"function","function":{"name":"get_ro_timeline",
  "description":get_ro_timeline.__doc__,
  "parameters":{"type":"object","properties":{"ro_number":{"type":"string"},
                "limit":{"type":"integer"}},"required":["ro_number"]}}},
 {"type":"function","function":{"name":"list_ros",
  "description":list_ros.__doc__,
  "parameters":{"type":"object","properties":{
      "filter":{"type":"string","enum":["active","blocked","at_risk","safety","waiter","all"]},
      "limit":{"type":"integer"}}}}},
 {"type":"function","function":{"name":"get_technician_activity",
  "description":get_technician_activity.__doc__,
  "parameters":{"type":"object","properties":{"staff_id":{"type":"string"},
                "days":{"type":"integer"}},"required":["staff_id"]}}},
 {"type":"function","function":{"name":"generate_handover",
  "description":generate_handover.__doc__,
  "parameters":{"type":"object","properties":{
      "shift":{"type":"string","enum":["MORNING","AFTERNOON"]}}}}},
 {"type":"function","function":{"name":"detect_anomalies",
  "description":detect_anomalies.__doc__,
  "parameters":{"type":"object","properties":{"days":{"type":"integer"}}}}},
 {"type":"function","function":{"name":"diff_ro",
  "description":diff_ro.__doc__,
  "parameters":{"type":"object","properties":{"ro_number":{"type":"string"},
                "since_hours":{"type":"integer"}},"required":["ro_number"]}}},
 {"type":"function","function":{"name":"search_updates",
  "description":search_updates.__doc__,
  "parameters":{"type":"object","properties":{"query":{"type":"string"},
                "k":{"type":"integer"},"ro_number":{"type":"string"}},
                "required":["query"]}}},
 {"type":"function","function":{"name":"get_op_code_info",
  "description":get_op_code_info.__doc__,
  "parameters":{"type":"object","properties":{"op_code":{"type":"string"}},
                "required":["op_code"]}}},
 {"type":"function","function":{"name":"get_shift_activity",
  "description":get_shift_activity.__doc__,
  "parameters":{"type":"object","properties":{
      "day_offset":{"type":"integer",
                    "description":"0 today, -1 yesterday, -2 the day before"},
      "shift":{"type":"string","enum":["MORNING","AFTERNOON",""]},
      "view":{"type":"string","enum":["people","vehicles"],
              "description":"people = who worked; vehicles = which cars"},
      "days":{"type":"integer",
              "description":"1 that day alone, 7 the week ending there"}}}}},
 {"type":"function","function":{"name":"get_intake",
  "description":get_intake.__doc__,
  "parameters":{"type":"object","properties":{
      "days":{"type":"integer",
              "description":"window ending now; 1 today, 7 this week, 30 this month"}}}}},
]


def call(name: str, **kwargs) -> dict:
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"unknown tool {name}", "available": list(TOOLS)}
    # Every tool the agent runs is dispatched here, so this is the one place a
    # trace has to be taken. The error shapes below are untouched: callers and
    # tests already match on them.
    from app.obs import trace as _trace
    with _trace.tool_span(name, kwargs) as _span:
        try:
            out = fn(**kwargs)
        except TypeError as e:
            out = {"error": f"bad arguments for {name}: {e}"}
        except Exception as e:
            out = {"error": f"{name} failed: {type(e).__name__}: {str(e)[:200]}"}
        _span["result"] = out
        return out
