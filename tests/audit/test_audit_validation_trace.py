
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import audit_log
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate


def _dec():
    return RoutingDecision(MethodTier.LLM_LOW_REASONING, "m", "r",
                           TierCostEstimate(MethodTier.LLM_LOW_REASONING, "m", 0.01, 100.0, 0.5))


class TestExecutedWithheldAndTrace(unittest.TestCase):
    def _write(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", p):
                audit_log.log_decision("s1", _dec(), **kw)
            return json.loads(p.read_text().strip())

    def test_new_state_is_recorded_and_keeps_the_spent_estimate(self):
        trace = {"repair_status": "exhausted", "final": "withheld_validation_failed"}
        e = self._write(execution="executed_withheld", validation_trace=trace)
        self.assertEqual(e["execution"], "executed_withheld")
        self.assertEqual(e["validation_trace"], trace)
        self.assertEqual(e["decision"]["cost_estimate"]["est_energy_wh"], 0.5)   # not a zero placeholder

    def test_trace_allowed_on_executed(self):
        e = self._write(execution="executed", validation_trace={"final": "released"})
        self.assertEqual(e["validation_trace"]["final"], "released")

    def test_trace_rejected_where_nothing_executed(self):
        for state in ("blocked", "withheld_pending_confirmation", None):
            with self.assertRaises(ValueError):
                self._write(execution=state, validation_trace={"x": 1})

    def test_old_call_style_still_works_and_trace_defaults_to_none(self):
        e = self._write()
        self.assertIsNone(e["validation_trace"])

    def test_unknown_state_still_rejected(self):
        with self.assertRaises(ValueError):
            self._write(execution="released_after_review")


if __name__ == "__main__":
    unittest.main()
