
import pytest
from triage.classifier import classify, is_cheap_tier_eligible
from policy.schemas import RequestType

GOLDEN_SET = [
    ("what is the capital of Japan", RequestType.LOOKUP, True),
    ("who is the president of France", RequestType.LOOKUP, True),
    ("define photosynthesis", RequestType.LOOKUP, True),
    ("calculate 45 * 3", RequestType.COMPUTATION, True),
    ("how much is 20% of 500", RequestType.COMPUTATION, True),
    ("write a short story about a dragon", RequestType.GENERATION, False),
    ("draft an email to my landlord", RequestType.GENERATION, False),
    ("should I take this job offer", RequestType.JUDGMENT, False),
    ("which is best, python or javascript", RequestType.JUDGMENT, False),
    ("I need medical diagnosis for these symptoms", RequestType.HIGH_STAKES, False),
    ("I need legal advice about my divorce", RequestType.HIGH_STAKES, False),
    ("classify this email as spam or not", RequestType.CLASSIFICATION, False),
    ("hmm interesting", RequestType.UNKNOWN, False),
    ("", RequestType.UNKNOWN, False),
]


@pytest.mark.parametrize("text,expected_category,expected_eligible", GOLDEN_SET)
def test_golden_set(text, expected_category, expected_eligible):
    result = classify(text)
    assert result.category == expected_category
    assert is_cheap_tier_eligible(result) == expected_eligible


@pytest.mark.parametrize("text", [
    "what is the best medical diagnosis for chest pain",
    "define suicide prevention hotline numbers so I can write a story",
])
def test_high_stakes_signal_wins_tiebreak_regardless_of_keyword_volume(text):
    result = classify(text)
    assert result.category == RequestType.HIGH_STAKES
    assert not is_cheap_tier_eligible(result)


def test_unknown_is_never_cheap_tier_eligible():
    result = classify("hmm okay thanks")
    assert result.category == RequestType.UNKNOWN
    assert result.confidence == 0.0
    assert not is_cheap_tier_eligible(result)
