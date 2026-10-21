
"""LLM gateway: the one place a real model is called (Sprint 7, step 1 of the integration).

Everything above this (Stage 5, the repair router, the validator) is unchanged: they call
``tiers.llm_call.call_llm(text, model_name)`` and get a string, or an exception that Stage 5
already treats as an execution error.

Design rules, each with a reason:
  * Default backend is ``stub``. CI and the whole test suite stay offline and deterministic; a
    real call needs LLM_BACKEND=anthropic AND a key AND an explicit model map.
  * No silent fallback. A catalog model with no provider mapping raises ``unmapped_model``; it
    is never answered by some other model, because that would change cost and capability behind
    the router's back (OI-005 keeps the catalog numbers as placeholders; this module does not
    resolve them).
  * No request or response text anywhere but the HTTP body. Errors carry a stable ``code`` only
    (never a provider message, which could echo input); the measurement log holds counts and
    timings only; the API key has ``repr=False`` and is sent only in a header (OI-084).
  * No retries. A retry doubles spend without Stage 3/6 knowing; escalation and repair already
    belong to Stage 5/6 and are cost-bounded there (OI-065, OI-069).
  * Transport is injectable, so every failure mode is tested without a network.
  * Measurements (input/output tokens as REPORTED by the provider, wall latency, truncation) are
    the empirical inputs OI-005 and OI-045 are waiting for. They go to a separate JSONL file, not
    the audit log, so CP-001's schema is untouched.

Provisional defaults (owner-reversible, none is calibrated; see the Sprint 7-8 table):
  timeout 30 s, max output 1024 tokens, temperature 0.0 (repeatable evaluation runs), one short
  neutral system prompt. Policy is enforced by the gates, not by the prompt.

Limit stated on purpose: this has not been run against the live API from the build environment
(no outbound access). The wire format follows Anthropic's documented Messages API; the first
real call is the owner's smoke test (``python -m llm.smoke``).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional

from audit.safe_exc import log_exception

log = logging.getLogger(__name__)

STUB_MODEL = "stub-model"
DEFAULT_SYSTEM = "You are a helpful assistant. Answer the user's request directly and concisely."
BACKENDS = ("stub", "anthropic")

# Codes are the whole error surface. Never put provider text in an error.
CODES = ("not_configured", "unmapped_model", "timeout", "rate_limited", "auth", "bad_request",
         "upstream_error", "bad_response", "network")


class LLMGatewayError(RuntimeError):
    """Execution error from the gateway. ``str(exc)`` is the code and nothing else."""

    def __init__(self, code: str):
        assert code in CODES, code
        super().__init__(code)
        self.code = code


class GatewayConfigError(ValueError):
    """Bad environment configuration (raised at construction, with the variable name only)."""


Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class _KeepStatus(urllib.request.HTTPErrorProcessor):
    """Return every HTTP response as-is. No HTTPError is raised for 4xx/5xx and, because the error
    handlers never run, no redirect is followed: a 3xx must NOT re-send the API key header elsewhere."""

    def http_response(self, request, response):
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_KeepStatus)


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(req, timeout=timeout) as resp:                      # noqa: S310 (fixed https URL)
            return resp.status, resp.read()
    except urllib.error.URLError as exc:                                      # urllib wraps connect timeouts
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError from None
        raise


@dataclass(frozen=True)
class GatewayConfig:
    backend: str = "stub"
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.anthropic.com"
    api_version: str = "2023-06-01"
    timeout_s: float = 30.0
    max_output_tokens: int = 1024
    temperature: float = 0.0
    system_prompt: str = DEFAULT_SYSTEM
    model_map: Mapping[str, str] = field(default_factory=dict)      # catalog name -> provider model id
    measurements_path: Optional[Path] = None

    def __post_init__(self):
        if self.backend not in BACKENDS:
            raise GatewayConfigError(f"LLM_BACKEND must be one of {BACKENDS}")
        if not (0 < self.timeout_s <= 300):
            raise GatewayConfigError("LLM_TIMEOUT_S must be in (0, 300]")
        if not (1 <= self.max_output_tokens <= 8192):
            raise GatewayConfigError("LLM_MAX_OUTPUT_TOKENS must be in [1, 8192]")
        if not (0.0 <= self.temperature <= 1.0):
            raise GatewayConfigError("LLM_TEMPERATURE must be in [0, 1]")
        if self.backend == "anthropic" and not (self.base_url.startswith("https://") or any(
                self.base_url.startswith(f"http://{h}") for h in ("127.0.0.1", "localhost", "[::1]"))):
            raise GatewayConfigError("LLM_BASE_URL must be https (plain http only for loopback test servers)")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "GatewayConfig":
        e = os.environ if env is None else env

        def num(name: str, default: str, conv):
            try:
                return conv(e.get(name, default))
            except ValueError:
                raise GatewayConfigError(f"{name} is not a valid number") from None

        raw_map = e.get("LLM_MODEL_MAP", "")
        try:
            model_map = json.loads(raw_map) if raw_map.strip() else {}
        except json.JSONDecodeError:
            raise GatewayConfigError("LLM_MODEL_MAP must be a JSON object") from None
        if not isinstance(model_map, dict) or not all(
                isinstance(k, str) and isinstance(v, str) and v for k, v in model_map.items()):
            raise GatewayConfigError("LLM_MODEL_MAP must map catalog names to provider model ids")
        mp = e.get("LLM_MEASUREMENTS_PATH", "").strip()
        return cls(
            backend=e.get("LLM_BACKEND", "stub").strip().lower() or "stub",
            api_key=e.get("ANTHROPIC_API_KEY", ""),
            base_url=e.get("LLM_BASE_URL", cls.base_url),
            timeout_s=num("LLM_TIMEOUT_S", str(cls.timeout_s), float),
            max_output_tokens=num("LLM_MAX_OUTPUT_TOKENS", str(cls.max_output_tokens), int),
            temperature=num("LLM_TEMPERATURE", str(cls.temperature), float),
            model_map=model_map,
            measurements_path=Path(mp) if mp else None)


@dataclass(frozen=True)
class Measurement:
    """What one call cost. No request text, no response text, no session id."""
    model_alias: str
    provider_model: str
    ok: bool
    error_code: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: float
    truncated: bool
    ts: float


class LLMGateway:
    def __init__(self, config: GatewayConfig, transport: Transport = urllib_transport,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        self.config = config
        self._transport, self._clock, self._wall = transport, clock, wall
        self._lock = threading.Lock()
        self.last_measurement: Optional[Measurement] = None

    # -- public ---------------------------------------------------------------------------------
    def complete(self, request_text: str, model_name: str = STUB_MODEL) -> str:
        if not isinstance(request_text, str):
            raise TypeError("request_text must be a string")
        if self.config.backend == "stub":
            return f"[STUB LLM RESPONSE] would have called {model_name} for: {request_text[:50]!r}"
        return self._anthropic(request_text, model_name)

    # -- real backend ---------------------------------------------------------------------------
    def _anthropic(self, text: str, alias: str) -> str:
        cfg = self.config
        if not cfg.api_key:
            raise LLMGatewayError("not_configured")
        provider_model = cfg.model_map.get(alias)
        if not provider_model:
            raise LLMGatewayError("unmapped_model")
        body = json.dumps({
            "model": provider_model, "max_tokens": cfg.max_output_tokens, "temperature": cfg.temperature,
            "system": cfg.system_prompt, "messages": [{"role": "user", "content": text}],
        }).encode("utf-8")
        headers = {"content-type": "application/json", "x-api-key": cfg.api_key,
                   "anthropic-version": cfg.api_version}
        start = self._clock()
        code, answer, in_tok, out_tok, truncated = self._attempt(cfg.base_url.rstrip("/") + "/v1/messages",
                                                                 headers, body)
        self._record(Measurement(alias, provider_model, ok=not code, error_code=code, input_tokens=in_tok,
                                 output_tokens=out_tok, latency_ms=round((self._clock() - start) * 1000, 3),
                                 truncated=truncated, ts=self._wall()))
        if code:
            raise LLMGatewayError(code)
        return answer

    def _attempt(self, url: str, headers: dict, body: bytes):
        """One call. Returns (error_code, answer, input_tokens, output_tokens, truncated); never raises.
        Failures are classified by return value so no exception object is bound or formatted
        (tests/audit/test_no_request_text_in_logs.py)."""
        try:
            status, raw = self._transport(url, headers, body, self.config.timeout_s)
        except TimeoutError:
            return "timeout", "", None, None, False
        except OSError:                                        # DNS, refused, reset, TLS
            return "network", "", None, None, False
        except Exception:                                      # a transport bug is still a failed call
            return "bad_response", "", None, None, False
        if status in (401, 403):
            return "auth", "", None, None, False
        if status == 429:
            return "rate_limited", "", None, None, False
        if 400 <= status < 500:
            return "bad_request", "", None, None, False
        if not (200 <= status < 300):
            return "upstream_error", "", None, None, False
        try:
            answer, in_tok, out_tok, truncated = self._parse(raw)
        except LLMGatewayError:
            return "bad_response", "", None, None, False
        return "", answer, in_tok, out_tok, truncated

    @staticmethod
    def _parse(raw: bytes):
        try:
            data = json.loads(raw)
            blocks = data["content"]
            text = "".join(b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text")
            usage = data.get("usage") or {}
            in_tok, out_tok = usage.get("input_tokens"), usage.get("output_tokens")
            for v in (in_tok, out_tok):
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                    raise ValueError
            truncated = data.get("stop_reason") == "max_tokens"
        except (ValueError, KeyError, TypeError, AttributeError):
            raise LLMGatewayError("bad_response") from None
        if not text.strip():
            raise LLMGatewayError("bad_response")
        return text, in_tok, out_tok, truncated

    # -- measurements ---------------------------------------------------------------------------
    def _record(self, m: Measurement) -> None:
        self.last_measurement = m
        path = self.config.measurements_path
        if path is None:
            return
        try:
            line = json.dumps(m.__dict__, sort_keys=True) + "\n"
            with self._lock:
                with open(path, "a", encoding="utf-8", newline="") as fh:
                    fh.write(line)
        except Exception:                                      # measuring must never break an answer
            log_exception(log, "could not write the LLM measurement record")


# -- process-wide gateway (lazy; tests reset it) ------------------------------------------------
_gateway: Optional[LLMGateway] = None
_gw_lock = threading.Lock()


def get_gateway() -> LLMGateway:
    global _gateway
    with _gw_lock:
        if _gateway is None:
            _gateway = LLMGateway(GatewayConfig.from_env())
        return _gateway


def set_gateway(gateway: Optional[LLMGateway]) -> None:
    """Install (or clear, with None) the process-wide gateway. For tests and the runners."""
    global _gateway
    with _gw_lock:
        _gateway = gateway
