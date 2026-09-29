
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import audit_log
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate


class TestAuditLogExtension(unittest.TestCase):
    def _read_last(self, path):
        return json.loads(Path(path).read_text().strip().splitlines()[-1])

    def test_old_call_style_still_works(self):
        dec = RoutingDecision(MethodTier.CACHE, None, "r", TierCostEstimate(tier=MethodTier.CACHE))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", p):
                audit_log.log_decision("s1", dec)   # no new kwargs
            entry = self._read_last(p)
        self.assertEqual(entry["session_id"], "s1")
        self.assertIsNone(entry.get("stage0_screen_result"))
        self.assertIsNone(entry.get("session_state_snapshot"))

    def test_new_fields_are_recorded(self):
        dec = RoutingDecision(MethodTier.CACHE, None, "r", TierCostEstimate(tier=MethodTier.CACHE))
        snap = {"session_id": "s1", "turn_count": 3, "cumulative_risk": 4.0,
                "cumulative_cost": 0.0, "invalid_inputs": 0, "floor": "require_human"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", p):
                audit_log.log_decision("s1", dec, stage0_screen_result="clean",
                                       session_state_snapshot=snap)
            entry = self._read_last(p)
        self.assertEqual(entry["stage0_screen_result"], "clean")
        self.assertEqual(entry["session_state_snapshot"], snap)

    def test_estimated_cost_still_comes_from_the_decision_object(self):
        est = TierCostEstimate(MethodTier.LLM_LOW_REASONING, "m", 0.01, 200.0, 0.5)
        dec = RoutingDecision(MethodTier.LLM_LOW_REASONING, "m", "r", est)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", p):
                audit_log.log_decision("s1", dec)
            entry = self._read_last(p)
        self.assertEqual(entry["decision"]["cost_estimate"]["est_energy_wh"], 0.5)


if __name__ == "__main__":
    unittest.main()
