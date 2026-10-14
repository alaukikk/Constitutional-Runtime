
"""
audit/request_evidence.py -- salted-HMAC evidence of a text request, for the Stage 7 audit
record (schema v2, CP-001). The permanent audit log never stores request content; this module
produces the content-free `request_evidence` object that stands in for it.

WHAT IT PROVIDES
    digest = HMAC-SHA-256(key, salt_bytes || UTF-8(normalized_text))
    * `salt` is 16 cryptographically random bytes, fresh for EVERY record, so equal requests
      give unrelated digests and digests cannot be compared across records. The fixed salt
      length makes the concatenation unambiguous.
    * The text digested is the Stage 0 NORMALIZED text (the text that drives policy and
      routing), never the raw request. `normalized_char_len` counts Unicode code points.
    * A reporter who supplies a request can be matched against the log by recomputing the
      digest for each record (matches_request / find_matching_records). That needs the key
      whose `key_id` the record names; keep old keys for as long as records are retained.

WHAT IT DOES NOT PROVIDE (CP-001 A.2, A.5)
    * It does not make a request recoverable from the log, and it cannot help with a request
      that was never flagged and is not supplied again by a reporter.
    * An attacker holding BOTH the key and the log can test guesses against single records.
      Key compromise and key loss are real risks; the key is configuration, not log content.

KEY HANDLING (owner decision, CP-001 Part C #4)
    AUDIT_HMAC_KEY and AUDIT_HMAC_KEY_ID are read from the environment at WRITE time, never at
    import. A missing or malformed key, or a failure to generate a salt, raises
    AuditConfigError. There is deliberately NO fallback: no plain SHA-256, no per-process random
    key, no omitted digest. Every audit write needs a valid key configuration -- including
    records that carry no digest (non-text refusals) -- so a misconfigured deployment fails on
    its first request rather than only when a text request happens to arrive. [JUDGMENT]
    The key must also be at least MIN_KEY_CHARS characters, so an empty or trivial placeholder
    cannot silently weaken every digest. [JUDGMENT, placeholder length]

STATUS (frozen schema in ARCHITECTURE.md Stage 7)
    available                  digest computed over normalized text
    not_text_input             non-text ingress refusal; attachment payloads are never digested
    normalization_unavailable  no usable normalized text: Stage 0 failed, the input was empty, or
                               it was oversized (Stage 0 truncates oversized input, and a digest
                               of a truncated text could not be matched against the full request)
    For the last two, digest, salt, key_id, normalization_version and normalized_char_len are null.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Optional

ENV_KEY = "AUDIT_HMAC_KEY"
ENV_KEY_ID = "AUDIT_HMAC_KEY_ID"

DIGEST_ALG = "hmac-sha256"
SALT_BYTES = 16
MIN_KEY_CHARS = 16          # [JUDGMENT] placeholder; see module docstring

AVAILABLE = "available"
NOT_TEXT_INPUT = "not_text_input"
NORMALIZATION_UNAVAILABLE = "normalization_unavailable"
STATUSES = (AVAILABLE, NOT_TEXT_INPUT, NORMALIZATION_UNAVAILABLE)

EVIDENCE_KEYS = frozenset({
    "digest_alg", "digest", "salt", "key_id", "normalization_version",
    "normalized_char_len", "raw_text_stored", "status",
})

# Key IDs are labels, not content: a short, boring character set keeps request text out of them.
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_SALT_RE = re.compile(r"^[0-9a-f]{%d}$" % (SALT_BYTES * 2))


class AuditConfigError(RuntimeError):
    """The audit HMAC configuration is missing or unusable. Audit writes must fail loudly."""


def _check_key(key: object, key_id: object) -> tuple[bytes, str]:
    if not isinstance(key, str) or len(key) < MIN_KEY_CHARS:
        raise AuditConfigError(
            f"{ENV_KEY} is missing or shorter than {MIN_KEY_CHARS} characters; "
            f"refusing to write an audit record without a usable HMAC key")
    if not isinstance(key_id, str) or not _KEY_ID_RE.match(key_id):
        raise AuditConfigError(
            f"{ENV_KEY_ID} is missing or invalid (1-64 characters from A-Z a-z 0-9 . _ : -); "
            f"refusing to write an audit record without a key id")
    return key.encode("utf-8"), key_id


def load_hmac_config() -> tuple[bytes, str]:
    """(key bytes, key id) from the environment, read now -- never cached, never at import."""
    return _check_key(os.environ.get(ENV_KEY), os.environ.get(ENV_KEY_ID))


def ensure_audit_ready() -> None:
    """Raise AuditConfigError unless the HMAC configuration is usable. Cheap; call it before
    doing work or consuming single-use state, so a misconfiguration fails the request up front
    instead of after an answer was generated."""
    load_hmac_config()


def _compute(key: bytes, salt: bytes, normalized_text: str) -> str:
    return hmac.new(key, salt + normalized_text.encode("utf-8"), hashlib.sha256).hexdigest()


def build_request_evidence(normalized_text: Optional[str], *,
                           normalization_version: Optional[str],
                           status: str = AVAILABLE) -> dict:
    """Build the `request_evidence` object for ONE audit record.

    `normalized_text` is only read to compute the digest and its length; it is not kept in the
    returned object. Raises AuditConfigError when the key configuration is unusable or a secure
    salt cannot be generated (checked for every status, see module docstring).
    """
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    key, key_id = load_hmac_config()

    evidence = {
        "digest_alg": DIGEST_ALG, "digest": None, "salt": None, "key_id": None,
        "normalization_version": None, "normalized_char_len": None,
        "raw_text_stored": False, "status": status,
    }
    if status != AVAILABLE:
        if normalized_text is not None:
            raise ValueError(f"status {status!r} must not be given any text")
        return evidence

    if not isinstance(normalized_text, str) or not normalized_text:
        raise ValueError("an 'available' request evidence needs non-empty normalized text")
    if not isinstance(normalization_version, str) or not normalization_version:
        raise ValueError("an 'available' request evidence needs a normalization_version")
    try:
        salt = secrets.token_bytes(SALT_BYTES)
    except Exception as exc:   # NotImplementedError / OSError from the OS entropy source
        raise AuditConfigError("a secure random salt could not be generated") from exc
    evidence.update(
        digest=_compute(key, salt, normalized_text),
        salt=salt.hex(),
        key_id=key_id,
        normalization_version=normalization_version,
        normalized_char_len=len(normalized_text),     # Unicode code points, not bytes
    )
    return evidence


def validate_request_evidence(evidence: object) -> dict:
    """Shape check applied to every record on write. Rejects unknown keys (nothing else may ride
    along in this object) and any status/field combination the schema does not allow."""
    if not isinstance(evidence, Mapping):
        raise ValueError("request_evidence must be a mapping")
    if set(evidence) != EVIDENCE_KEYS:
        raise ValueError(f"request_evidence keys must be exactly {sorted(EVIDENCE_KEYS)}, "
                         f"got {sorted(evidence)}")
    if evidence["digest_alg"] != DIGEST_ALG:
        raise ValueError(f"digest_alg must be {DIGEST_ALG!r}")
    if evidence["raw_text_stored"] is not False:
        raise ValueError("raw_text_stored must be False: the audit log never stores request text")
    status = evidence["status"]
    if status not in STATUSES:
        raise ValueError(f"request_evidence status must be one of {STATUSES}, got {status!r}")
    nullable = ("digest", "salt", "key_id", "normalization_version", "normalized_char_len")
    if status != AVAILABLE:
        if any(evidence[k] is not None for k in nullable):
            raise ValueError(f"status {status!r} requires digest, salt, key_id, "
                             f"normalization_version and normalized_char_len to be null")
        return dict(evidence)
    if not (isinstance(evidence["digest"], str) and _HEX_DIGEST_RE.match(evidence["digest"])):
        raise ValueError("digest must be 64 lowercase hex characters")
    if not (isinstance(evidence["salt"], str) and _HEX_SALT_RE.match(evidence["salt"])):
        raise ValueError(f"salt must be {SALT_BYTES * 2} lowercase hex characters")
    if not (isinstance(evidence["key_id"], str) and _KEY_ID_RE.match(evidence["key_id"])):
        raise ValueError("key_id is missing or invalid")
    if not (isinstance(evidence["normalization_version"], str) and evidence["normalization_version"]):
        raise ValueError("normalization_version must be a non-empty string")
    n = evidence["normalized_char_len"]
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("normalized_char_len must be a positive integer")
    return dict(evidence)


# --------------------------------------------------------------------------- verification

def matches_request(evidence: Mapping, request_text: str, key: str) -> bool:
    """Does `request_text` (as a reporter supplied it, i.e. NOT yet normalized) match this record?

    The text is normalized with the CURRENT Stage 0 normalizer. A record made under a different
    normalization version is reported as no match rather than guessed at. `key` must be the key
    whose id the record names (the caller looks it up; see find_matching_records).
    """
    from guardrails.injection_screen import NORMALIZATION_VERSION, screen_request

    if evidence.get("status") != AVAILABLE:
        return False
    if evidence.get("normalization_version") != NORMALIZATION_VERSION:
        return False
    normalized = screen_request(request_text).normalized_text
    if not normalized:
        return False
    key_bytes, _ = _check_key(key, evidence.get("key_id"))
    if len(normalized) != evidence.get("normalized_char_len"):
        return False
    salt = bytes.fromhex(evidence["salt"])
    return hmac.compare_digest(_compute(key_bytes, salt, normalized), evidence["digest"])


def find_matching_records(request_text: str, keys: Mapping[str, str],
                          log_path: Path | str) -> Iterator[dict]:
    """Scan an audit log for records matching a reporter-supplied request.

    `keys` maps key_id -> key for every key that may have signed a record in this log (old keys
    included). Records whose key_id is not in `keys`, and version-1 records (no request
    evidence), cannot match and are skipped. Yields {"line", "timestamp", "session_id",
    "final_outcome"} for each match; the request text is never written anywhere.
    """
    with open(log_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("schema_version") != 2:
                continue
            ev = rec.get("request_evidence")
            if not isinstance(ev, dict):
                continue
            key = keys.get(ev.get("key_id"))
            if key is None:
                continue
            if matches_request(ev, request_text, key):
                yield {"line": lineno, "timestamp": rec.get("timestamp"),
                       "session_id": rec.get("session_id"),
                       "final_outcome": rec.get("final_outcome")}
