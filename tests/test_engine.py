"""Engine tests - deterministic, no GPU, no network."""
import sys, pytest
from datetime import datetime, timedelta
sys.path.insert(0, '.')
from app.state.events import Event, EventType as E
from app.state.engine import fold
from app.state.transitions import ROState as S, is_legal

T0 = datetime(2026, 9, 24, 8, 0)
RO = "RO-26-08871"


def ev(t, at_min, actor="EMP014", **payload):
    return Event(RO, t, T0 + timedelta(minutes=at_min), actor, payload)


def base():
    return [ev(E.RO_OPENED, 0, "SYSTEM"), ev(E.STATE_CHANGED, 10, "ADV001", to="DISPATCHED")]


class TestTransitions:
    def test_repair_cannot_start_before_authorisation(self):
        assert not is_legal(S.AWAITING_AUTHORISATION, S.REPAIR_IN_PROGRESS)

    def test_qc_failure_returns_to_bench(self):
        assert is_legal(S.QUALITY_CONTROL, S.REPAIR_IN_PROGRESS)

    def test_invoiced_is_terminal(self):
        assert not any(is_legal(S.INVOICED, s) for s in S)

    def test_menu_priced_work_may_skip_diagnosis(self):
        assert is_legal(S.DISPATCHED, S.ESTIMATE_PREPARED)


class TestFold:
    def test_empty_log_rejected(self):
        with pytest.raises(ValueError):
            fold([])

    def test_illegal_transition_is_surfaced_not_applied(self):
        evs = base() + [ev(E.STATE_CHANGED, 20, to="INVOICED")]
        snap = fold(evs)
        assert snap.state is S.DISPATCHED, "illegal jump must not mutate state"
        assert any(c.kind == "ILLEGAL_TRANSITION" for c in snap.conflicts)

    def test_repeat_op_flagged_as_comeback(self):
        evs = base() + [
            ev(E.STATE_CHANGED, 15, to="REPAIR_IN_PROGRESS"),
            ev(E.OP_COMPLETED, 30, op_code="BRK-FR-PAD", actual_hrs=1.7),
            ev(E.OP_COMPLETED, 400, op_code="BRK-FR-PAD", actual_hrs=0.6)]
        snap = fold(evs)
        assert snap.comebacks == 1
        assert any(c.kind == "REPEAT_OP" for c in snap.conflicts)

    def test_out_of_spec_measurement_raises_safety_flag(self):
        evs = base() + [ev(E.MEASUREMENT_TAKEN, 40, type="rotor_thickness", value=22.8,
                           unit="mm", spec_min=23.0, out_of_spec=True, safety_related=True)]
        snap = fold(evs)
        assert snap.has_open_safety
        assert "22.8mm" in snap.safety_flags[0]["detail"]

    def test_in_spec_measurement_raises_nothing(self):
        evs = base() + [ev(E.MEASUREMENT_TAKEN, 40, type="rotor_thickness", value=25.1,
                           unit="mm", spec_min=23.0, out_of_spec=False, safety_related=False)]
        assert not fold(evs).has_open_safety

    def test_completed_op_is_not_downgraded_by_a_later_pending(self):
        evs = base() + [
            ev(E.STATE_CHANGED, 15, to="REPAIR_IN_PROGRESS"),
            ev(E.OP_COMPLETED, 30, op_code="LOF", actual_hrs=0.4),
            ev(E.OP_PENDING, 45, op_code="LOF")]
        assert fold(evs).ops["LOF"].status == "COMPLETED"

    def test_proficiency_is_flat_rate_over_actual(self):
        evs = base() + [
            ev(E.STATE_CHANGED, 15, to="REPAIR_IN_PROGRESS"),
            ev(E.OP_COMPLETED, 30, op_code="BRK-FR-PAD", actual_hrs=1.5)]  # flat rate 1.8
        snap = fold(evs)
        assert snap.hours_booked == 1.5 and snap.flat_rate_total == 1.8
        assert snap.proficiency == 1.2

    def test_parts_hold_names_the_blocking_part(self):
        evs = base() + [
            ev(E.STATE_CHANGED, 15, to="DIAGNOSING"),
            ev(E.PARTS_ORDERED, 20, part_no="45022-T2G-A01", availability="BACKORDER"),
            ev(E.STATE_CHANGED, 25, to="PARTS_HOLD")]
        snap = fold(evs)
        assert snap.is_blocked and "45022-T2G-A01" in snap.blocked_on

    def test_received_parts_clear_the_block_reason(self):
        evs = base() + [
            ev(E.STATE_CHANGED, 15, to="DIAGNOSING"),
            ev(E.PARTS_ORDERED, 20, part_no="P1", availability="BACKORDER"),
            ev(E.STATE_CHANGED, 25, to="PARTS_HOLD"),
            ev(E.PARTS_RECEIVED, 60, part_no="P1")]
        assert fold(evs).blocked_on == "parts"

    def test_event_order_independence(self):
        evs = base() + [ev(E.STATE_CHANGED, 15, to="DIAGNOSING"),
                        ev(E.OP_COMPLETED, 30, op_code="DIAG-BRAKE", actual_hrs=0.4)]
        assert fold(list(reversed(evs))).state == fold(evs).state

    def test_every_fact_carries_provenance(self):
        evs = base() + [ev(E.STATE_CHANGED, 15, to="REPAIR_IN_PROGRESS"),
                        ev(E.OP_COMPLETED, 30, op_code="LOF", actual_hrs=0.4)]
        snap = fold(evs)
        assert snap.ops["LOF"].event_id and len(snap.event_ids) == len(evs)


class TestPromiseRisk:
    def _snap(self, promised_in_h, state=S.PARTS_HOLD):
        evs = base() + [ev(E.STATE_CHANGED, 15, to="DIAGNOSING"),
                        ev(E.STATE_CHANGED, 20, to=state.value)]
        return fold(evs, promised_time=T0 + timedelta(hours=promised_in_h))

    def test_breached_when_promise_passed(self):
        assert self._snap(1).promise_risk(now=T0 + timedelta(hours=3)) == "BREACHED"

    def test_at_risk_when_blocked_near_promise(self):
        assert self._snap(9).promise_risk(now=T0 + timedelta(hours=7)) == "AT_RISK"

    def test_ok_when_ample_time(self):
        assert self._snap(30).promise_risk(now=T0 + timedelta(hours=1)) == "OK"
