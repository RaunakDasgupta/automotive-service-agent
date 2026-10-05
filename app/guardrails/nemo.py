"""NeMo Guardrails on the serving path, in shadow by default.

`app/guardrails/config/` has carried three colang flows - out of scope, prompt
injection, unauthorised action - since the first release, and nothing ever
called them. The hand-written patterns in rails.py did the work. This puts the
colang rails back on the path without betting the demo on them.

    ASOIA_NEMO_RAILS=off      the default. Nothing runs. Behaviour byte-identical.
    ASOIA_NEMO_RAILS=shadow   colang runs in a background thread AFTER the answer
                              has gone out. It cannot change a decision and adds
                              no latency; every agreement and disagreement is
                              counted, so you can see what it WOULD have done.
    ASOIA_NEMO_RAILS=on       colang runs inline and is authoritative alongside
                              the patterns: if either would block, the request is
                              blocked. Costs a model call per turn.

Shadow is the interesting mode and the reason this file exists. A guardrail you
have never run against real traffic is a guess; one you have run in shadow for a
week is a measurement. Turning it on without that step is how you discover it
refuses "Show me the handover" in front of an audience - which is exactly the
class of bug pass 20 found in the hand-written patterns.

Every failure here degrades to "no opinion". A guardrail experiment must never be
the reason a question goes unanswered.
"""
from __future__ import annotations
import os
import threading

_rails = None
_load_failed = False
_lock = threading.Lock()


def mode() -> str:
    """off | shadow | on. Anything unrecognised is off."""
    m = os.environ.get("ASOIA_NEMO_RAILS", "off").strip().lower()
    return m if m in ("off", "shadow", "on") else "off"


def available() -> bool:
    """Is the library installed and the colang config present?"""
    from app.guardrails.rails import CONFIG_DIR
    try:
        import nemoguardrails  # noqa: F401
    except Exception:
        return False
    return CONFIG_DIR.is_dir() and any(CONFIG_DIR.glob("*.co"))


def _get():
    """Load the colang rails once. Returns None if they cannot be loaded."""
    global _rails, _load_failed
    if _rails is not None or _load_failed:
        return _rails
    with _lock:
        if _rails is None and not _load_failed:
            try:
                from app.guardrails.rails import load_nemo_rails
                _rails = load_nemo_rails()
            except Exception as e:
                _load_failed = True
                print(f"[nemo] colang rails unavailable ({type(e).__name__}: "
                      f"{str(e)[:120]}) - continuing without them")
    return _rails


# A colang flow that fires replaces the answer with its own refusal text. These
# are the openings the three flows in rails.co produce; matching on them is how
# we tell "the rail fired" from "the model answered".
_REFUSALS = ("i can't", "i cannot", "i'm not able", "i am not able",
             "only cover", "has to be a person", "can't change my operating")


def verdict(question: str) -> bool | None:
    """Would the colang rails allow this QUESTION? True/False, or None.

    Evaluates the INPUT rails only, and nothing else.

    This used to run the whole pipeline. That made colang answer the question
    itself using the bare LLM with no tools, and then let the output rail judge
    that invented answer - while the builtin rail it is compared against checks
    the question. A verdict on a hallucinated answer is not comparable to a
    verdict on the question, and the mismatch produced confident false blocks:
    "Which jobs are blocked waiting for parts?" was refused because the
    tool-less answer tripped the unauthorised-action rail.

    Restricting generation to the input rails makes the two sides answer the
    same question. Measured across the versioned sets: 4/4 action requests
    blocked, 24/24 legitimate questions allowed, one local NIM call and about
    45ms each.
    """
    rails = _get()
    if rails is None:
        return None
    try:
        res = rails.generate(
            messages=[{"role": "user", "content": question}],
            options={"rails": {"input": True, "dialog": False,
                               "output": False, "retrieval": False},
                     "log": {"activated_rails": True}},
        )
    except Exception:
        return None
    try:
        log = getattr(res, "log", None)
        acts = (getattr(log, "activated_rails", None) or []) if log is not None else []
        if not acts:
            # No input rail ran, so colang expressed no view. Saying "allow"
            # here is what the previous version did, and it is how a rail that
            # never fires gets recorded as agreement.
            return None
        for r in acts:
            if getattr(r, "stop", False):
                return False
            if "stop" in (getattr(r, "decisions", None) or []):
                return False
        return True
    except Exception:
        return None


def _compare(question: str, builtin_allowed: bool) -> None:
    """Record how the colang rails would have decided. Never raises."""
    from app.obs import metrics as M
    try:
        nemo_allowed = verdict(question)
        if nemo_allowed is None:
            M.RAIL_SHADOW.labels(agreement="no_opinion").inc()
        elif nemo_allowed == builtin_allowed:
            M.RAIL_SHADOW.labels(
                agreement="agree_allow" if builtin_allowed else "agree_block").inc()
        elif builtin_allowed:
            # The interesting one: colang catches something the patterns missed.
            M.RAIL_SHADOW.labels(agreement="nemo_only_block").inc()
        else:
            M.RAIL_SHADOW.labels(agreement="builtin_only_block").inc()
    except Exception:
        try:
            M.RAIL_SHADOW.labels(agreement="error").inc()
        except Exception:
            pass


def observe(question: str, builtin_allowed: bool) -> None:
    """Shadow mode: compare in the background, after the answer has gone."""
    if mode() != "shadow" or not available():
        return
    threading.Thread(target=_compare, args=(question, builtin_allowed),
                     daemon=True).start()


def enforce(question: str) -> bool | None:
    """On mode: the colang verdict, to be combined with the patterns."""
    if mode() != "on" or not available():
        return None
    return verdict(question)
