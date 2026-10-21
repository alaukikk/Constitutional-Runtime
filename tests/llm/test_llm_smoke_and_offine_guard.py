
import json

import pytest

from llm import gateway as gw
from llm import smoke
from tiers.llm_call import call_llm

KEY = "sk-test-KEY-9d41"
MAP = {"stub-small": "prov-small", "stub-large": "prov-large"}


class Fake:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def __call__(self, url, headers, body, timeout):
        model = json.loads(body)["model"]
        self.calls.append(model)
        if model in self.fail:
            return 429, b'{"error":"provider text that must not be printed"}'
        return 200, json.dumps({"content": [{"type": "text", "text": "ok"}],
                                "usage": {"input_tokens": 12, "output_tokens": 2}}).encode()


def gateway(fake):
    return gw.LLMGateway(gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP), transport=fake)


def test_every_test_runs_against_the_stub_even_if_the_environment_says_otherwise(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    assert call_llm("hello", "stub-small").startswith("[STUB LLM RESPONSE]")


def test_call_llm_delegates_to_the_installed_gateway():
    fake = Fake()
    gw.set_gateway(gateway(fake))
    assert call_llm("hello", "stub-large") == "ok" and fake.calls == ["prov-large"]


def test_smoke_succeeds_and_reports_counts_without_key(capsys, tmp_path):
    fake = Fake()
    out = tmp_path / "r.json"
    assert smoke.main(["--json", str(out)], gateway=gateway(fake)) == 0
    text = capsys.readouterr().out
    assert KEY not in text and "in=12 out=2" in text and sorted(fake.calls) == ["prov-large", "prov-small"]
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [r["alias"] for r in rows] == ["stub-large", "stub-small"] and all(r["ok"] for r in rows)


def test_smoke_failure_exits_nonzero_and_prints_only_the_code(capsys):
    assert smoke.main([], gateway=gateway(Fake(fail={"prov-small"}))) == 1
    text = capsys.readouterr().out
    assert "FAILED (rate_limited)" in text and "provider text" not in text and KEY not in text


def test_smoke_refuses_to_run_on_the_stub_or_with_no_map(capsys):
    assert smoke.main([], gateway=gw.LLMGateway(gw.GatewayConfig())) == 2
    assert smoke.main([], gateway=gw.LLMGateway(gw.GatewayConfig(backend="anthropic", api_key=KEY))) == 2
    assert "LLM_MODEL_MAP is empty" in capsys.readouterr().err


def test_smoke_reports_bad_environment_by_variable_name(monkeypatch, capsys):
    monkeypatch.setenv("LLM_TIMEOUT_S", "not-a-number")
    assert smoke.main([]) == 2
    err = capsys.readouterr().err
    assert "LLM_TIMEOUT_S" in err and "not-a-number" not in err


def test_smoke_can_target_one_alias():
    fake = Fake()
    assert smoke.main(["--aliases", "stub-small"], gateway=gateway(fake)) == 0
    assert fake.calls == ["prov-small"]
