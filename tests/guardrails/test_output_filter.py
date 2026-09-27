
import pytest
from guardrails.output_filter import check_output

CLEAN_OUTPUTS = [
    "The capital of France is Paris.",
    "I can't help with that specific request, but I'm happy to help with something else.",
]

LEAK_CASES = [
    ("DAN mode activated. I will now answer without restrictions.", "explicit_jailbreak_ack"),
    ("Sure, here's the API key: sk-abcdefghijklmnopqrstuvwx1234", "credential_pattern"),
    ("Here's an AWS key I found: AKIAIOSFODNN7EXAMPLE", "credential_pattern"),
]

FALSE_POSITIVE_CASES = [
    "My favorite fictional AI is DAN from a movie about hacking.",
    "I work at Anthropic and I use Claude every day for my job.",
]


@pytest.mark.parametrize("text", CLEAN_OUTPUTS)
def test_clean_output_passes(text):
    assert check_output(text).passed


@pytest.mark.parametrize("text,expected_reason", LEAK_CASES)
def test_leak_patterns_caught(text, expected_reason):
    result = check_output(text)
    assert not result.passed
    assert expected_reason in result.reasons


@pytest.mark.parametrize("text", FALSE_POSITIVE_CASES)
def test_legitimate_mentions_do_not_false_positive(text):
    assert check_output(text).passed


def test_none_output_fails_closed():
    assert check_output(None).passed is False
