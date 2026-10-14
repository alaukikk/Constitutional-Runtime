
"""CP-001: salted-HMAC request evidence, key handling, and verification of a supplied request."""
import hashlib
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import audit.request_evidence as re_mod
from audit import audit_log
from audit.request_evidence import (
    AVAILABLE, ENV_KEY, ENV_KEY_ID, NORMALIZATION_UNAVAILABLE, NOT_TEXT_INPUT, AuditConfigError,
    build_request_evidence, ensure_audit_ready, find_matching_records, matches_request,
    validate_request_evidence,
)
from guardrails.injection_screen import NORMALIZATION_VERSION, screen_request
from policy.schemas import MethodTier, RoutingDecision, TierCostEstimate

KEY = "test-only-audit-hmac-key-0123456789"     # same throwaway value the autouse fixture sets
REPO_ROOT = Path(__file__).resolve().parents[2]


def build(text="What is the capital of Japan?", **over):
    kw = {"normalization_version": NORMALIZATION_VERSION}
    kw.update(over)
    return build_request_evidence(text, **kw)


# ---------------------------------------------------------------- shape and digest

def test_available_evidence_has_the_documented_shape_and_never_holds_the_text():
    text = "What is the capital of Japan?"
    ev = build(text)
    assert set(ev) == re_mod.EVIDENCE_KEYS
    assert ev["status"] == AVAILABLE and ev["digest_alg"] == "hmac-sha256"
    assert ev["raw_text_stored"] is False
    assert ev["key_id"] == "test-key-1" and ev["normalization_version"] == NORMALIZATION_VERSION
    assert len(ev["digest"]) == 64 and len(ev["salt"]) == 32
    assert text not in json.dumps(ev) and "Japan" not in json.dumps(ev)
    validate_request_evidence(ev)


def test_digest_is_hmac_sha256_over_salt_then_utf8_normalized_text():
    text = "café ☃ snowman"
    ev = build(text)
    expected = hmac.new(KEY.encode(), bytes.fromhex(ev["salt"]) + text.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    assert ev["digest"] == expected


def test_normalized_char_len_counts_code_points_not_bytes():
    text = "café ☃ \U0001f600"          # 8 code points, 13 UTF-8 bytes
    assert len(text) == 8 and len(text.encode("utf-8")) != 8
    assert build(text)["normalized_char_len"] == 8


def test_every_record_gets_a_fresh_random_salt_so_equal_requests_do_not_share_a_digest():
    evs = [build("same request text") for _ in range(20)]
    assert len({e["salt"] for e in evs}) == 20
    assert len({e["digest"] for e in evs}) == 20


@pytest.mark.parametrize("status", [NOT_TEXT_INPUT, NORMALIZATION_UNAVAILABLE])
def test_unavailable_evidence_has_null_digest_salt_key_version_and_length(status):
    ev = build_request_evidence(None, normalization_version=None, status=status)
    assert ev["status"] == status and ev["raw_text_stored"] is False
    for k in ("digest", "salt", "key_id", "normalization_version", "normalized_char_len"):
        assert ev[k] is None
    validate_request_evidence(ev)


def test_unavailable_status_refuses_to_be_given_text_so_nothing_can_be_digested_by_accident():
    with pytest.raises(ValueError):
        build_request_evidence("attachment payload", normalization_version=None, status=NOT_TEXT_INPUT)


def test_unknown_status_and_missing_text_or_version_are_rejected():
    with pytest.raises(ValueError):
        build_request_evidence("x", normalization_version="1", status="whatever")
    with pytest.raises(ValueError):
        build(None)
    with pytest.raises(ValueError):
        build("")
    with pytest.raises(ValueError):
        build("x", normalization_version=None)


# ---------------------------------------------------------------- key handling

@pytest.mark.parametrize("env", [
    {ENV_KEY: None},                                            # missing key
    {ENV_KEY: ""},                                              # empty key
    {ENV_KEY: "short"},                                         # shorter than MIN_KEY_CHARS
    {ENV_KEY_ID: None},                                         # missing key id
    {ENV_KEY_ID: ""},
    {ENV_KEY_ID: "has space"},                                  # not the label alphabet
    {ENV_KEY_ID: "x" * 65},                                     # too long
])
def test_missing_or_bad_key_configuration_fails_loud_for_every_status(monkeypatch, env):
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(AuditConfigError):
        build("some text")
    with pytest.raises(AuditConfigError):
        build_request_evidence(None, normalization_version=None, status=NOT_TEXT_INPUT)
    with pytest.raises(AuditConfigError):
        ensure_audit_ready()


def test_no_fallback_digest_is_produced_when_the_key_is_missing(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    produced = []
    with pytest.raises(AuditConfigError):
        produced.append(build("some text"))
    assert produced == []


def test_key_is_read_at_write_time_not_import_time(monkeypatch):
    first = build("same text")
    monkeypatch.setenv(ENV_KEY, "a-completely-different-key-9876543210")
    monkeypatch.setenv(ENV_KEY_ID, "test-key-2")
    second = build("same text")
    assert first["key_id"] == "test-key-1" and second["key_id"] == "test-key-2"
    expected = hmac.new(b"a-completely-different-key-9876543210",
                        bytes.fromhex(second["salt"]) + b"same text", hashlib.sha256).hexdigest()
    assert second["digest"] == expected


def test_importing_the_module_needs_no_key():
    env = {k: v for k, v in os.environ.items() if k not in (ENV_KEY, ENV_KEY_ID)}
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run([sys.executable, "-c", "import audit.request_evidence, audit.audit_log"],
                          cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_salt_generation_failure_fails_loud_with_no_fallback(monkeypatch):
    def broken(_n):
        raise OSError("no entropy source")
    monkeypatch.setattr(re_mod.secrets, "token_bytes", broken)
    with pytest.raises(AuditConfigError):
        build("some text")


# ---------------------------------------------------------------- shape validation on write

def test_validate_rejects_anything_that_could_smuggle_content_or_break_the_schema():
    good = build("some text")
    for bad in (
        {**good, "extra": "x"},                                 # unknown key
        {**good, "raw_text_stored": True},
        {**good, "digest": "ABC"},
        {**good, "salt": "00"},
        {**good, "normalized_char_len": 0},
        {**good, "normalized_char_len": True},
        {**good, "status": "available_maybe"},
        {**good, "key_id": "bad id"},
        {k: v for k, v in good.items() if k != "salt"},
        {**build_request_evidence(None, normalization_version=None, status=NOT_TEXT_INPUT),
         "digest": "0" * 64},                                   # a digest on a non-text record
    ):
        with pytest.raises(ValueError):
            validate_request_evidence(bad)
    with pytest.raises(ValueError):
        validate_request_evidence("not a mapping")


# ---------------------------------------------------------------- verifying a supplied request

def evidence_for(raw_text):
    return build(screen_request(raw_text).normalized_text)


def test_a_reporter_supplied_request_matches_its_own_record_after_normalization():
    ev = evidence_for("  What is the capital​ of Japan?  ")
    assert matches_request(ev, "What is the capital of Japan?", KEY)
    assert matches_request(ev, "Ｗhat is the capital of Japan?", KEY)     # NFKC folds full-width W


def test_a_different_request_or_the_wrong_key_does_not_match():
    ev = evidence_for("What is the capital of Japan?")
    assert not matches_request(ev, "What is the capital of France?", KEY)
    assert not matches_request(ev, "What is the capital of Japan?", "some-other-key-0123456789abcdef")


def test_a_record_from_another_normalization_version_or_without_text_never_matches():
    ev = evidence_for("What is the capital of Japan?")
    assert not matches_request({**ev, "normalization_version": "0"}, "What is the capital of Japan?", KEY)
    none_ev = build_request_evidence(None, normalization_version=None, status=NOT_TEXT_INPUT)
    assert not matches_request(none_ev, "What is the capital of Japan?", KEY)


def test_scanning_a_log_finds_only_matching_version_2_records(tmp_path, monkeypatch):
    log = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log, "LOG_PATH", log)
    dec = RoutingDecision(MethodTier.CACHE, None, "r", TierCostEstimate(tier=MethodTier.CACHE))
    target = "My exact reported request"

    def write(text, session):
        audit_log.log_decision(
            session, dec, execution="blocked", outcome_reason="stage0_screen",
            request_evidence=build(screen_request(text).normalized_text))

    log.write_text(json.dumps({"timestamp": 1.0, "session_id": "old-v1-record"}) + "\n")   # version 1
    write("an unrelated request", "s-other")
    write(target, "s-match-1")
    monkeypatch.setenv(ENV_KEY, "rotated-key-for-later-records-12345")
    monkeypatch.setenv(ENV_KEY_ID, "test-key-2")
    write(target, "s-match-2")

    keys = {"test-key-1": KEY, "test-key-2": "rotated-key-for-later-records-12345"}
    hits = list(find_matching_records(target, keys, log))
    assert [h["session_id"] for h in hits] == ["s-match-1", "s-match-2"]
    assert all(h["final_outcome"] == "blocked" for h in hits)
    # with only the old key, the record signed by the rotated key cannot be matched
    assert [h["session_id"] for h in find_matching_records(target, {"test-key-1": KEY}, log)] == ["s-match-1"]
    assert list(find_matching_records("never logged", keys, log)) == []
