
import unittest

from audit_testkit import llm_decision, v2_kwargs, write_record


class TestExecutedWithheldAndTrace(unittest.TestCase):
    def _write(self, execution, **kw):
        return write_record(llm_decision(), **v2_kwargs(execution, **kw))

    def test_new_state_is_recorded_and_keeps_the_spent_estimate(self):
        trace = {"repair_status": "exhausted", "final": "withheld_validation_failed"}
        e = self._write("executed_withheld", validation_trace=trace)
        self.assertEqual(e["execution"], "executed_withheld")
        self.assertEqual(e["validation_trace"], trace)
        self.assertEqual(e["decision"]["cost_estimate"]["est_energy_wh"], 0.5)   # not a zero placeholder

    def test_trace_allowed_on_executed(self):
        e = self._write("executed", validation_trace={"final": "released"})
        self.assertEqual(e["validation_trace"]["final"], "released")

    def test_trace_rejected_where_nothing_executed(self):
        for state in ("blocked", "withheld_pending_confirmation"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                self._write(state, validation_trace={"x": 1})

    def test_trace_defaults_to_none(self):
        e = self._write("executed")
        self.assertIsNone(e["validation_trace"])
        self.assertEqual(e["validation_result"], "not_run")

    def test_unknown_state_still_rejected(self):
        with self.assertRaises(ValueError):
            write_record(llm_decision(), **{**v2_kwargs("blocked"), "execution": "released_after_review"})


if __name__ == "__main__":
    unittest.main()
