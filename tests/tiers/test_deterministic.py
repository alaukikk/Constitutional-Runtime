

import os
import pytest
from tiers.deterministic import try_deterministic

ARITHMETIC_CASES = [
    ("2 + 2", "4"), ("10 - 3", "7"), ("6 * 7", "42"), ("10 / 4", "2.5"),
    ("9 / 3", "3"), ("-5 + 3", "-2"), ("2.5 + 2.5", "5"), ("2+2", "4"), ("2   +   2", "4"),
]

# Phrasing widened in D1 (CP: deterministic tier). "what is 2 + 2?" used to fall through on purpose;
# it is now answered because the expression and its answer are unambiguous.
PHRASED_CASES = [
    ("what is 2 + 2?", "4"), ("calculate 45 * 3", "135"), ("what is 15 + 27", "42"),
    ("What's 100 - 37", "63"), ("please compute 6 * 7", "42"), ("how much is 20% of 500", "100"),
    ("20% of 500", "100"), ("12.5% of 80", "10"), ("what is 12 squared", "144"), ("12 squared", "144"),
    ("what is the square root of 144", "12"), ("0.1 + 0.2", "0.3"),
    ("99999999999999 * 99999999999999", "9999999999999800000000000001"),
]

FACT_CASES = [
    ("What is the capital of France?", "Paris"),
    ("what is the capital of france", "Paris"),
    ("WHAT IS THE CAPITAL OF FRANCE", "Paris"),
    ("How many days are in a week", "7"),
]

FALLS_THROUGH_CASES = [
    "5 / 0", "2 + 2 * 3", "what is 2 + 2 + 2", "1 / 3", "what is the square root of 2",
    "what is 2 + 2 and then double it", "convert 5 km to miles", "what is 5 squared plus 1",
    "what is the capital of germany", "what do you think about cats", "", "   ",
]

SECURITY_CASES = [
    "__import__('os').system('echo pwned')",
    "exec('import os; os.system(\"echo pwned\")')",
    "eval('1+1')",
    "() for () in ().__class__.__bases__[0].__subclasses__()",
]


@pytest.mark.parametrize("text,expected", ARITHMETIC_CASES)
def test_arithmetic(text, expected):
    assert try_deterministic(text) == expected


@pytest.mark.parametrize("text,expected", PHRASED_CASES)
def test_phrased_and_percent_and_powers(text, expected):
    assert try_deterministic(text) == expected


@pytest.mark.parametrize("text,expected", FACT_CASES)
def test_static_facts(text, expected):
    assert try_deterministic(text) == expected


@pytest.mark.parametrize("text", FALLS_THROUGH_CASES)
def test_falls_through_rather_than_guessing(text):
    assert try_deterministic(text) is None


@pytest.mark.parametrize("text", SECURITY_CASES)
def test_no_code_execution_on_adversarial_input(text):
    assert try_deterministic(text) is None


def test_no_side_effects_from_security_cases():
    for text in SECURITY_CASES:
        try_deterministic(text)
    assert not os.path.exists("pwned")
