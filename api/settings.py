
"""
api/settings.py — app-level settings, loaded from environment variables
(optionally via a .env file).

Design note: fields use field(default_factory=...) rather than a plain
`= os.getenv(...)` default. A plain default is computed ONCE at module
import time, so creating multiple Settings() instances (e.g. in tests,
after monkeypatching os.environ) would silently reuse the first-ever
value instead of re-reading the environment. default_factory re-reads
on every instantiation.

Bad config (e.g. a non-integer APP_PORT) fails loudly at construction
time with a clear message, rather than crashing confusingly later or
silently falling back to a default.

Sprint 6 (OI-013): SESSION_SECRET signs server-issued session tokens. If it is
empty the app generates a random per-process secret (tokens then stop working on
restart, and so does the in-memory session state, OI-020/OI-041). Set it in any
real deployment. The three SESSION_* limits are PLACEHOLDERS (OI-078).
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_int_env(key: str, default: str) -> int:
    raw = os.getenv(key, default)
    try:
        return int(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {key}='{raw}' is not a valid integer. "
            f"Fix your .env / environment before starting the app."
        ) from None


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_int_env("APP_PORT", "8000"))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./dev.db"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    checkpoint_secret: str = field(default_factory=lambda: os.getenv("CHECKPOINT_SECRET", ""))
    # Server-issued session identity (OI-013). Limits are placeholders (OI-078).
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", ""))
    session_ttl_seconds: int = field(default_factory=lambda: _get_int_env("SESSION_TTL_SECONDS", "604800"))
    session_issue_limit: int = field(default_factory=lambda: _get_int_env("SESSION_ISSUE_LIMIT", "10"))
    session_issue_window_seconds: int = field(
        default_factory=lambda: _get_int_env("SESSION_ISSUE_WINDOW_SECONDS", "3600"))


settings = Settings()
