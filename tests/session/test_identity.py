
"""OI-013: server-issued session identity.

The tests state both what the module guarantees (forged / altered / foreign /
expired tokens never verify; clients cannot choose IDs) and what it does NOT
guarantee (a client can still mint new sessions, up to the rate limit), so the
residual limit stays visible instead of being forgotten.
"""
import pytest

from session.identity import EXPIRED, INVALID, SessionIdentity

SECRET = "unit-test-secret"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t
    def __call__(self):
        return self.t
    def advance(self, s):
        self.t += s


def make(clock=None, **kw):
    return SessionIdentity(SECRET, clock=clock or Clock(), **kw), (clock or None)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ident(clock):
    return SessionIdentity(SECRET, clock=clock, ttl_seconds=1000, issue_limit=3, issue_window_seconds=100)


def issue(ident, key="client-a"):
    r = ident.issue(key)
    assert r.ok, r.reason
    return r.session


# ---- round trip ----

def test_issued_token_verifies_and_returns_the_server_chosen_id(ident):
    s = issue(ident)
    v = ident.verify(s.token)
    assert v.ok and v.session_id == s.session_id and v.reason is None
    assert s.token.startswith("v1." + s.session_id + ".")


def test_session_ids_are_unique_and_long_enough(clock):
    ident = SessionIdentity(SECRET, clock=clock, issue_limit=500)
    ids = {ident.issue(f"c{i}").session.session_id for i in range(300)}
    assert len(ids) == 300
    assert all(len(i) >= 24 for i in ids)           # 144 bits, url-safe encoded


def test_expiry_is_reported_in_the_issue_result(ident, clock):
    s = issue(ident)
    assert s.expires_at == int(clock.t) + 1000


# ---- a client cannot choose, alter or forge a session ----

def test_client_chosen_id_is_rejected(ident):
    assert ident.verify("my-own-session-id").reason == INVALID
    assert ident.verify("v1.my-own-session-id.1800000000.signature").reason == INVALID


@pytest.mark.parametrize("which", ["sid", "issued", "sig"])
def test_altering_any_part_invalidates_the_token(ident, which):
    s = issue(ident)
    v, sid, issued, sig = s.token.split(".")
    parts = {"sid": sid, "issued": issued, "sig": sig}
    parts[which] = {"sid": "AAAA" + sid[4:], "issued": str(int(issued) + 1), "sig": sig[:-2] + "xx"}[which]
    forged = ".".join([v, parts["sid"], parts["issued"], parts["sig"]])
    assert forged != s.token
    assert ident.verify(forged).reason == INVALID


def test_swapping_in_another_sessions_signature_fails(ident):
    a, b = issue(ident, "a"), issue(ident, "b")
    franken = ".".join(a.token.split(".")[:3] + [b.token.split(".")[3]])
    assert ident.verify(franken).reason == INVALID


def test_token_from_another_secret_is_rejected(clock):
    other = SessionIdentity("a-different-secret", clock=clock)
    token = other.issue("x").session.token
    assert SessionIdentity(SECRET, clock=clock).verify(token).reason == INVALID


def test_ephemeral_secrets_do_not_cross_verify(clock):
    a, b = SessionIdentity(clock=clock), SessionIdentity(clock=clock)
    assert b.verify(a.issue("x").session.token).reason == INVALID
    assert a.verify(a.issue("x").session.token).ok


@pytest.mark.parametrize("bad", [None, "", "   ", 123, b"v1.a.1.b", ["v1"], {}, "v1", "v1.a.b", "v2.a.1.sig",
                                 "v1..1.sig", "v1.a..sig", "v1.a.1.", "v1.a.-5.sig", "v1.a.1.2.sig",
                                 "v1.a.\u00b2.sig", "x" * 1000])
def test_malformed_input_is_rejected_without_raising(ident, bad):
    r = ident.verify(bad)
    assert r.ok is False and r.reason == INVALID and r.session_id is None


def test_token_issued_in_the_future_is_rejected(ident, clock):
    token = issue(ident).token
    clock.advance(-5000)                                # verifier's clock is far behind the issue time
    assert ident.verify(token).reason == INVALID


def test_small_clock_skew_is_tolerated(ident, clock):
    token = issue(ident).token
    clock.advance(-30)
    assert ident.verify(token).ok


# ---- expiry ----

def test_token_expires_at_exactly_ttl(ident, clock):
    token = issue(ident).token
    clock.advance(999)
    assert ident.verify(token).ok
    clock.advance(1)
    r = ident.verify(token)
    assert r.ok is False and r.reason == EXPIRED


# ---- the residual limit, stated openly: a client can ask for NEW sessions ----

def test_a_client_can_still_mint_fresh_sessions_up_to_the_limit(ident):
    ids = [issue(ident, "same-client").session_id for _ in range(3)]
    assert len(set(ids)) == 3                         # each is a clean, unrelated session (OI-078)


def test_issuance_beyond_the_limit_is_refused(ident):
    for _ in range(3):
        issue(ident, "same-client")
    r = ident.issue("same-client")
    assert r.ok is False and r.reason == "rate_limited" and r.session is None


def test_the_window_slides(ident, clock):
    for _ in range(3):
        issue(ident, "c")
    assert ident.issue("c").reason == "rate_limited"
    clock.advance(100)
    assert ident.issue("c").ok


def test_clients_are_limited_independently(ident):
    for _ in range(3):
        issue(ident, "a")
    assert ident.issue("a").ok is False
    assert ident.issue("b").ok is True


def test_a_refused_issuance_does_not_consume_the_window(ident, clock):
    for _ in range(3):
        issue(ident, "c")
    for _ in range(10):
        assert ident.issue("c").reason == "rate_limited"
    clock.advance(100)                                # window fully past the three real issuances
    assert ident.issue("c").ok


# ---- bounded memory, fail closed ----

def test_full_table_of_live_clients_refuses_new_clients_instead_of_evicting(clock):
    ident = SessionIdentity(SECRET, clock=clock, max_tracked_clients=2, issue_window_seconds=100)
    issue(ident, "a"), issue(ident, "b")
    r = ident.issue("c")
    assert r.ok is False and r.reason == "issuer_busy"
    assert ident.issue("a").ok                         # existing clients are not evicted or reset


def test_expired_entries_are_purged_to_make_room(clock):
    ident = SessionIdentity(SECRET, clock=clock, max_tracked_clients=2, issue_window_seconds=100)
    issue(ident, "a"), issue(ident, "b")
    clock.advance(100)
    assert ident.issue("c").ok


@pytest.mark.parametrize("bad_key", [None, "", 5, b"x"])
def test_bad_client_key_refuses_issuance(ident, bad_key):
    r = ident.issue(bad_key)
    assert r.ok is False and r.reason == "issuance_error"


def test_an_internal_error_while_issuing_refuses(clock):
    def broken():
        raise RuntimeError("clock broke")
    ident = SessionIdentity(SECRET, clock=broken)
    r = ident.issue("c")
    assert r.ok is False and r.reason == "issuance_error"


def test_an_internal_error_while_verifying_rejects(clock):
    ident = SessionIdentity(SECRET, clock=clock)
    token = ident.issue("c").session.token
    ident._clock = lambda: (_ for _ in ()).throw(RuntimeError("clock broke"))
    assert ident.verify(token).ok is False


# ---- client key hashing and configuration ----

def test_client_key_is_a_stable_hash_not_the_address(ident):
    k = ident.client_key("203.0.113.9")
    assert k == ident.client_key("203.0.113.9") and k != ident.client_key("203.0.113.10")
    assert "203" not in k and len(k) == 32


def test_client_key_depends_on_the_secret(clock):
    assert SessionIdentity("s1", clock=clock).client_key("1.2.3.4") != SessionIdentity("s2", clock=clock).client_key("1.2.3.4")


@pytest.mark.parametrize("field", ["ttl_seconds", "issue_limit", "issue_window_seconds", "max_tracked_clients"])
@pytest.mark.parametrize("bad", [0, -1, 1.5, "10", None, True])
def test_bad_configuration_fails_loudly(field, bad):
    with pytest.raises(ValueError):
        SessionIdentity(SECRET, **{field: bad})


def test_non_string_secret_is_rejected():
    with pytest.raises(TypeError):
        SessionIdentity(12345)


def test_empty_secret_falls_back_to_an_ephemeral_one_with_a_warning(caplog):
    with caplog.at_level("WARNING", logger="session.identity"):
        SessionIdentity("")
    assert "SESSION_SECRET" in caplog.text
