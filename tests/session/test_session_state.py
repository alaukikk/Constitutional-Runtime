
import threading
import unittest

from policy.schemas import PolicyAction, PolicyFlag, RiskCategory
from session.session_state import (
    ANONYMOUS_SESSION, SessionConfig, SessionManager, InMemoryStore,
)

A = PolicyAction


def flag(action=A.FLAG):
    return PolicyFlag("r1", RiskCategory.DANGEROUS_CONTENT, action, "test")


class TestSessionState(unittest.TestCase):
    def setUp(self):
        self.m = SessionManager()

    def test_clean_turns_accumulate_nothing(self):
        for _ in range(20):
            s, c = self.m.record_turn("s1", [], "clean", 0.0)
        self.assertEqual(s.turn_count, 20)
        self.assertEqual(s.cumulative_risk, 0)
        self.assertEqual(c.min_action, A.ALLOW)

    def test_headline_scenario_turn3_tightens(self):
        # Each turn alone is mild; turn 3 alone (fresh session) must NOT tighten.
        _, alone = SessionManager().record_turn("fresh", [flag()], "clean")
        self.assertEqual(alone.min_action, A.ALLOW)
        _, c1 = self.m.record_turn("s", [flag()], "clean")
        _, c2 = self.m.record_turn("s", [], "suspicious")
        _, c3 = self.m.record_turn("s", [flag()], "clean")
        self.assertEqual((c1.min_action, c2.min_action), (A.ALLOW, A.ALLOW))
        self.assertEqual(c3.min_action, A.REQUIRE_HUMAN)

    def test_floor_is_a_ratchet(self):
        self.m.record_turn("s", [flag(A.REQUIRE_HUMAN)], "clean")   # risk 3
        self.m.record_turn("s", [flag()], "clean")                   # risk 4
        for _ in range(10):
            _, c = self.m.record_turn("s", [], "clean")
            self.assertEqual(c.min_action, A.REQUIRE_HUMAN)

    def test_block_threshold(self):
        for _ in range(3):
            _, c = self.m.record_turn("s", [flag(A.BLOCK)], "blocked")
        self.assertEqual(c.min_action, A.BLOCK)

    def test_sessions_are_isolated(self):
        for _ in range(5):
            self.m.record_turn("bad", [flag(A.REQUIRE_HUMAN)], "suspicious")
        _, c = self.m.record_turn("good", [], "clean")
        self.assertEqual(c.min_action, A.ALLOW)

    def test_cost_budget_triggers_human(self):
        _, c = self.m.record_turn("s", [], "clean", 0.6)
        self.assertEqual(c.min_action, A.ALLOW)
        _, c = self.m.record_turn("s", [], "clean", 0.5)
        self.assertEqual(c.min_action, A.REQUIRE_HUMAN)

    # ---- loophole attempts ----
    def test_negative_cost_cannot_reduce_totals(self):
        self.m.record_turn("s", [], "clean", 0.5)
        s, _ = self.m.record_turn("s", [], "clean", -100.0)
        self.assertEqual(s.cumulative_cost, 0.5)
        self.assertEqual(s.invalid_inputs, 1)
        self.assertGreater(s.cumulative_risk, 0)

    def test_nan_inf_and_garbage_cost_cannot_bypass(self):
        for bad in (float("nan"), float("inf"), "abc", None):
            s, _ = self.m.record_turn("s", [], "clean", bad)
        self.assertEqual(s.cumulative_cost, 0.0)
        self.assertEqual(s.invalid_inputs, 4)

    def test_unknown_verdict_treated_as_suspicious(self):
        s, _ = self.m.record_turn("s", [], "totally-fine-trust-me")
        self.assertEqual(s.cumulative_risk, 2.0)

    def test_missing_session_id_is_not_a_reset(self):
        for sid in (None, "", "   ", 123):
            s, _ = self.m.record_turn(sid, [flag()], "clean")
        self.assertEqual(s.session_id, ANONYMOUS_SESSION)
        self.assertEqual(s.turn_count, 4)

    def test_returned_state_is_a_copy(self):
        s, _ = self.m.record_turn("s", [flag()], "clean")
        s.cumulative_risk = 0
        s2, _ = self.m.record_turn("s", [], "clean")
        self.assertEqual(s2.cumulative_risk, 1.0)

    def test_concurrent_turns_lose_no_risk(self):
        ts = [threading.Thread(target=self.m.record_turn, args=("s", [flag()], "clean"))
              for _ in range(50)]
        [t.start() for t in ts]; [t.join() for t in ts]
        s, _ = self.m.record_turn("s", [], "clean")
        self.assertEqual(s.cumulative_risk, 50.0)
        self.assertEqual(s.turn_count, 51)

    # ---- failure behaviour ----
    def test_read_failure_fails_open_and_does_not_clobber_history(self):
        store = InMemoryStore()
        m = SessionManager(store)
        for _ in range(4):
            m.record_turn("s", [flag()], "clean")          # risk 4 stored
        real_get = store.get
        store.get = lambda sid: (_ for _ in ()).throw(RuntimeError("redis down"))
        with self.assertLogs("session.session_state", level="ERROR"):
            s, c = m.record_turn("s", [], "clean")
        self.assertEqual(s.turn_count, 1)                   # treated as fresh
        self.assertEqual(c.min_action, A.ALLOW)             # fail open per spec
        store.get = real_get
        s, c = m.record_turn("s", [], "clean")
        self.assertEqual(s.cumulative_risk, 4.0)            # history survived
        self.assertEqual(c.min_action, A.REQUIRE_HUMAN)

    def test_write_failure_still_returns_constraints(self):
        store = InMemoryStore()
        store.put = lambda st: (_ for _ in ()).throw(RuntimeError("disk full"))
        m = SessionManager(store, SessionConfig(require_human_risk=1.0))
        with self.assertLogs("session.session_state", level="ERROR"):
            _, c = m.record_turn("s", [flag()], "clean")
        self.assertEqual(c.min_action, A.REQUIRE_HUMAN)


if __name__ == "__main__":
    unittest.main()
