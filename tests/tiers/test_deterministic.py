
import os
import pytest
from tiers.deterministic import try_deterministic

ARITHMETIC_CASES = [
    ("2 + 2", "4"), ("10 - 3", "7"), ("6 * 7", "42"), ("10 / 4", "2.5"),
    ("9 / 3", "3"), ("-5 + 3", "-2"), ("2.5 + 2.5", "5"), ("2+2", "4"), ("2   +   2", "4"),
]

FACT_CASES = [
    ("What is the capital of France?", "Paris"),
    ("what is the capital of france", "Paris"),
    ("WHAT IS THE CAPITAL OF FRANCE", "Paris"),
    ("How many days are in a week", "7"),
]

FALLS_THROUGH_CASES = [
    "what is 2 + 2?", "5 / 0", "2 + 2 * 3",
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
