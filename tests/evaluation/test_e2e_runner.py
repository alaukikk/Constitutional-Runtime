
import dataclasses
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
    d = rep["tokens"]["decomposition"]
    assert d["avoided_calls"] == 1 and d["avoided_call_tokens"] == 200 and d["avoided_share_of_baseline"] == 0.5
    assert d["llm_routed"] == {"n": 1, "runtime_tokens": 100, "baseline_tokens": 200, "difference": -100,
                               "same_underlying_model": False}      # runtime alias stub-medium vs baseline stub-large
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
    assert "Not measured: free-text answer quality" in md


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


def test_pacing_wait_is_not_counted_as_call_latency():
    ticks = iter([100.0, 100.0, 100.25,      # call 1: pace check, start, end
                  101.0, 101.0, 101.25])     # call 2: pace check (5 s wait), start, end
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map=MAP, min_interval_s=6.0)

    def transport(url, headers, body, timeout):
        return 200, json.dumps({"content": [{"type": "text", "text": "a"}],
                                "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
    g = e2e.RecordingGateway(cfg, transport=transport, clock=lambda: next(ticks), sleep=lambda s: None)
    g.complete("x", "stub-small")
    g.complete("y", "stub-small")
    first, second = g.drain()
    assert (first.latency_ms, first.paced_ms) == (250.0, 0.0)
    assert (second.latency_ms, second.paced_ms) == (250.0, 5000.0)      # the 5 s wait is reported apart


def test_unpaced_wall_time_subtracts_the_waits():
    import time
    calls = (llm_call(), e2e.LLMCall("stub-small", True, "", 1, 1, 10.0, 60_000.0))
    t0 = time.perf_counter() - 61.0                                     # 61 s elapsed, 60 s of it was pacing
    assert 900.0 <= e2e._unpaced_ms(t0, calls) <= 1500.0


def test_progress_lines_are_emitted_per_item_and_cli_keeps_stdout_clean(capsys):
    lines = []
    e2e.run(ITEMS[:3], lambda it: obs(), mk_gateway(), "stub-large", progress=lines.append)
    assert len(lines) == 3 and lines[0].startswith("[1/3] G-001 answered_non_llm") and "baseline=ok" in lines[0]
    e2e.main(["--baseline-alias", "stub-large", "--limit", "2"], observe_factory=lambda g_: (lambda it: obs()),
             gateway=e2e.RecordingGateway(gw.GatewayConfig()))
    cap = capsys.readouterr()
    assert "[1/2]" in cap.err and "[1/2]" not in cap.out and cap.out.startswith("# Golden set")


def test_same_underlying_model_is_reported_as_run_to_run_variation():
    items = [i for i in ITEMS if i.id in ("G-001", "G-007")]
    script = {"G-001": obs("deterministic"), "G-007": obs("llm_low_reasoning", calls=[llm_call(i=40, o=60)])}
    # same provider model behind both aliases -> the LLM-routed difference is not a saving
    cfg = gw.GatewayConfig(backend="anthropic", api_key=KEY, model_map={a: "m1" for a in MAP})
    g3 = e2e.RecordingGateway(cfg, transport=lambda u, h, b, t: (200, json.dumps(
        {"content": [{"type": "text", "text": "x"}], "usage": {"input_tokens": 100, "output_tokens": 100}}).encode()))
    rep3 = e2e.run(items, lambda it: script[it.id], g3, "stub-large")
    assert rep3["tokens"]["decomposition"]["llm_routed"]["same_underlying_model"] is True
    assert "run-to-run variation, not a saving" in e2e.render_markdown(rep3)


def test_answer_matches_is_whole_token_and_alternative_aware():
    am = gs.answer_matches
    assert am("12", "The answer is 12.") and not am("12", "It is 12.5") and not am("12", "112")
    assert am("100|212", "212 degrees F") and am("Tokyo", "It's tokyo!") and am("1000", "about 1,000")
    assert not am("", "anything") and not am("7", "seven")


def test_correctness_scores_cheap_and_llm_answers_separately():
    items = [dataclasses.replace(i, expected_answer=a) for i, a in
             ((next(x for x in ITEMS if x.id == "G-001"), "Tokyo"), (next(x for x in ITEMS if x.id == "G-007"), "ans"))]
    script = {"G-001": e2e.Observed("deterministic", False, False, None, None, (), 1.0, "", "Paris"),     # wrong cheap answer
              "G-007": e2e.Observed("llm_low_reasoning", False, False, None, None, (llm_call(i=1, o=1),), 1.0, "", "ans ok")}
    rep = e2e.run(items, lambda it: script[it.id], mk_gateway(), "stub-large")
    c = rep["correctness"]
    assert c["scored"] == 2
    assert c["non_llm"]["n"] == 1 and c["non_llm"]["runtime_correct"] == 0 and c["non_llm"]["wrong_ids"] == ["G-001"]
    assert c["llm"]["runtime_correct"] == 1 and c["llm"]["baseline_correct"] == 1       # baseline gateway answers "ans"
    md = e2e.render_markdown(rep)
    assert "WRONG ['G-001']" in md and "## Correctness" in md


def test_unscored_items_do_not_appear_in_correctness():
    item = dataclasses.replace(ITEMS[0], expected_answer="")
    rep = e2e.run([item], lambda it: obs("deterministic"), mk_gateway(), "stub-large")
    assert rep["correctness"]["scored"] == 0 and "## Correctness" not in e2e.render_markdown(rep)
