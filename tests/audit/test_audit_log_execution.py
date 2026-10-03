
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import audit_log
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate

ESTIMATE = {"est_energy_wh": 0.5, "est_energy_wh_high": 0.7, "est_dollar_cost": 0.001,
            "est_latency_ms": 200.0, "basis": "estimate of the withheld route; nothing executed"}


def decision():
    return RoutingDecision(MethodTier.CACHE, None, "r", TierCostEstimate(tier=MethodTier.CACHE))


class TestExecutionFields(unittest.TestCase):
    def log(self, **kwargs):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", path):
                audit_log.log_decision("s1", decision(), **kwargs)
            return json.loads(path.read_text().strip().splitlines()[-1])

    def test_old_call_style_still_works_and_new_fields_default_to_none(self):
        entry = self.log()
        self.assertIsNone(entry["execution"])
        self.assertIsNone(entry["withheld_route_estimate"])

    def test_each_execution_state_is_recorded(self):
        for state in audit_log.EXECUTION_STATES:
            with self.subTest(state=state):
                kwargs = {"execution": state}
                if state == "withheld_pending_confirmation":
                    kwargs["withheld_route_estimate"] = ESTIMATE
                self.assertEqual(self.log(**kwargs)["execution"], state)

    def test_withheld_estimate_is_recorded_separately_from_the_decision_cost(self):
        entry = self.log(execution="withheld_pending_confirmation", withheld_route_estimate=ESTIMATE)
        self.assertEqual(entry["withheld_route_estimate"], ESTIMATE)
        self.assertEqual(entry["decision"]["cost_estimate"]["est_energy_wh"], 0.0)
        self.assertEqual(entry["decision"]["cost_estimate"]["est_dollar_cost"], 0.0)

    def test_unknown_execution_state_fails_loud(self):
        for bad in ("done", "", "EXECUTED", 1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.log(execution=bad)

    def test_estimate_is_only_allowed_on_withheld_records(self):
        for state in (None, "executed", "blocked"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.log(execution=state, withheld_route_estimate=ESTIMATE)

    def test_nothing_is_written_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", path):
                with self.assertRaises(ValueError):
                    audit_log.log_decision("s1", decision(), execution="bogus")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
