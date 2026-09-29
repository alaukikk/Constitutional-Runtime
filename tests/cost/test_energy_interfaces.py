
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from audit import audit_log
from cost.model_registry import MODEL_CATALOG, EnergyAnchor, ModelInfo
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate


class TestSchemaEnergy(unittest.TestCase):
    def test_energy_field_exists_and_defaults_to_zero(self):
        est = TierCostEstimate(tier=MethodTier.CACHE)
        self.assertEqual(est.est_energy_wh, 0.0)

    def test_old_positional_construction_still_works(self):
        est = TierCostEstimate(MethodTier.LLM_LOW_REASONING, "m", 0.5, 100.0)
        self.assertEqual((est.est_dollar_cost, est.est_latency_ms), (0.5, 100.0))
        self.assertEqual(est.est_energy_wh, 0.0)

    def test_energy_reaches_the_audit_log(self):
        est = TierCostEstimate(MethodTier.LLM_LOW_REASONING, "m", 0.5, 100.0, 1.5)
        dec = RoutingDecision(MethodTier.LLM_LOW_REASONING, "m", "because", est)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "log.jsonl"
            with mock.patch.object(audit_log, "LOG_PATH", path):
                audit_log.log_decision("s1", dec)
            entry = json.loads(path.read_text().strip())
        self.assertEqual(entry["decision"]["cost_estimate"]["est_energy_wh"], 1.5)


def good_kwargs(**over):
    kw = dict(name="x", provider="p", cost_per_1k_tokens=0.001,
              typical_latency_ms=100, capability_score=0.5,
              energy_anchors=(EnergyAnchor(100, 300, 0.2, 0.05),
                              EnergyAnchor(1000, 1000, 0.6, 0.1)),
              energy_source="test")
    kw.update(over)
    return kw


class TestRegistryEnergy(unittest.TestCase):
    def test_every_catalog_model_has_measured_anchors_and_a_source(self):
        for m in MODEL_CATALOG:
            self.assertGreaterEqual(len(m.energy_anchors), 2)
            self.assertTrue(m.energy_source.strip(), m.name)
            for a in m.energy_anchors:
                self.assertGreater(a.wh, 0)

    def test_catalog_matches_paper_values(self):
        # Guard against accidental edits: How Hungry is AI, Table 4.
        expected = {
            "stub-small":  [0.207, 0.575, 0.827],   # GPT-4.1 nano
            "stub-medium": [0.450, 1.545, 2.122],   # GPT-4.1 mini
            "stub-large":  [0.871, 3.161, 4.833],   # GPT-4.1
        }
        by_name = {m.name: m for m in MODEL_CATALOG}
        for name, whs in expected.items():
            self.assertEqual([a.wh for a in by_name[name].energy_anchors], whs)
            self.assertEqual([(a.input_tokens, a.output_tokens) for a in by_name[name].energy_anchors],
                             [(100, 300), (1000, 1000), (10000, 1500)])

    def test_bigger_models_cost_more_energy_at_every_anchor(self):
        by_cap = sorted(MODEL_CATALOG, key=lambda m: m.capability_score)
        for i in range(len(by_cap[0].energy_anchors)):
            whs = [m.energy_anchors[i].wh for m in by_cap]
            self.assertEqual(whs, sorted(whs))
            self.assertEqual(len(set(whs)), len(whs))

    def test_energy_data_is_required_so_omission_cannot_look_free(self):
        kw = good_kwargs(); del kw["energy_anchors"]
        with self.assertRaises(TypeError):
            ModelInfo(**kw)

    def test_bad_scalar_numbers_rejected(self):
        for field in ("cost_per_1k_tokens", "typical_latency_ms", "capability_score"):
            for bad in (-1.0, math.nan, math.inf):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(ValueError):
                        ModelInfo(**good_kwargs(**{field: bad}))

    def test_bad_anchor_values_rejected(self):
        for bad in (-1.0, math.nan, math.inf, 0.0):
            with self.subTest(wh=bad):
                with self.assertRaises(ValueError):
                    EnergyAnchor(100, 300, bad, 0.0)
        for kwargs in (dict(input_tokens=-1, output_tokens=300, wh=1, wh_std=0),
                       dict(input_tokens=100, output_tokens=math.nan, wh=1, wh_std=0),
                       dict(input_tokens=0, output_tokens=0, wh=1, wh_std=0),
                       dict(input_tokens=100, output_tokens=300, wh=1, wh_std=-0.1),
                       dict(input_tokens=100, output_tokens=300, wh=1, wh_std=math.nan)):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    EnergyAnchor(**kwargs)

    def test_needs_at_least_two_anchors_and_unique_sizes(self):
        one = (EnergyAnchor(100, 300, 0.2, 0.05),)
        with self.assertRaises(ValueError):
            ModelInfo(**good_kwargs(energy_anchors=one))
        with self.assertRaises(ValueError):
            ModelInfo(**good_kwargs(energy_anchors=()))
        dup = (EnergyAnchor(100, 300, 0.2, 0.05), EnergyAnchor(300, 100, 0.3, 0.05))
        with self.assertRaises(ValueError):   # same total tokens -> ambiguous
            ModelInfo(**good_kwargs(energy_anchors=dup))

    def test_anchors_are_sorted_by_total_tokens(self):
        shuffled = (EnergyAnchor(10000, 1500, 0.8, 0.1), EnergyAnchor(100, 300, 0.2, 0.05),
                    EnergyAnchor(1000, 1000, 0.6, 0.1))
        m = ModelInfo(**good_kwargs(energy_anchors=shuffled))
        totals = [a.input_tokens + a.output_tokens for a in m.energy_anchors]
        self.assertEqual(totals, sorted(totals))
        self.assertIsInstance(m.energy_anchors, tuple)

    def test_catalog_names_unique(self):
        names = [m.name for m in MODEL_CATALOG]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
