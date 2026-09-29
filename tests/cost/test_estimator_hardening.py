
import unittest

from cost import estimator as est
from cost.model_registry import MODEL_CATALOG
from policy.schemas import MethodTier as T

SMALL = sorted(MODEL_CATALOG, key=lambda m: m.capability_score)[0]
LLM_TIERS = (T.RAG_SMALL_MODEL, T.LLM_LOW_REASONING, T.LLM_HIGH_REASONING)


class TestTokenHeuristicIsConservativeForNonEnglish(unittest.TestCase):
    def test_ascii_unchanged(self):
        self.assertEqual(est.estimate_tokens("a" * 400), 100)

    def test_at_least_one_token_per_non_ascii_char(self):
        for s in ("日" * 1000, "😀" * 1000, "नमस्ते" * 200):
            with self.subTest(sample=s[:3]):
                self.assertGreaterEqual(est.estimate_tokens(s), len(s))

    def test_mixed_text_adds_up(self):
        self.assertEqual(est.estimate_tokens("abcd" * 10 + "日" * 5), 10 + 5)

    def test_same_length_non_english_never_cheaper_than_english(self):
        self.assertGreater(est.estimate_tokens("日" * 100), est.estimate_tokens("a" * 100))

    def test_lone_surrogate_still_safe(self):
        self.assertGreaterEqual(est.estimate_tokens("ab\ud800cd"), 1)


class TestArgumentValidation(unittest.TestCase):
    def test_absurd_output_tokens_is_a_value_error(self):
        for tier in LLM_TIERS:
            with self.assertRaises(ValueError):
                est.estimate_tier(tier, "x", SMALL, expected_output_tokens=10**400)

    def test_cap_boundary(self):
        est.estimate_tier(T.LLM_LOW_REASONING, "x", SMALL,
                          expected_output_tokens=est.MAX_OUTPUT_TOKENS)
        with self.assertRaises(ValueError):
            est.estimate_tier(T.LLM_LOW_REASONING, "x", SMALL,
                              expected_output_tokens=est.MAX_OUTPUT_TOKENS + 1)

    def test_wrong_model_type_is_a_type_error(self):
        for tier in LLM_TIERS:
            for bad in ("stub-large", 42, object()):
                with self.subTest(tier=tier, bad=type(bad).__name__):
                    with self.assertRaises(TypeError):
                        est.estimate_tier(tier, "x", bad)

    def test_missing_model_is_still_a_value_error(self):
        for tier in LLM_TIERS:
            with self.assertRaises(ValueError):
                est.estimate_tier(tier, "x", None)


class TestBelowRangeSemantics(unittest.TestCase):
    def test_below_range_estimate_is_bracketed_and_below_first_anchor(self):
        r = est.estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, expected_output_tokens=10)
        first = SMALL.energy_anchors[0].wh
        self.assertEqual(r.range_status, "below_range")
        self.assertLessEqual(r.wh_low, r.tier_estimate.est_energy_wh)
        self.assertLessEqual(r.tier_estimate.est_energy_wh, r.wh_high)
        self.assertLess(r.tier_estimate.est_energy_wh, first)     # no inflated baseline
        self.assertGreaterEqual(r.wh_high, first)                 # but the measured floor is still an upper bound
        self.assertTrue(any("headline" in n for n in r.notes))

    def test_in_range_is_labelled_in_range(self):
        r = est.estimate_tier(T.LLM_LOW_REASONING, "a" * 4000, SMALL, expected_output_tokens=1000)
        self.assertEqual(r.range_status, "in_range")

    def test_estimate_is_continuous_across_the_lower_boundary(self):
        first = SMALL.energy_anchors[0]
        just_below = est.estimate_tier(T.LLM_LOW_REASONING, "a" * 4, SMALL,
                                       expected_output_tokens=first.total_tokens - 2)
        at_edge = est.estimate_tier(T.LLM_LOW_REASONING, "a" * 4, SMALL,
                                    expected_output_tokens=first.total_tokens - 1)
        self.assertAlmostEqual(just_below.tier_estimate.est_energy_wh,
                               at_edge.tier_estimate.est_energy_wh, delta=0.01)


if __name__ == "__main__":
    unittest.main()
