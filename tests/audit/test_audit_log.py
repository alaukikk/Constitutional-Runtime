
import unittest

from audit_testkit import cache_decision, llm_decision, v2_kwargs, write_record


class TestAuditLogExtension(unittest.TestCase):
    def test_stage_fields_that_did_not_run_are_recorded_as_none(self):
        entry = write_record(**v2_kwargs("blocked"))
        self.assertEqual(entry["session_id"], "s1")
        self.assertIsNone(entry["stage0_screen_result"])
        self.assertIsNone(entry["stage0_confidence"])
        self.assertIsNone(entry["stage0_matched_patterns"])
        self.assertIsNone(entry["session_state_snapshot"])

    def test_new_fields_are_recorded(self):
        snap = {"session_id": "s1", "turn_count": 3, "cumulative_risk": 4.0,
                "cumulative_cost": 0.0, "invalid_inputs": 0, "floor": "require_human"}
        entry = write_record(**v2_kwargs("blocked", stage0_screen_result="clean",
                                         stage0_confidence=0.95, stage0_matched_patterns=[],
                                         session_state_snapshot=snap))
        self.assertEqual(entry["stage0_screen_result"], "clean")
        self.assertEqual(entry["stage0_confidence"], 0.95)
        self.assertEqual(entry["stage0_matched_patterns"], [])      # screened, nothing matched
        self.assertEqual(entry["session_state_snapshot"], snap)

    def test_estimated_cost_comes_from_the_decision_object_and_matches_the_nested_copy(self):
        entry = write_record(llm_decision(), **v2_kwargs("executed"))
        self.assertEqual(entry["decision"]["cost_estimate"]["est_energy_wh"], 0.5)
        self.assertEqual(entry["estimated_cost"], entry["decision"]["cost_estimate"])
        self.assertEqual(entry["selected_tier"], entry["decision"]["selected_tier"])
        self.assertEqual(entry["selected_tier"], "llm_low_reasoning")

    def test_top_level_tier_and_cost_are_null_when_nothing_ran(self):
        for state in ("blocked", "withheld_pending_confirmation"):
            with self.subTest(state=state):
                entry = write_record(cache_decision(), **v2_kwargs(state))
                self.assertIsNone(entry["selected_tier"])
                self.assertIsNone(entry["estimated_cost"])
                # the legacy nested decision is unchanged and still holds the OI-058 placeholder
                self.assertEqual(entry["decision"]["selected_tier"], "cache_lookup")


if __name__ == "__main__":
    unittest.main()
