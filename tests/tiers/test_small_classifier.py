
"""
Tests for tiers/small_classifier.py.

The inputs below are SMOKE checks written by the implementer in the same style
as the SYNTHETIC seed. They show the mechanics work (abstention, thresholds,
guards); they are NOT evidence of accuracy on real traffic.
"""
import unittest
from unittest import mock

from tiers import small_classifier as sc
from tiers import spam_seed_synthetic as seed
from tiers.spam_seed_synthetic import LABEL_HAM, LABEL_SPAM, SEED_EXAMPLES, SYNTHETIC
from triage.classifier import classify, is_cheap_tier_eligible

CLEAR_SPAM = "You have won a free prize, click this link now to claim your cash"
CLEAR_HAM = "Hi, the meeting agenda for tomorrow is attached, please review"
BORDERLINE = "please click the link to confirm the meeting time"


def lenient():
    """Abstain only on too-little-vocabulary, so predictions are visible."""
    return sc.SmallClassifier(abstain_below=0.5)


class TestSeedData(unittest.TestCase):
    def test_seed_is_labeled_synthetic(self):
        self.assertTrue(SYNTHETIC)
        self.assertIn("SYNTHETIC", seed.__doc__)

    def test_seed_is_balanced_two_class_and_deduplicated(self):
        labels = [label for _, label in SEED_EXAMPLES]
        self.assertEqual(set(labels), {LABEL_SPAM, LABEL_HAM})
        self.assertEqual(labels.count(LABEL_SPAM), labels.count(LABEL_HAM))
        texts = [" ".join(t.lower().split()) for t, _ in SEED_EXAMPLES]
        self.assertEqual(len(texts), len(set(texts)))


class TestExtraction(unittest.TestCase):
    def test_accepted_phrasings(self):
        cases = {
            "is this spam: win a free prize": "win a free prize",
            "Is this spam? - win a free prize": "win a free prize",
            "classify this email as spam or not: hi there": "hi there",
            "Classify this as spam or ham: hi there": "hi there",
            "classify this message as spam or not spam: line one\nline two": "line one\nline two",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sc.extract_message(text), expected)

    def test_rejected_phrasings(self):
        for text in ["", "   ", "is this spam", "is this spam:", "is this spam:   ",
                     "what is the capital of Japan", "classify this email as spam or not",
                     "is  this spam: double space must not match", "tell me if this is spam: x",
                     None, 123, b"is this spam: x"]:
            with self.subTest(text=text):
                self.assertIsNone(sc.extract_message(text))


class TestAbstention(unittest.TestCase):
    def test_answers_clear_cases_when_lenient(self):
        c = lenient()
        self.assertEqual(c.predict(CLEAR_SPAM).label, LABEL_SPAM)
        self.assertEqual(c.predict(CLEAR_HAM).label, LABEL_HAM)

    def test_abstains_on_out_of_vocabulary_and_tiny_input(self):
        c = lenient()
        for text in ["zxqv wlkj plmn", "free", "hello", "", "   ", None, 123]:
            with self.subTest(text=text):
                self.assertIsNone(c.predict(text))

    def test_abstains_on_oversized_input(self):
        self.assertIsNone(lenient().predict(CLEAR_SPAM + " " + "word " * sc.MAX_INPUT_CHARS))

    def test_threshold_controls_abstention_at_the_measured_boundary(self):
        p = lenient().predict(BORDERLINE).probability
        self.assertLess(p, 1.0)
        above = sc.SmallClassifier(abstain_below=min(1.0, p + 0.01))
        below = sc.SmallClassifier(abstain_below=max(0.5, p - 0.01))
        self.assertIsNone(above.predict(BORDERLINE))
        self.assertIsNotNone(below.predict(BORDERLINE))

    def test_default_threshold_is_not_tuned_to_make_the_seed_look_good(self):
        # Documents the honest state: with a 72-example synthetic seed the model
        # is under-confident, so the placeholder default abstains often. The
        # default must not be lowered to hide that; calibrate on a separate set.
        self.assertEqual(sc.ABSTAIN_BELOW, 0.80)

    def test_min_known_terms_controls_abstention(self):
        strict = sc.SmallClassifier(abstain_below=0.5, min_known_terms=10_000)
        self.assertIsNone(strict.predict(CLEAR_SPAM))

    def test_never_returns_a_label_outside_the_training_labels(self):
        c = lenient()
        for text in [CLEAR_SPAM, CLEAR_HAM, BORDERLINE]:
            self.assertIn(c.predict(text).label, {LABEL_SPAM, LABEL_HAM})


class TestConstruction(unittest.TestCase):
    def test_bad_thresholds_rejected(self):
        for bad in (0, -0.1, 1.5, float("nan"), float("inf")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sc.SmallClassifier(abstain_below=bad)
        for bad in (True, "0.8", None):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                sc.SmallClassifier(abstain_below=bad)

    def test_bad_min_terms_rejected(self):
        for bad in (0, -1, 2.5, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sc.SmallClassifier(min_known_terms=bad)

    def test_needs_two_labels_with_two_examples_each(self):
        with self.assertRaises(ValueError):
            sc.SmallClassifier([("a b c", "spam"), ("d e f", "spam")])
        with self.assertRaises(ValueError):
            sc.SmallClassifier([("a b", "spam"), ("c d", "spam"), ("e f", "ham")])

    def test_malformed_examples_rejected(self):
        with self.assertRaises(TypeError):
            sc.SmallClassifier([("only text",)])
        with self.assertRaises(TypeError):
            sc.SmallClassifier([("text", 1), ("text2", 2)])

    def test_training_is_deterministic(self):
        a, b = lenient(), lenient()
        for text in [CLEAR_SPAM, CLEAR_HAM, BORDERLINE]:
            self.assertEqual(a.predict(text), b.predict(text))


class TestTierFunction(unittest.TestCase):
    def setUp(self):
        # The module default uses the strict placeholder threshold; swap in a
        # lenient instance so the end-to-end path is observable.
        self._patch = mock.patch.object(sc, "get_default_classifier", return_value=lenient())
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_end_to_end_answers(self):
        self.assertEqual(sc.try_small_classifier(f"is this spam: {CLEAR_SPAM}"), LABEL_SPAM)
        self.assertEqual(sc.try_small_classifier(f"classify this email as spam or not: {CLEAR_HAM}"), LABEL_HAM)

    def test_other_requests_return_none(self):
        for text in ["what is the capital of Japan", "2 + 2", "", "write a short story", None]:
            with self.subTest(text=text):
                self.assertIsNone(sc.try_small_classifier(text))

    def test_abstains_when_the_message_is_unclassifiable(self):
        self.assertIsNone(sc.try_small_classifier("is this spam: zxqv wlkj plmn"))

    def test_internal_errors_become_none_never_exceptions(self):
        with mock.patch.object(sc, "get_default_classifier", side_effect=RuntimeError("boom")):
            self.assertIsNone(sc.try_small_classifier(f"is this spam: {CLEAR_SPAM}"))
        broken = mock.Mock()
        broken.predict.side_effect = ValueError("bad vector")
        with mock.patch.object(sc, "get_default_classifier", return_value=broken):
            self.assertIsNone(sc.try_small_classifier(f"is this spam: {CLEAR_SPAM}"))


class TestUnreachableUntilOI031(unittest.TestCase):
    """If this fails, eligibility or the keyword vocabulary changed and this tier
    has silently become reachable from the live pipeline. That is the OI-031
    routing-policy decision: take it to the owner; do not just edit this test."""

    def test_every_accepted_request_is_not_cheap_tier_eligible(self):
        payloads = [CLEAR_SPAM, "what is the capital of France", "who is the president",
                    "define photosynthesis", "calculate 45 * 3", "how much is 20% of 500",
                    "write a short story", "capital of japan, sum of two numbers"]
        prefixes = ["is this spam: ", "Is This Spam? - ", "classify this email as spam or not: ",
                    "CLASSIFY THIS MESSAGE AS SPAM OR HAM: "]
        for prefix in prefixes:
            for payload in payloads:
                text = prefix + payload
                with self.subTest(text=text):
                    self.assertIsNotNone(sc.extract_message(text))
                    self.assertFalse(is_cheap_tier_eligible(classify(text)))


if __name__ == "__main__":
    unittest.main()
