
import os
import pytest
from api.settings import Settings


@pytest.fixture(autouse=True)
def clean_env():
    keys = ["APP_HOST", "APP_PORT", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "REDIS_URL", "DATABASE_URL", "LOG_LEVEL"]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def test_defaults_with_no_env_vars():
    s = Settings()
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.anthropic_api_key == ""
    assert s.log_level == "INFO"


def test_env_overrides_picked_up_on_fresh_instance():
    os.environ["APP_HOST"] = "127.0.0.1"
    os.environ["APP_PORT"] = "9090"
    s = Settings()
    assert s.host == "127.0.0.1"
    assert s.port == 9090


def test_earlier_instance_is_unaffected_by_later_env_changes():
    s1 = Settings()
    os.environ["APP_HOST"] = "127.0.0.1"
    assert s1.host == "0.0.0.0"


def test_invalid_port_raises_clear_value_error():
    os.environ["APP_PORT"] = "not-a-number"
    with pytest.raises(ValueError, match="APP_PORT"):
        Settings()


def test_settings_is_immutable():
    s = Settings()
    with pytest.raises(Exception):
        s.port = 1234
