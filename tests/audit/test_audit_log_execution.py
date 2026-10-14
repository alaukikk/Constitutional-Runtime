
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import audit_log
from audit_testkit import cache_decision, no_text_evidence, v2_kwargs, write_record

ESTIMATE = {"est_energy_wh": 0.5, "est_energy_wh_high": 0.7, "est_dollar_cost": 0.001,
            "est_latency_ms": 200.0, "basis": "estimate of the withheld route; nothing executed"}


class TestExecutionFields(unittest.TestCase):
    def log(self, execution, **over):
        return write_record(cache_decision(), **v2_kwargs(execution, **over))

    def test_execution_is_a_required_argument(self):
        with self.assertRaises(TypeError):
            write_record(cache_decision(), request_evidence=no_text_evidence(), outcome_reason="x")

    def test_withheld_estimate_defaults_to_none(self):
        self.assertIsNone(self.log("blocked")["withheld_route_estimate"])

    def test_each_execution_state_is_recorded_with_its_final_outcome(self):
        expected = {"executed": "released", "blocked": "blocked",
                    "withheld_pending_confirmation": "pending_confirmation",
                    "executed_withheld": "withheld"}
        self.assertEqual(set(expected), set(audit_log.EXECUTION_STATES))
        for state in audit_log.EXECUTION_STATES:
            with self.subTest(state=state):
                over = {"withheld_route_estimate": ESTIMATE} if state == "withheld_pending_confirmation" else {}
                entry = self.log(state, **over)
                self.assertEqual(entry["execution"], state)
                self.assertEqual(entry["final_outcome"], expected[state])

    def test_withheld_estimate_is_recorded_separately_from_the_decision_cost(self):
        entry = self.log("withheld_pending_confirmation", withheld_route_estimate=ESTIMATE)
        self.assertEqual(entry["withheld_route_estimate"], ESTIMATE)
        self.assertEqual(entry["decision"]["cost_estimate"]["est_energy_wh"], 0.0)
        self.assertEqual(entry["decision"]["cost_estimate"]["est_dollar_cost"], 0.0)
        self.assertIsNone(entry["estimated_cost"])      # nothing ran: no estimate presented as spend

    def test_unknown_or_missing_execution_state_fails_loud(self):
        for bad in ("done", "", "EXECUTED", 1, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                write_record(cache_decision(), **{**v2_kwargs("blocked"), "execution": bad})

    def test_estimate_is_only_allowed_on_withheld_records(self):
        for state in ("executed", "blocked", "executed_withheld"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.log(state, withheld_route_estimate=ESTIMATE)

    def test_nothing_is_written_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", path):
                with self.assertRaises(ValueError):
                    audit_log.log_decision("s1", cache_decision(),
                                           **{**v2_kwargs("blocked"), "execution": "bogus"})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
