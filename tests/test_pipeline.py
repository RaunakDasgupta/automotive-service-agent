"""Extraction, resolution and reconciliation - all offline, no GPU, no network."""
import sys, json, pytest
from datetime import datetime
sys.path.insert(0, '.')
from app.pipeline.extract import parse_json, validate, Extraction
from app.pipeline.resolve import resolve_ro, resolve_op, Resolution, expand_aliases
from app.data.catalog import OP_BY_CODE

ROS = ["RO-26-08165", "RO-26-08166", "RO-26-08394"]


class TestJsonParsing:
    @pytest.mark.parametrize("blob,expected", [
        ('{"a":1}', {"a": 1}),
        ('```json\n{"a":2}\n```', {"a": 2}),
        ('Here you go:\n{"a":3}\nHope that helps!', {"a": 3}),
        ('{"a":"brace } inside string"}', {"a": "brace } inside string"}),
    ])
    def test_tolerates_model_formatting(self, blob, expected):
        assert parse_json(blob) == expected

    def test_rejects_output_with_no_json(self):
        with pytest.raises(ValueError):
            parse_json("I could not process that.")


class TestRoResolution:
    def test_exact_number(self):
        assert resolve_ro("finished RO-26-08165", ROS).value == "RO-26-08165"

    def test_spoken_digits(self):
        r = resolve_ro("ro two six zero eight one six five", ROS)
        assert r.value == "RO-26-08165"

    def test_ambiguous_suffix_asks_rather_than_guesses(self):
        r = resolve_ro("job 0816", ["RO-26-08160", "RO-26-08161"])
        assert r.value is None and r.needs_clarification

    def test_no_reference_is_not_invented(self):
        assert resolve_ro("the blue golf on ramp 3", ROS).value is None


class TestOpResolution:
    @pytest.mark.parametrize("text,expected", [
        ("front brake pads and discs", "BRK-FR-PAD"),
        ("rear pads and discs", "BRK-RR-PAD"),       # axle position must be honoured
        ("oil and filter change", "LOF"),
        ("four wheel alignment", "ALN-4WHEEL"),
        ("ac regas", "HVAC-EVAC"),
    ])
    def test_trade_language_resolves(self, text, expected):
        assert resolve_op(text).value == expected

    def test_front_and_rear_are_not_confused(self):
        assert resolve_op("front pads").value != resolve_op("rear pads").value

    def test_nonsense_is_not_resolved(self):
        r = resolve_op("teleport the flux capacitor")
        assert not r.is_certain(Resolution.OP_THRESHOLD)

    def test_op_code_passes_through(self):
        assert resolve_op("BRK-FR-PAD").value == "BRK-FR-PAD"

    def test_aliases_expand(self):
        assert "rotor" in expand_aliases("brake discs").lower()


class TestValidation:
    def _raw(self, **over):
        base = {"concern": "grinding", "cause": "pad worn", "verified": True,
                "completed": [{"work": "front brake pads and discs", "hours": 1.7}],
                "pending": [{"work": "rear brake inspection"}],
                "recommended": [], "parts": [], "dtc_codes": [], "measurements": [],
                "ro_hint": "RO-26-08165", "state_hint": None, "safety_concern": False}
        base.update(over)
        return base

    def test_work_maps_to_canonical_codes(self):
        e = validate(self._raw(), "RO-26-08165", ROS)
        assert e.completed[0]["op_code"] == "BRK-FR-PAD"
        assert e.pending[0]["op_code"] == "BRK-RR-INSP"

    def test_hallucinated_dtc_is_dropped(self):
        e = validate(self._raw(dtc_codes=["P0420", "P9999", "NOTACODE"]), "", ROS)
        assert e.dtc_codes == ["P0420"]

    def test_out_of_spec_measurement_sets_safety(self):
        e = validate(self._raw(measurements=[
            {"type": "rotor_thickness", "value": 22.8, "unit": "mm", "spec_min": 23.0}]), "", ROS)
        assert e.severity == "SAFETY_RELATED"
        assert e.measurements[0]["out_of_spec"] is True

    def test_in_spec_measurement_does_not(self):
        e = validate(self._raw(measurements=[
            {"type": "rotor_thickness", "value": 25.0, "unit": "mm", "spec_min": 23.0}]), "", ROS)
        assert e.severity is None

    def test_implausible_hours_rejected(self):
        e = validate(self._raw(completed=[{"work": "front brake pads and discs", "hours": 900}]),
                     "", ROS)
        assert e.completed[0]["actual_hrs"] is None

    def test_unknown_work_becomes_a_question_not_a_guess(self):
        e = validate(self._raw(completed=[{"work": "teleport the flux capacitor", "hours": 1}]),
                     "", ROS)
        assert e.completed == []
        assert e.unresolved and e.needs_clarification
        assert any("teleport" in q for q in e.clarifying_questions())

    def test_invalid_state_hint_ignored(self):
        assert validate(self._raw(state_hint="BANANA"), "", ROS).state_signal is None

    def test_missing_ro_forces_clarification(self):
        e = validate(self._raw(ro_hint=None), "no reference here", ROS)
        assert e.needs_clarification
        assert any("Which repair order" in q for q in e.clarifying_questions())
