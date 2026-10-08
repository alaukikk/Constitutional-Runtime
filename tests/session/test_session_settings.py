
"""OI-013: session identity settings. Kept apart from test_session_http.py, which is skipped as a
whole when fastapi/httpx are not installed; these tests need neither."""
import pytest

from api.settings import Settings


def test_session_settings_defaults_and_env_overrides(monkeypatch):
    for k in ("SESSION_SECRET", "SESSION_TTL_SECONDS", "SESSION_ISSUE_LIMIT", "SESSION_ISSUE_WINDOW_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert (s.session_secret, s.session_ttl_seconds, s.session_issue_limit,
            s.session_issue_window_seconds) == ("", 604800, 10, 3600)
    monkeypatch.setenv("SESSION_SECRET", "abc")
    monkeypatch.setenv("SESSION_ISSUE_LIMIT", "2")
    s = Settings()
    assert s.session_secret == "abc" and s.session_issue_limit == 2


def test_bad_session_setting_fails_loudly(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_SECONDS", "forever")
    with pytest.raises(ValueError, match="SESSION_TTL_SECONDS"):
        Settings()


def test_each_session_integer_setting_rejects_non_integers(monkeypatch):
    for key in ("SESSION_TTL_SECONDS", "SESSION_ISSUE_LIMIT", "SESSION_ISSUE_WINDOW_SECONDS"):
        monkeypatch.setenv(key, "ten")
        with pytest.raises(ValueError, match=key):
            Settings()
        monkeypatch.delenv(key)
