
import math
import unittest
from types import SimpleNamespace

from audit import metrics as m

EXAMPLES = [("a1", "spam"), ("a2", "spam"), ("a3", "spam"), ("b1", "ham"), ("b2", "ham"), ("b3", "ham")]


def scripted(answers):
    """classify_fn that returns a scripted answer per text."""
    return lambda text: answers[text]


class TestAbstentionReport(unittest.TestCase):
    def test_counts_and_rates_with_wrong_answers_and_abstentions(self):
        fn = scripted({"a1": "spam", "a2": "spam", "a3": None,      # 2 right, 1 abstain
                       "b1": "ham", "b2": "spam", "b3": None})       # 1 right, 1 WRONG, 1 abstain
        r = m.evaluate_abstaining_classifier(fn, EXAMPLES, cpu_power_w=20.0)
        self.assertEqual((r.n, r.answered, r.abstained, r.correct, r.incorrect), (6, 4, 2, 3, 1))
        self.assertAlmostEqual(r.coverage, 4 / 6)
        self.assertAlmostEqual(r.abstention_rate, 2 / 6)
        self.assertEqual(r.escalation_rate, r.abstention_rate)
        self.assertAlmostEqual(r.accuracy_on_answered, 3 / 4)
        self.assertAlmostEqual(r.incorrect_answer_rate, 1 / 6)

    def test_precision_and_recall_count_abstentions_as_misses(self):
        fn = scripted({"a1": "spam", "a2": "spam", "a3": None,
                       "b1": "ham", "b2": "spam", "b3": None})
        r = m.evaluate_abstaining_classifier(fn, EXAMPLES, cpu_power_w=20.0)
        spam, ham = r.per_class["spam"], r.per_class["ham"]
        self.assertEqual((spam.support, spam.predicted, spam.true_positive), (3, 3, 2))
        self.assertAlmostEqual(spam.precision, 2 / 3)
        self.assertAlmostEqual(spam.recall, 2 / 3)
        self.assertEqual((ham.support, ham.predicted, ham.true_positive), (3, 1, 1))
        self.assertAlmostEqual(ham.precision, 1.0)
        self.assertAlmostEqual(ham.recall, 1 / 3)

    def test_always_abstaining_has_no_accuracy_and_no_precision(self):
        r = m.evaluate_abstaining_classifier(lambda t: None, EXAMPLES, cpu_power_w=20.0)
        self.assertIsNone(r.accuracy_on_answered)
        self.assertEqual(r.incorrect_answer_rate, 0.0)
        self.assertEqual(r.abstention_rate, 1.0)
        self.assertTrue(all(c.precision is None and c.recall == 0.0 for c in r.per_class.values()))

    def test_resource_numbers_and_the_estimate_formula(self):
        r = m.evaluate_abstaining_classifier(lambda t: "spam", EXAMPLES, cpu_power_w=20.0)
        self.assertGreaterEqual(r.mean_latency_ms, 0.0)
        self.assertGreaterEqual(r.p95_latency_ms, 0.0)
        self.assertGreaterEqual(r.total_cpu_ms, 0.0)
        self.assertAlmostEqual(r.estimated_cpu_wh, 20.0 * r.total_cpu_ms / 3_600_000.0)

    def test_validation(self):
        with self.assertRaises(TypeError):
            m.evaluate_abstaining_classifier("not callable", EXAMPLES, cpu_power_w=1.0)
        with self.assertRaises(ValueError):
            m.evaluate_abstaining_classifier(lambda t: None, [], cpu_power_w=1.0)
        with self.assertRaises(TypeError):
            m.evaluate_abstaining_classifier(lambda t: None, [("x", "")], cpu_power_w=1.0)
        with self.assertRaises(TypeError):
            m.evaluate_abstaining_classifier(lambda t: 5, EXAMPLES, cpu_power_w=1.0)
        for bad in (-1, math.nan, math.inf, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.evaluate_abstaining_classifier(lambda t: None, EXAMPLES, cpu_power_w=bad)


class TestRetrievalReport(unittest.TestCase):
    @staticmethod
    def hit(source):
        return SimpleNamespace(passage=SimpleNamespace(source=source))

    def test_hit_rate_mrr_and_abstention_behavior(self):
        results = {
            "q1": [self.hit("docs/A.md")],                                  # rank 1
            "q2": [self.hit("docs/X.md"), self.hit("docs/B.md")],           # rank 2
            "q3": [self.hit("docs/X.md")],                                  # miss
            "u1": [],                                                       # correct abstention
            "u2": [self.hit("docs/A.md")],                                  # false answer
        }
        cases = [("q1", "docs/A.md"), ("q2", "docs/B.md"), ("q3", "docs/C.md"),
                 ("u1", None), ("u2", None)]
        r = m.evaluate_retrieval(lambda q, k: results[q], cases, k=3)
        self.assertEqual((r.n_answerable, r.n_unanswerable), (3, 2))
        self.assertAlmostEqual(r.hit_rate_at_k, 2 / 3)
        self.assertAlmostEqual(r.mrr, (1.0 + 0.5 + 0.0) / 3)
        self.assertAlmostEqual(r.correct_abstention_rate, 0.5)
        self.assertAlmostEqual(r.false_answer_rate, 0.5)

    def test_missing_categories_report_none(self):
        r = m.evaluate_retrieval(lambda q, k: [], [("u", None)])
        self.assertIsNone(r.hit_rate_at_k)
        self.assertIsNone(r.mrr)
        self.assertEqual(r.correct_abstention_rate, 1.0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            m.evaluate_retrieval(lambda q, k: [], [])
        with self.assertRaises(ValueError):
            m.evaluate_retrieval(lambda q, k: [], [("q", None)], k=0)
        with self.assertRaises(TypeError):
            m.evaluate_retrieval(None, [("q", None)])


class TestSplitIntegrity(unittest.TestCase):
    def test_overlap_is_detected_after_normalization(self):
        train = ["Win a FREE prize now", "meeting at three"]
        with self.assertRaises(ValueError):
            m.assert_no_overlap(train, [("win   a free  PRIZE now", "spam")])

    def test_disjoint_sets_pass(self):
        m.assert_no_overlap(["win a free prize"], [("lunch tomorrow?", "ham")])

    def test_fingerprint_is_order_insensitive_and_content_sensitive(self):
        a = [("x y z", "spam"), ("p q r", "ham")]
        self.assertEqual(m.dataset_fingerprint(a), m.dataset_fingerprint(list(reversed(a))))
        self.assertEqual(m.dataset_fingerprint(a), m.dataset_fingerprint([("X  y Z", "spam"), ("p q r", "ham")]))
        self.assertNotEqual(m.dataset_fingerprint(a), m.dataset_fingerprint([("x y z", "ham"), ("p q r", "ham")]))
        self.assertNotEqual(m.dataset_fingerprint(a), m.dataset_fingerprint([("x y z", "spam")]))

    def test_synthetic_seed_never_overlaps_a_set_built_from_it(self):
        from tiers.spam_seed_synthetic import SEED_EXAMPLES
        with self.assertRaises(ValueError):
            m.assert_no_overlap([t for t, _ in SEED_EXAMPLES], [SEED_EXAMPLES[0]])


if __name__ == "__main__":
    unittest.main()
