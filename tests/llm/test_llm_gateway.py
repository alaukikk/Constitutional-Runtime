
import json
import logging

import pytest

from llm import gateway as gw

CANARY = "CANARY-7f3a-request-text"
KEY = "sk-test-KEY-9d41"
MAP = {"stub-small": "prov-small", "stub-large": "prov-large"}


def ok_body(text="hello", i=11, o=7, stop="end_turn"):
    return json.dumps({"content": [{"type": "text", "text": text}], "usage": {"input_tokens": i, "output_tokens": o},
                       "stop_reason": stop}).encode()


class Fake:
    def __init__(self, status=200, body=None, exc=None):
        self.status, self.body, self.exc, self.calls = status, body if body is not None else ok_body(), exc, []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body), timeout))
        if self.exc:
            raise self.exc
        return self.status, self.body


def make(fake=None, tmp=None, **over):
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP,
                           measurements_path=(tmp / "m.jsonl") if tmp else None, **over)
    return gw.LLMGateway(cfg, transport=fake or Fake()), fake


def test_stub_backend_keeps_the_old_string_and_never_touches_the_network():
    fake = Fake()
    g = gw.LLMGateway(gw.GatewayConfig(), transport=fake)
    assert g.complete("what is 2+2", "stub-small") == "[STUB LLM RESPONSE] would have called stub-small for: 'what is 2+2'"
    assert fake.calls == []


def test_request_shape_and_answer():
    fake = Fake()
    g, _ = make(fake)
    assert g.complete("hi there", "stub-large") == "hello"
    url, headers, body, timeout = fake.calls[0]
    assert url == "https://api.anthropic.com/v1/messages" and timeout == 30.0
    assert headers["x-api-key"] == KEY and headers["anthropic-version"] == "2023-06-01"
    assert body == {"model": "prov-large", "max_tokens": 1024, "temperature": 0.0, "system": gw.DEFAULT_SYSTEM,
                    "messages": [{"role": "user", "content": "hi there"}]}


def test_multiple_text_blocks_are_joined_and_non_text_ignored():
    blocks = json.dumps({"content": [{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": "b"}],
                         "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
    g, _ = make(Fake(body=blocks))
    assert g.complete("x", "stub-small") == "ab"


@pytest.mark.parametrize("status,code", [(401, "auth"), (403, "auth"), (429, "rate_limited"),
                                         (400, "bad_request"), (404, "bad_request"), (500, "upstream_error"),
                                         (529, "upstream_error"), (302, "upstream_error")])
def test_status_to_code(status, code):
    g, _ = make(Fake(status=status, body=json.dumps({"error": {"message": CANARY}}).encode()))
    with pytest.raises(gw.LLMGatewayError) as ei:
        g.complete(CANARY, "stub-small")
    assert ei.value.code == code and str(ei.value) == code and CANARY not in repr(ei.value)


@pytest.mark.parametrize("exc,code", [(TimeoutError(CANARY), "timeout"), (ConnectionResetError(CANARY), "network"),
                                      (OSError(CANARY), "network"), (ValueError(CANARY), "bad_response")])
def test_transport_failures_map_to_codes_without_the_message(exc, code):
    g, _ = make(Fake(exc=exc))
    with pytest.raises(gw.LLMGatewayError) as ei:
        g.complete(CANARY, "stub-small")
    assert ei.value.code == code and CANARY not in str(ei.value) and CANARY not in repr(ei.value)
    assert g.last_measurement.ok is False and g.last_measurement.error_code == code


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"content": []}', b'{"content": [{"type":"text","text":"  "}]}',
                                  b'{"content": "x"}', json.dumps({"content": [{"type": "text", "text": "a"}],
                                                                   "usage": {"input_tokens": -1}}).encode(),
                                  json.dumps({"content": [{"type": "text", "text": "a"}],
                                              "usage": {"input_tokens": True}}).encode()])
def test_malformed_success_bodies_are_bad_response(body):
    g, _ = make(Fake(body=body))
    with pytest.raises(gw.LLMGatewayError) as ei:
        g.complete("x", "stub-small")
    assert ei.value.code == "bad_response"


def test_no_key_and_unmapped_model_fail_closed_without_a_call():
    fake = Fake()
    g = gw.LLMGateway(gw.GatewayConfig(backend="anthropic", model_map=MAP), transport=fake)
    with pytest.raises(gw.LLMGatewayError, match="not_configured"):
        g.complete("x", "stub-small")
    g2, _ = make(fake)
    with pytest.raises(gw.LLMGatewayError, match="unmapped_model"):
        g2.complete("x", "stub-medium")                     # never answered by a different model
    assert fake.calls == []


def test_measurements_hold_counts_only_never_text_or_key(tmp_path):
    g, _ = make(Fake(body=ok_body(text="ans " + CANARY, i=5, o=9, stop="max_tokens")), tmp=tmp_path)
    g.complete("q " + CANARY, "stub-small")
    raw = (tmp_path / "m.jsonl").read_text(encoding="utf-8")
    assert CANARY not in raw and KEY not in raw
    rec = json.loads(raw)
    assert rec["input_tokens"] == 5 and rec["output_tokens"] == 9 and rec["truncated"] is True
    assert rec["ok"] is True and rec["model_alias"] == "stub-small" and rec["provider_model"] == "prov-small"
    assert set(rec) == {"model_alias", "provider_model", "ok", "error_code", "input_tokens", "output_tokens",
                        "latency_ms", "truncated", "ts"}


def test_failed_calls_are_measured_too(tmp_path):
    g, _ = make(Fake(status=429), tmp=tmp_path)
    with pytest.raises(gw.LLMGatewayError):
        g.complete("x", "stub-small")
    rec = json.loads((tmp_path / "m.jsonl").read_text(encoding="utf-8"))
    assert rec["ok"] is False and rec["error_code"] == "rate_limited" and rec["input_tokens"] is None


def test_unwritable_measurement_file_never_breaks_the_answer(tmp_path, caplog):
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP, measurements_path=tmp_path / "no" / "dir" / "m")
    g = gw.LLMGateway(cfg, transport=Fake())
    with caplog.at_level(logging.DEBUG):
        assert g.complete("x", "stub-small") == "hello"
    assert "could not write the LLM measurement record" in caplog.text and CANARY not in caplog.text


def test_latency_uses_the_injected_clock():
    ticks = iter([10.0, 10.25])
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP)
    g = gw.LLMGateway(cfg, transport=Fake(), clock=lambda: next(ticks), wall=lambda: 123.0)
    g.complete("x", "stub-small")
    assert g.last_measurement.latency_ms == 250.0 and g.last_measurement.ts == 123.0


def test_no_retry_on_failure():
    fake = Fake(status=500)
    g, _ = make(fake)
    with pytest.raises(gw.LLMGatewayError):
        g.complete("x", "stub-small")
    assert len(fake.calls) == 1


def test_config_never_leaks_the_key():
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY)
    assert KEY not in repr(cfg) and KEY not in str(cfg)


@pytest.mark.parametrize("env,needle", [
    ({"LLM_BACKEND": "openai"}, "LLM_BACKEND"),
    ({"LLM_TIMEOUT_S": "abc"}, "LLM_TIMEOUT_S"), ({"LLM_TIMEOUT_S": "0"}, "LLM_TIMEOUT_S"),
    ({"LLM_MAX_OUTPUT_TOKENS": "x"}, "LLM_MAX_OUTPUT_TOKENS"), ({"LLM_MAX_OUTPUT_TOKENS": "99999"}, "LLM_MAX_OUTPUT_TOKENS"),
    ({"LLM_TEMPERATURE": "2"}, "LLM_TEMPERATURE"),
    ({"LLM_MODEL_MAP": "{bad"}, "LLM_MODEL_MAP"), ({"LLM_MODEL_MAP": '["a"]'}, "LLM_MODEL_MAP"),
    ({"LLM_MODEL_MAP": '{"a": ""}'}, "LLM_MODEL_MAP"),
    ({"LLM_BACKEND": "anthropic", "LLM_BASE_URL": "http://insecure"}, "https"),
])
def test_bad_environment_is_rejected_by_name(env, needle):
    with pytest.raises(gw.GatewayConfigError, match=needle):
        gw.GatewayConfig.from_env(env)


def test_from_env_defaults_to_stub_and_reads_the_map():
    assert gw.GatewayConfig.from_env({}).backend == "stub"
    cfg = gw.GatewayConfig.from_env({"LLM_BACKEND": "Anthropic", "ANTHROPIC_API_KEY": KEY,
                                     "LLM_MODEL_MAP": json.dumps(MAP), "LLM_MEASUREMENTS_PATH": "m.jsonl"})
    assert cfg.backend == "anthropic" and dict(cfg.model_map) == MAP and str(cfg.measurements_path) == "m.jsonl"


def test_process_wide_gateway_can_be_installed_and_cleared():
    g = gw.LLMGateway(gw.GatewayConfig())
    gw.set_gateway(g)
    try:
        assert gw.get_gateway() is g
    finally:
        gw.set_gateway(None)
    assert gw.get_gateway() is not g
    gw.set_gateway(None)


def test_non_string_request_is_a_type_error():
    with pytest.raises(TypeError):
        gw.LLMGateway(gw.GatewayConfig()).complete(None)          # a wiring bug, not data


class _Server:
    """Real localhost HTTP server so the real opener is exercised (redirects, statuses, timeouts)."""

    def __init__(self):
        import http.server
        import threading
        self.hits = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("content-length", 0))
                self.rfile.read(n)
                outer.hits.append((self.path, self.headers.get("x-api-key")))
                if self.path == "/redir":
                    self.send_response(302)
                    self.send_header("Location", "/stolen")
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                code = {"/ok": 200, "/v1/messages": 200, "/limited": 429, "/boom": 500}.get(self.path, 404)
                payload = b'{"content":[{"type":"text","text":"hi"}]}' if code == 200 else b'{"error":"x"}'
                self.send_response(code)
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def test_real_transport_returns_statuses_and_never_follows_a_redirect():
    srv = _Server()
    try:
        assert gw.urllib_transport(srv.url + "/ok", {"x-api-key": KEY}, b"{}", 5)[0] == 200
        assert gw.urllib_transport(srv.url + "/limited", {}, b"{}", 5)[0] == 429
        assert gw.urllib_transport(srv.url + "/boom", {}, b"{}", 5)[0] == 500
        status, _ = gw.urllib_transport(srv.url + "/redir", {"x-api-key": KEY}, b"{}", 5)
        assert status == 302
        assert all(path != "/stolen" for path, _ in srv.hits)       # the key was never re-sent elsewhere
    finally:
        srv.close()


def test_real_transport_maps_connection_refused_and_timeouts(monkeypatch):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                          # nothing is listening now
    with pytest.raises(OSError):
        gw.urllib_transport(f"http://127.0.0.1:{port}/x", {}, b"{}", 2)
    import urllib.error

    class FakeOpener:
        def open(self, req, timeout=None):
            raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(gw, "_OPENER", FakeOpener())
    with pytest.raises(TimeoutError):
        gw.urllib_transport("https://x/v1/messages", {}, b"{}", 1.0)


def test_gateway_end_to_end_over_the_real_transport(tmp_path):
    srv = _Server()
    try:
        cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP, base_url=srv.url,
                               measurements_path=tmp_path / "m.jsonl")
        assert gw.LLMGateway(cfg).complete("x", "stub-small") == "hi"
        assert srv.hits == [("/v1/messages", KEY)]
        assert json.loads((tmp_path / "m.jsonl").read_text(encoding="utf-8"))["ok"] is True
    finally:
        srv.close()


def test_plain_http_is_refused_except_for_loopback():
    with pytest.raises(gw.GatewayConfigError, match="https"):
        gw.GatewayConfig(backend="anthropic", base_url="http://api.example.com")
    gw.GatewayConfig(backend="anthropic", base_url="http://127.0.0.1:9")
