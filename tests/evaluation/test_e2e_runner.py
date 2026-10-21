
import json
import sys
from unittest.mock import MagicMock

import pytest

from evaluation import e2e_runner as e2e
from evaluation import golden_set as gs
from llm import gateway as gw

ITEMS = gs.load()
KEY = "sk-test-KEY-9d41"
MAP = {"stub-small": "p-small", "stub-medium": "p-med", "stub-large": "p-large"}


def mk_gateway(tokens=(10, 5), fail_alias=None):
    def transport(url, headers, body, timeout):
        model = json.loads(body)["model"]
        if model == fail_alias:
            return 500, b"{}"
        return 200, json.dumps({"content": [{"type": "text", "text": "ans"},],
                                "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}).encode()
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP)
    return e2e.RecordingGateway(cfg, transport=transport)


def obs(tier="deterministic", blocked=False, confirm=False, calls=(), error=""):
    return e2e.Observed(tier, blocked, confirm, None, None, tuple(calls), 1.5, error)


def llm_call(alias="stub-medium", ok=True, i=100, o=50):
    return e2e.LLMCall(alias, ok, "" if ok else "upstream_error", i if ok else None, o if ok else None, 20.0)


def test_outcome_classification():
    assert e2e.outcome_of(obs()) == "answered_non_llm"
    assert e2e.outcome_of(obs("llm_low_reasoning")) == "answered_llm"
    assert e2e.outcome_of(obs("blocked_policy", blocked=True)) == "blocked"
    assert e2e.outcome_of(obs("blocked_policy", blocked=True, confirm=True)) == "needs_confirmation"
    assert e2e.outcome_of(obs("error", error="ValueError")) == "error"


def test_run_compares_runtime_to_baseline_on_answered_items_only():
    items = [i for i in ITEMS if i.id in ("G-001", "G-007", "G-011", "G-069")]   # det, llm, require_human, FP block
    script = {"G-001": obs("deterministic"),
              "G-007": obs("llm_low_reasoning", calls=[llm_call(i=40, o=60)]),
              "G-011": obs("blocked_policy", blocked=True, confirm=True),
              "G-069": obs("blocked_policy", blocked=True)}
    gateway = mk_gateway(tokens=(100, 100))
    rep = e2e.run(items, lambda it: script[it.id], gateway, "stub-large")
    assert rep["outcomes"] == {"answered_non_llm": 1, "answered_llm": 1, "blocked": 1, "needs_confirmation": 1, "error": 0}
    assert rep["llm_calls"]["baseline"] == 2                      # only the two answered items get a baseline call
    t = rep["tokens"]
    assert t["measured"] and (t["runtime_in"], t["runtime_out"]) == (40, 60) and (t["baseline_in"], t["baseline_out"]) == (200, 200)
    assert t["saving_vs_baseline"] == 0.75                        # 1 - 100/400
    assert rep["gate_agreement"]["disagreements"] == ["G-069"]    # expected allow, runtime blocked
    assert rep["answered"]["non_llm_share"] == 0.5 and rep["baseline_alias"] == "stub-large"


def test_stub_backend_reports_tokens_as_not_measured():
    gateway = e2e.RecordingGateway(gw.GatewayConfig())
    rep = e2e.run([ITEMS[0]], lambda it: obs("deterministic"), gateway, "stub-large")
    assert rep["tokens"]["measured"] is False and rep["tokens"]["saving_vs_baseline"] is None
    assert "not measured" in e2e.render_markdown(rep)


def test_failed_baseline_and_failed_runtime_calls_are_counted_not_hidden():
    gateway = mk_gateway(fail_alias="p-large")
    rep = e2e.run([ITEMS[0]], lambda it: obs("llm_low_reasoning", calls=[llm_call(ok=False)]), gateway, "stub-large")
    assert rep["llm_calls"]["baseline_failed"] == 1 and rep["llm_calls"]["runtime_failed"] == 1
    assert rep["tokens"]["measured"] is False and rep["tokens"]["saving_vs_baseline"] is None


def test_report_carries_the_caveats_and_baseline():
    rep = e2e.run(ITEMS[:2], lambda it: obs(), mk_gateway(), "stub-large")
    md = e2e.render_markdown(rep)
    assert "DIAGNOSTIC ONLY" in md and "baseline alias `stub-large`" in md
    assert "Not measured: answer quality, cache tier, energy or dollars" in md


def test_preflight_requires_key_and_a_mapping_for_every_catalog_model_and_the_baseline():
    ok = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP)
    assert e2e.preflight(ok, "stub-large") == []
    assert e2e.preflight(gw.GatewayConfig(), "anything") == []                     # stub spends nothing
    nokey = gw.GatewayConfig(backend="anthropic", model_map=MAP)
    assert any("ANTHROPIC_API_KEY" in p for p in e2e.preflight(nokey, "stub-large"))
    partial = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map={"stub-small": "x"})
    assert "stub-medium" in " ".join(e2e.preflight(partial, "stub-large"))
    assert any("my-baseline" in p for p in e2e.preflight(ok, "my-baseline"))


def test_cli_refuses_real_spend_without_consent_and_requires_a_baseline(capsys):
    g = mk_gateway()
    assert e2e.main(["--baseline-alias", "stub-large", "--limit", "2"], observe_factory=lambda gw_: (lambda it: obs()),
                    gateway=g) == 2
    assert "refusing to spend without --yes-spend" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        e2e.main(["--limit", "2"])                                                  # no baseline: argparse exits


def test_cli_writes_reports_and_restores_the_process_gateway(tmp_path, capsys):
    js, md = tmp_path / "r.json", tmp_path / "r.md"
    g = e2e.RecordingGateway(gw.GatewayConfig())
    code = e2e.main(["--baseline-alias", "stub-large", "--limit", "3", "--json", str(js), "--markdown", str(md)],
                    observe_factory=lambda gw_: (lambda it: obs()), gateway=g)
    assert code == 0 and json.loads(js.read_text(encoding="utf-8"))["provenance"]["items"] == 3
    assert md.read_text(encoding="utf-8").startswith("# Golden set: end-to-end")


# -- the real pipeline adapter -------------------------------------------------------------------
@pytest.fixture()
def web_layer():
    """api.main needs FastAPI only to define its HTTP app. Where FastAPI is absent (some sandboxes) stand-ins
    are installed for this test and removed afterwards so FastAPI-gated tests still skip as before."""
    try:
        import fastapi  # noqa: F401
        yield
        return
    except ImportError:
        pass
    names = ("fastapi", "fastapi.responses", "fastapi.testclient", "uvicorn")
    sys.modules.update({n: MagicMock() for n in names})
    try:
        yield
    finally:
        for n in names + ("api.main",):
            sys.modules.pop(n, None)


def test_real_pipeline_adapter_matches_the_expected_outcomes(web_layer, tmp_path):
    import os
    before = os.getcwd()
    gateway = e2e.RecordingGateway(gw.GatewayConfig())               # stub backend: spends nothing
    wanted = {"G-001": "answered_non_llm",      # capital of Japan: deterministic table
              "G-007": "answered_llm",          # write a story: LLM rung (stub)
              "G-011": "needs_confirmation",    # medical diagnosis: HAC-001
              "G-036": "answered_llm",
              "G-069": "blocked",               # DP-001 keyword block (known false positive)
              "G-082": "answered_llm"}          # HAC-002 is a flag, still answered
    items = [i for i in ITEMS if i.id in wanted]
    with e2e.scratch_environment(tmp_path / "scratch") as work:
        observe = e2e.real_pipeline(gateway)
        got = {i.id: e2e.outcome_of(observe(i)) for i in items}
        assert (work / "audit_log.jsonl").exists()                   # the audit record went to the scratch dir
    assert got == wanted
    assert os.getcwd() == before
    assert not (tmp_path / "audit_log.jsonl").exists()


def test_scratch_environment_restores_env_and_cache(web_layer, tmp_path):
    import os
    from audit.request_evidence import ENV_KEY
    import tiers.cache_lookup as cl
    os.environ[ENV_KEY] = "keep-me"
    old = cl._client
    with e2e.scratch_environment(tmp_path / "s"):
        assert os.environ[ENV_KEY].startswith("e2e-scratch-")
    assert os.environ[ENV_KEY] == "keep-me" and cl._client is old
