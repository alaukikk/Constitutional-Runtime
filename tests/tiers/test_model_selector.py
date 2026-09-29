
import math
import unittest
from dataclasses import replace

from cost.model_registry import EnergyAnchor, MODEL_CATALOG, ModelInfo
from policy.schemas import MethodTier as T, RequestType as R
from tiers import model_selector as ms

SMALL, MEDIUM, LARGE = sorted(MODEL_CATALOG, key=lambda m: m.capability_score)


def anchors(*vals):
    sizes = ((100, 300), (1000, 1000), (10000, 1500))
    return tuple(EnergyAnchor(i, o, w, 0.0) for (i, o), w in zip(sizes, vals))


# A crafted catalog where cheapest-by-energy and cheapest-by-dollar disagree,
# so the "objective" parameter actually gets exercised.
CHEAP_ENERGY_EXPENSIVE_DOLLAR = ModelInfo(
    "cheap-energy", "test", cost_per_1k_tokens=1.0, typical_latency_ms=100,
    capability_score=0.5, energy_anchors=anchors(0.1, 0.3, 0.5), energy_source="synthetic")
EXPENSIVE_ENERGY_CHEAP_DOLLAR = ModelInfo(
    "cheap-dollar", "test", cost_per_1k_tokens=0.0001, typical_latency_ms=100,
    capability_score=0.5, energy_anchors=anchors(0.9, 2.0, 3.0), energy_source="synthetic")
LOW_CAP = ModelInfo("low-cap", "test", 0.0001, 100, 0.1, anchors(0.01, 0.02, 0.03), "synthetic")
HIGH_CAP_EXPENSIVE = ModelInfo("high-cap", "test", 1.0, 500, 0.99, anchors(5, 10, 15), "synthetic")


class TestBasicSelection(unittest.TestCase):
    def test_no_floor_picks_cheapest_energy(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", catalog=MODEL_CATALOG)
        self.assertEqual(r.model.name, SMALL.name)
        self.assertFalse(r.escalated)

    def test_floor_restricts_to_qualifying_models(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", min_capability=0.6, catalog=MODEL_CATALOG)
        self.assertEqual(r.model.name, MEDIUM.name)   # cheapest of {medium, large}

    def test_floor_at_the_top_picks_the_largest(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", min_capability=0.9, catalog=MODEL_CATALOG)
        self.assertEqual(r.model.name, LARGE.name)
        self.assertFalse(r.escalated)

    def test_works_for_rag_tier(self):
        r = ms.select_model(T.RAG_SMALL_MODEL, "hello", catalog=MODEL_CATALOG)
        self.assertIn(r.model.name, {m.name for m in MODEL_CATALOG})


class TestEscalation(unittest.TestCase):
    def test_impossible_floor_escalates_to_best_available(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", min_capability=0.999, catalog=MODEL_CATALOG)
        self.assertTrue(r.escalated)
        self.assertEqual(r.model.name, LARGE.name)     # highest capability, not cheapest
        self.assertIn("escalat", r.rationale.lower())

    def test_escalation_never_picks_a_cheaper_low_capability_model(self):
        catalog = [LOW_CAP, HIGH_CAP_EXPENSIVE]
        r = ms.select_model(T.LLM_LOW_REASONING, "x", min_capability=0.999, catalog=catalog)
        self.assertEqual(r.model.name, "high-cap")     # not the cheap, incapable one


class TestSafetyProperty(unittest.TestCase):
    def test_cheap_incapable_model_never_beats_a_qualifying_one(self):
        # low-cap is far cheaper on every axis but doesn't meet the floor.
        catalog = [LOW_CAP, HIGH_CAP_EXPENSIVE]
        r = ms.select_model(T.LLM_LOW_REASONING, "x", min_capability=0.5, catalog=catalog)
        self.assertEqual(r.model.name, "high-cap")
        self.assertFalse(r.escalated)


class TestObjective(unittest.TestCase):
    def test_energy_and_dollar_objectives_can_disagree(self):
        catalog = [CHEAP_ENERGY_EXPENSIVE_DOLLAR, EXPENSIVE_ENERGY_CHEAP_DOLLAR]
        by_energy = ms.select_model(T.LLM_LOW_REASONING, "x", objective="energy", catalog=catalog)
        by_dollar = ms.select_model(T.LLM_LOW_REASONING, "x", objective="dollar", catalog=catalog)
        self.assertEqual(by_energy.model.name, "cheap-energy")
        self.assertEqual(by_dollar.model.name, "cheap-dollar")

    def test_unknown_objective_rejected(self):
        with self.assertRaises(ValueError):
            ms.select_model(T.LLM_LOW_REASONING, "x", objective="latency", catalog=MODEL_CATALOG)


class TestValidation(unittest.TestCase):
    def test_non_llm_tier_rejected(self):
        for tier in (T.CACHE, T.DETERMINISTIC, T.SMALL_CLASSIFIER):
            with self.assertRaises(ValueError):
                ms.select_model(tier, "x", catalog=MODEL_CATALOG)

    def test_empty_catalog_rejected(self):
        with self.assertRaises(ValueError):
            ms.select_model(T.LLM_LOW_REASONING, "x", catalog=[])

    def test_bad_catalog_entry_rejected(self):
        with self.assertRaises(TypeError):
            ms.select_model(T.LLM_LOW_REASONING, "x", catalog=[SMALL, "not-a-model"])

    def test_non_finite_capability_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                ms.select_model(T.LLM_LOW_REASONING, "x", min_capability=bad, catalog=MODEL_CATALOG)

    def test_bool_capability_rejected(self):
        with self.assertRaises(TypeError):
            ms.select_model(T.LLM_LOW_REASONING, "x", min_capability=True, catalog=MODEL_CATALOG)

    def test_negative_capability_is_a_no_op_floor(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "x", min_capability=-5, catalog=MODEL_CATALOG)
        self.assertEqual(r.model.name, SMALL.name)


class TestDeterminism(unittest.TestCase):
    def test_repeated_calls_agree(self):
        results = {ms.select_model(T.LLM_LOW_REASONING, "hello world", catalog=MODEL_CATALOG).model.name
                   for _ in range(20)}
        self.assertEqual(len(results), 1)

    def test_energy_tie_breaks_toward_least_overqualified_then_name(self):
        a = ModelInfo("tie-a", "test", 0.001, 100, 0.5, anchors(0.2, 0.6, 1.0), "synthetic")
        b = ModelInfo("tie-b", "test", 0.001, 100, 0.7, anchors(0.2, 0.6, 1.0), "synthetic")
        r = ms.select_model(T.LLM_LOW_REASONING, "x", catalog=[b, a])
        self.assertEqual(r.model.name, "tie-a")   # same cost, lower capability = less overqualified


class TestAlternatives(unittest.TestCase):
    def test_every_candidate_appears_once(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", catalog=MODEL_CATALOG)
        self.assertEqual({a.model_name for a in r.alternatives}, {m.name for m in MODEL_CATALOG})

    def test_alternatives_sorted_cheapest_first_by_objective(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", objective="energy", catalog=MODEL_CATALOG)
        vals = [a.estimate.tier_estimate.est_energy_wh for a in r.alternatives]
        self.assertEqual(vals, sorted(vals))

    def test_alternatives_record_whether_each_met_the_floor(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", min_capability=0.6, catalog=MODEL_CATALOG)
        met = {a.model_name: a.meets_capability for a in r.alternatives}
        self.assertFalse(met[SMALL.name])
        self.assertTrue(met[MEDIUM.name])
        self.assertTrue(met[LARGE.name])

    def test_alternatives_are_immutable(self):
        r = ms.select_model(T.LLM_LOW_REASONING, "hello", catalog=MODEL_CATALOG)
        self.assertIsInstance(r.alternatives, tuple)
        with self.assertRaises(Exception):
            r.alternatives[0].model_name = "changed"


if __name__ == "__main__":
    unittest.main()
