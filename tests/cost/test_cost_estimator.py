
import math
import unittest

from cost.estimator import (
    CPU_POWER_W, NON_LLM_LATENCY_MS, RAG_CONTEXT_TOKENS, REASONING_MULTIPLIER_HIGH,
    CostEstimate, estimate_tier, estimate_tokens, runtime_overhead_wh,
)
from cost.model_registry import MODEL_CATALOG
from policy.schemas import MethodTier as T, RequestType as R

SMALL, MEDIUM, LARGE = sorted(MODEL_CATALOG, key=lambda m: m.capability_score)


def est(tier=T.LLM_LOW_REASONING, chars=4000, model=SMALL, out=1000, rt=R.UNKNOWN):
    return estimate_tier(tier, "a" * chars, model, rt, out)


class TestTokens(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(estimate_tokens("abcd"), 1)
        self.assertEqual(estimate_tokens("abcde"), 2)
        self.assertEqual(estimate_tokens("a" * 400), 100)

    def test_empty_is_at_least_one(self):
        self.assertEqual(estimate_tokens(""), 1)

    def test_non_ascii_not_undercounted(self):
        self.assertGreater(estimate_tokens("日" * 4), estimate_tokens("a" * 4))

    def test_lone_surrogate_does_not_crash(self):
        self.assertGreaterEqual(estimate_tokens("\ud800" * 10), 1)

    def test_non_string_rejected(self):
        for bad in (None, 5, b"abc", ["a"]):
            with self.assertRaises(TypeError):
                estimate_tokens(bad)


class TestInterpolation(unittest.TestCase):
    def test_exact_anchor(self):
        e = est()  # 1000 in + 1000 out = anchor 2 of nano
        self.assertEqual(e.range_status, "in_range")
        self.assertAlmostEqual(e.tier_estimate.est_energy_wh, 0.575, places=6)
        self.assertAlmostEqual(e.wh_low, 0.575 - 0.108, places=6)
        self.assertAlmostEqual(e.wh_high, 0.575 + 0.108, places=6)

    def test_midpoint_between_anchors(self):
        e = est(chars=800, out=1000)  # total 1200, halfway between 400 and 2000
        self.assertAlmostEqual(e.tier_estimate.est_energy_wh, 0.391, places=6)
        self.assertAlmostEqual(e.wh_low, 0.391 - 0.0775, places=6)
        self.assertAlmostEqual(e.wh_high, 0.391 + 0.0775, places=6)

    def test_below_measured_range(self):
        e = est(chars=80, out=80)  # total 100 < 400
        self.assertEqual(e.range_status, "below_range")
        floor, prop = 0.207, 0.207 * 100 / 400
        self.assertAlmostEqual(e.tier_estimate.est_energy_wh, (floor + prop) / 2, places=6)
        self.assertAlmostEqual(e.wh_low, max(0.0, prop - 0.047), places=6)
        self.assertAlmostEqual(e.wh_high, floor + 0.047, places=6)
        self.assertTrue(e.notes)

    def test_above_measured_range(self):
        e = est(chars=4 * 30000, out=20000)  # total 50000 > 11500
        self.assertEqual(e.range_status, "above_range")
        slope = (0.827 - 0.575) / (11500 - 2000)
        self.assertAlmostEqual(e.tier_estimate.est_energy_wh, 0.827 + slope * (50000 - 11500), places=6)
        self.assertAlmostEqual(e.wh_low, 0.827 - 0.094, places=6)
        self.assertAlmostEqual(e.wh_high, 0.827 * 50000 / 11500 + 0.094, places=6)
        self.assertTrue(e.notes)

    def test_sweep_is_ordered_and_continuous(self):
        for m in MODEL_CATALOG:
            prev = 0.0
            for n in (1, 5, 50, 100, 399, 400, 1000, 2000, 5000, 11500, 20000, 100000):
                e = est(model=m, chars=4 * n, out=1)
                c = e.tier_estimate.est_energy_wh
                self.assertGreaterEqual(c, prev, (m.name, n))
                self.assertGreaterEqual(e.wh_low, 0.0)
                self.assertLessEqual(e.wh_low, c)
                self.assertLessEqual(c, e.wh_high)
                prev = c
            # no jump across the lowest anchor boundary (total 400 vs 399)
            a = est(model=m, chars=4 * 398, out=1).tier_estimate.est_energy_wh   # total 399
            b = est(model=m, chars=4 * 399, out=1).tier_estimate.est_energy_wh   # total 400
            self.assertLess(abs(b - a), 0.01)
            self.assertAlmostEqual(b, m.energy_anchors[0].wh, places=6)

    def test_bigger_model_costs_more_energy_same_request(self):
        whs = [est(model=m).tier_estimate.est_energy_wh for m in (SMALL, MEDIUM, LARGE)]
        self.assertEqual(whs, sorted(whs))


class TestReasoningAndDollars(unittest.TestCase):
    def test_high_reasoning_multiplier(self):
        lo = est(T.LLM_LOW_REASONING)
        hi = est(T.LLM_HIGH_REASONING)
        self.assertAlmostEqual(REASONING_MULTIPLIER_HIGH, 17.15 / 2.33, places=9)
        for a, b in ((lo.tier_estimate.est_energy_wh, hi.tier_estimate.est_energy_wh),
                     (lo.wh_low, hi.wh_low), (lo.wh_high, hi.wh_high),
                     (lo.tier_estimate.est_dollar_cost, hi.tier_estimate.est_dollar_cost),
                     (lo.tier_estimate.est_latency_ms, hi.tier_estimate.est_latency_ms)):
            self.assertAlmostEqual(b / a, REASONING_MULTIPLIER_HIGH, places=6)
        self.assertTrue(any("GPT-5" in n for n in hi.notes))

    def test_dollar_cost_uses_registry_price(self):
        e = est()  # 2000 tokens on nano at $0.0001 / 1k
        self.assertAlmostEqual(e.tier_estimate.est_dollar_cost, 0.0002, places=9)
        self.assertEqual(e.tier_estimate.est_latency_ms, SMALL.typical_latency_ms)
        self.assertEqual(e.tier_estimate.model_name, SMALL.name)

    def test_llm_tiers_require_a_model(self):
        for tier in (T.RAG_SMALL_MODEL, T.LLM_LOW_REASONING, T.LLM_HIGH_REASONING):
            with self.assertRaises(ValueError):
                estimate_tier(tier, "hi", None)


class TestNonLlmTiers(unittest.TestCase):
    def test_cpu_formula_and_shape(self):
        for tier in (T.CACHE, T.DETERMINISTIC, T.SMALL_CLASSIFIER):
            e = estimate_tier(tier, "hello", None)
            expected = CPU_POWER_W * NON_LLM_LATENCY_MS[tier] / 3_600_000
            self.assertAlmostEqual(e.tier_estimate.est_energy_wh, expected, places=12)
            self.assertGreater(e.tier_estimate.est_energy_wh, 0)   # nothing is free
            self.assertEqual(e.tier_estimate.est_dollar_cost, 0.0)
            self.assertIsNone(e.tier_estimate.model_name)
            self.assertEqual(e.range_status, "n/a")
            self.assertTrue(any("placeholder" in n for n in e.notes))

    def test_model_ignored_for_non_llm_tiers(self):
        e = estimate_tier(T.CACHE, "hello", LARGE)
        self.assertIsNone(e.tier_estimate.model_name)

    def test_ladder_is_ordered_cheapest_first(self):
        order = [estimate_tier(T.CACHE, "hi", None), estimate_tier(T.DETERMINISTIC, "hi", None),
                 estimate_tier(T.SMALL_CLASSIFIER, "hi", None),
                 estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL),
                 estimate_tier(T.LLM_HIGH_REASONING, "hi", SMALL)]
        whs = [o.tier_estimate.est_energy_wh for o in order]
        self.assertEqual(whs, sorted(whs))

    def test_rag_adds_context_cost(self):
        rag = estimate_tier(T.RAG_SMALL_MODEL, "hi", SMALL, R.LOOKUP)
        plain = estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, R.LOOKUP)
        self.assertGreater(rag.input_tokens, plain.input_tokens + RAG_CONTEXT_TOKENS - 1)
        self.assertGreater(rag.tier_estimate.est_energy_wh, plain.tier_estimate.est_energy_wh)
        self.assertGreater(rag.tier_estimate.est_latency_ms, plain.tier_estimate.est_latency_ms)


class TestValidation(unittest.TestCase):
    def test_bad_output_tokens_rejected(self):
        for bad in (-1, math.nan, math.inf, 1.5, "100", True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, R.UNKNOWN, bad)

    def test_zero_output_tokens_allowed(self):
        self.assertIsInstance(estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, R.UNKNOWN, 0), CostEstimate)

    def test_non_string_text_rejected(self):
        with self.assertRaises(TypeError):
            estimate_tier(T.CACHE, None, None)

    def test_unknown_tier_rejected(self):
        for bad in ("cache_lookup", None, 3):
            with self.assertRaises(ValueError):
                estimate_tier(bad, "hi", None)

    def test_default_output_length_is_conservative_when_unknown(self):
        outs = {rt: estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, rt).output_tokens for rt in R}
        self.assertEqual(outs[R.UNKNOWN], max(outs.values()))
        self.assertGreater(outs[R.GENERATION], outs[R.CLASSIFICATION])

    def test_explicit_output_overrides_default(self):
        self.assertEqual(estimate_tier(T.LLM_LOW_REASONING, "hi", SMALL, R.GENERATION, 7).output_tokens, 7)

    def test_result_is_immutable(self):
        e = est()
        with self.assertRaises(Exception):
            e.wh_low = 0.0


class TestRuntimeOverhead(unittest.TestCase):
    def test_sums_stages(self):
        one = runtime_overhead_wh(["stage0_screen"])
        two = runtime_overhead_wh(["stage0_screen", "stage1_policy"])
        self.assertGreater(one, 0)
        self.assertGreater(two, one)

    def test_empty_is_zero(self):
        self.assertEqual(runtime_overhead_wh([]), 0.0)

    def test_unknown_stage_and_bare_string_rejected(self):
        with self.assertRaises(ValueError):
            runtime_overhead_wh(["stage99"])
        with self.assertRaises(TypeError):
            runtime_overhead_wh("stage0_screen")


if __name__ == "__main__":
    unittest.main()
