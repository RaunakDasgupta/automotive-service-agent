"""Agent routing and grounding - deterministic paths only, no LLM."""
import sys, pytest
sys.path.insert(0, '.')
from app.agent.agent import plan_keyword, check_grounding, _collect_citations
from app.agent.tools import TOOLS, call


class TestRouting:
    @pytest.mark.parametrize("q,expected", [
        ("What's the status of RO-26-08165?", "get_ro_state"),
        ("Give me the afternoon handover", "generate_handover"),
        ("Which vehicles are unsafe to release?", "list_ros"),
        ("What has EMP014 done this week?", "get_technician_activity"),
        ("Which jobs will miss their promised time?", "list_ros"),
        ("Any unusual patterns this week?", "detect_anomalies"),
    ])
    def test_routes_to_expected_tool(self, q, expected):
        assert expected in [c["name"] for c in plan_keyword(q)]

    def test_unknown_question_falls_back_to_search(self):
        assert plan_keyword("has anyone seen a whistling noise on a Passat")[0]["name"] == "search_updates"

    def test_every_planned_tool_exists(self):
        for q in ["status of RO-26-08165", "handover", "anomalies", "what changed on RO-26-08165"]:
            for c in plan_keyword(q):
                assert c["name"] in TOOLS


class TestGrounding:
    RESULTS = [{"tool": "get_ro_state",
                "result": {"ro_number": "RO-26-08165", "hours_booked": 1.9,
                           "flat_rate_total": 2.4, "citations": ["EV-ABC"]}}]

    def test_faithful_answer_passes(self):
        assert check_grounding("RO-26-08165 has 1.9 hours booked against 2.4.", self.RESULTS) == []

    def test_invented_decimal_caught(self):
        # Booked hours are decimals - a digits-only check would miss this.
        assert check_grounding("It has 7.4 hours booked.", self.RESULTS)

    def test_invented_integer_caught(self):
        assert check_grounding("There are 38 vehicles blocked.", self.RESULTS)

    def test_invented_ro_caught(self):
        assert check_grounding("RO-26-09999 is ready.", self.RESULTS)

    def test_citations_collected(self):
        assert "EV-ABC" in _collect_citations(self.RESULTS)


class TestToolErrorHandling:
    def test_unknown_tool(self):
        assert "unknown tool" in call("nope")["error"]

    def test_unknown_ro_is_a_message_not_a_crash(self):
        r = call("get_ro_state", ro_number="RO-99-99999")
        # A healthy "no such repair order" carries BOTH found=False and a
        # human-readable `error`, so the presence of `error` proves nothing. What
        # separates the two cases is `found`: a real answer has it, and a result
        # that call() built from a caught exception does not.
        #
        # This was one line - an index into ["found"] - so an empty database
        # raised KeyError at the test and threw away the diagnosis the tool had
        # already produced: "no such table: ros".
        assert "found" in r, f"the tool raised instead of reporting: {r.get('error')}"
        assert r["found"] is False, r

    def test_bad_arguments(self):
        assert "error" in call("get_ro_state", wrong_arg="x")
