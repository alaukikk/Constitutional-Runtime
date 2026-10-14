
"""
Shared test fixtures.

Audit schema v2 (CP-001) needs an HMAC key for EVERY audit write, and a missing key fails the
write loudly on purpose. Tests inject a throwaway key through this autouse fixture, so no key
is ever needed in tests.yml (the workflow is CODEOWNERS-protected) and no real secret appears
in the repository. Tests that exercise a missing or bad key delete or replace these variables
themselves with monkeypatch.
"""
import pytest

from audit.request_evidence import ENV_KEY, ENV_KEY_ID

TEST_HMAC_KEY = "test-only-audit-hmac-key-0123456789"        # throwaway, not a secret
TEST_HMAC_KEY_ID = "test-key-1"


@pytest.fixture(autouse=True)
def audit_hmac_config(monkeypatch):
    monkeypatch.setenv(ENV_KEY, TEST_HMAC_KEY)
    monkeypatch.setenv(ENV_KEY_ID, TEST_HMAC_KEY_ID)
    yield
