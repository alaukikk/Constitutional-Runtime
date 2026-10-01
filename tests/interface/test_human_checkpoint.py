
import math
import threading

import pytest

from interface.human_checkpoint import (
    CheckpointManager, MAX_TOKEN_CHARS, confirmation_message,
)

SECRET = "x" * 32
SESSION = "s1"
TEXT = "I need legal advice about my lease"
RULES = ["HAC-001"]


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def mgr(clock):
    return CheckpointManager(secret=SECRET, ttl_seconds=300, now=clock)


def issue(m, session=SESSION, text=TEXT, rules=RULES):
    return m.issue(session, text, rules)


def check(m, token, session=SESSION, text=TEXT, rules=RULES):
    return m.verify_and_consume(token, session, text, rules)


def test_roundtrip_confirms_and_returns_a_short_audit_id(mgr):
    token = issue(mgr)
    result = check(mgr, token)
    assert result.ok and result.reason == "confirmed"
    assert result.nonce and result.nonce in token and len(result.nonce) == 8


def test_single_use(mgr):
    token = issue(mgr)
    assert check(mgr, token).ok
    second = check(mgr, token)
    assert not second.ok and second.reason == "replayed"


def test_wrong_text_is_rejected(mgr):
    token = issue(mgr)
    assert check(mgr, token, text=TEXT + " and my deposit").reason == "bad_signature"


def test_wrong_session_is_rejected(mgr):
    token = issue(mgr)
    assert check(mgr, token, session="other").reason == "bad_signature"


def test_different_rule_set_is_rejected_but_order_is_irrelevant(mgr):
    token = issue(mgr, rules=["A", "B"])
    assert check(mgr, token, rules=["A"]).reason == "bad_signature"
    assert check(mgr, token, rules=["A", "B", "C"]).reason == "bad_signature"
    assert check(mgr, token, rules=["B", "A"]).ok


def test_failed_attempts_do_not_burn_the_real_token(mgr):
    token = issue(mgr)
    assert not check(mgr, token, text="something else").ok
    assert check(mgr, token).ok


def test_expired_token_is_rejected(mgr, clock):
    token = issue(mgr)
    clock.t += 301
    assert check(mgr, token).reason == "expired"


def test_token_valid_right_up_to_expiry(mgr, clock):
    token = issue(mgr)
    clock.t += 299
    assert check(mgr, token).ok


def test_tampering_with_any_field_is_rejected(mgr):
    nonce, exp, mac = issue(mgr).split(".")
    flipped = ("0" if mac[0] != "0" else "1") + mac[1:]
    for forged in (f"{nonce}.{exp}.{flipped}",
                   f"{nonce}.{int(exp) + 10_000}.{mac}",           # extend the expiry
                   f"{'f' * len(nonce)}.{exp}.{mac}"):             # swap the nonce
        assert check(mgr, forged).reason == "bad_signature"


@pytest.mark.parametrize("bad", [
    "", "a.b", "a.b.c.d", "abc", "a.notanumber.c", "a..c", ".1.c", "a.١٢٣.c",
    "x" * (MAX_TOKEN_CHARS + 1), None, 123, b"a.1.c", ["a", "1", "c"],
])
def test_malformed_tokens_are_rejected_without_raising(mgr, bad):
    result = check(mgr, bad)
    assert not result.ok
    assert result.reason in {"malformed", "bad_signature"}


def test_non_ascii_signature_does_not_crash(mgr):
    nonce, exp, _ = issue(mgr).split(".")
    assert not check(mgr, f"{nonce}.{exp}.\u00e9\ud800").ok


def test_internal_error_fails_closed(mgr):
    token = issue(mgr)
    result = mgr.verify_and_consume(token, SESSION, TEXT, None)   # rule_ids not iterable
    assert not result.ok and result.reason == "verification_error"


def test_token_from_another_secret_is_rejected(clock):
    a = CheckpointManager(secret="a" * 32, now=clock)
    b = CheckpointManager(secret="b" * 32, now=clock)
    assert check(b, issue(a)).reason == "bad_signature"


def test_default_secret_is_random_per_manager(clock):
    a, b = CheckpointManager(now=clock), CheckpointManager(now=clock)
    assert a.secret_is_ephemeral and b.secret_is_ephemeral
    assert not check(b, issue(a)).ok
    assert check(a, issue(a)).ok


def test_weak_or_badly_typed_secret_rejected(clock):
    with pytest.raises(ValueError):
        CheckpointManager(secret="short", now=clock)
    with pytest.raises(TypeError):
        CheckpointManager(secret=12345678901234567890, now=clock)


@pytest.mark.parametrize("ttl", [0, -1, math.nan, math.inf])
def test_bad_ttl_rejected(ttl, clock):
    with pytest.raises(ValueError):
        CheckpointManager(secret=SECRET, ttl_seconds=ttl, now=clock)


@pytest.mark.parametrize("ttl", [True, "300"])
def test_badly_typed_ttl_rejected(ttl, clock):
    with pytest.raises(TypeError):
        CheckpointManager(secret=SECRET, ttl_seconds=ttl, now=clock)


def test_spent_store_is_bounded_fail_closed_and_self_pruning(clock):
    m = CheckpointManager(secret=SECRET, ttl_seconds=60, now=clock, max_spent=2)
    assert check(m, issue(m, text="a"), text="a").ok
    assert check(m, issue(m, text="b"), text="b").ok
    blocked = check(m, issue(m, text="c"), text="c")
    assert not blocked.ok and blocked.reason == "store_full"
    clock.t += 61                                    # old nonces can no longer matter
    assert check(m, issue(m, text="d"), text="d").ok


def test_concurrent_use_of_one_token_succeeds_exactly_once(mgr):
    token = issue(mgr)
    results = []

    def worker():
        results.append(check(mgr, token))

    threads = [threading.Thread(target=worker) for _ in range(30)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(r.ok for r in results) == 1


def test_confirmation_message_has_reasons_and_instructions_but_no_token():
    msg = confirmation_message(["High-stakes decision affecting a third party"], 300)
    assert "High-stakes decision" in msg
    assert "re-submit" in msg and "5 minutes" in msg
    assert "confirmation_token" in msg


def test_confirmation_message_handles_empty_reasons_and_short_ttl():
    msg = confirmation_message([], 30)
    assert "requires human review" in msg and "1 minute." in msg
