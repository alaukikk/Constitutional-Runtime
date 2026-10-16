
"""Fixtures for the whole-pipeline attack suites in this folder.

Audit schema v2 (CP-001) needs an HMAC key for every audit write. tests/conftest.py provides
one for tests/, but this folder is outside tests/, so the same throwaway (non-secret) key is
injected here. Nothing in this folder needs a real key.
"""
import pytest

import tiers.cache_lookup as cache_lookup
from audit.request_evidence import ENV_KEY, ENV_KEY_ID
from guardrails.adversarial.harness import Pipe

THROWAWAY_KEY = "adversarial-suite-throwaway-key-0123456789"     # not a secret
THROWAWAY_KEY_ID = "adversarial-suite-key-1"


@pytest.fixture(autouse=True)
def audit_hmac_config(monkeypatch):
    monkeypatch.setenv(ENV_KEY, THROWAWAY_KEY)
    monkeypatch.setenv(ENV_KEY_ID, THROWAWAY_KEY_ID)
    yield


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = Pipe(tmp_path, monkeypatch)
    yield p
    cache_lookup._client = None
