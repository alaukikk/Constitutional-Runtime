
import json

import pytest

from cost import breakeven as be


def call(lat=1000.0, i=100, o=200, ok=True):
    return {"ok": ok, "latency_ms": lat, "input_tokens": i, "output_tokens": o}


def row(id, outcome, base=None, wall=1.0):
    return {"id": id, "outcome": outcome, "baseline_call": base, "wall_ms": wall}


REAL = {"backend": "openai_compat", "rows": [
    row("A", "answered_non_llm", call(500, 10, 10)), row("B", "answered_llm", call(1500, 100, 200)),
    row("C", "answered_llm", call(1000, 100, 100)), row("D", "blocked"), ]}
STUB = {"backend": "stub", "rows": [row(x, "answered_llm", wall=w) for x, w in zip("ABCD", (2.0, 4.0, 6.0, 8.0))]}


def test_overhead_stats_from_stub_rows():
    ov = be.overhead_stats(STUB)
    assert ov == {"n": 4, "mean_ms": 5.0, "median_ms": 5.0, "p95_ms": 8.0}
    assert be.overhead_stats({"rows": []}) is None


def test_analyze_latency_tokens_and_rag_bound():
    a = be.analyze(REAL, STUB, {"A": "deterministic", "B": "rag_small_model", "C": "llm_low_reasoning", "D": "deterministic"})
    assert a["requests"] == 4 and a["answered"] == 3 and a["skipped_calls"] == 1
    assert a["baseline_mean_latency_ms"] == 1000.0                    # (500+1500+1000)/3
    lat = a["latency"]
    assert lat["skipped_calls_latency_ms"] == 1000.0 and lat["overhead_total_ms"] == 20.0
    assert lat["net_ms_saved"] == 980.0 and lat["pays_for_itself"] is True
    assert lat["breakeven_skipped_share_of_requests"] == 0.005 and lat["observed_skipped_share_of_requests"] == 0.25
    t = a["tokens"]
    assert t["avoided_call_tokens"] == 20 and t["share_of_baseline"] == round(20 / 520, 4)    # baseline total 20+300+200
    assert a["rag_upper_bound"]["requests"] == 1 and a["rag_upper_bound"]["baseline_tokens"] == 300


def test_overhead_can_exceed_the_saving():
    heavy = {"backend": "stub", "rows": [row(x, "answered_llm", wall=900.0) for x in "ABCD"]}
    a = be.analyze(REAL, heavy, {})
    assert a["latency"]["pays_for_itself"] is False and a["latency"]["net_ms_saved"] < 0


def test_failed_baseline_calls_are_ignored_and_no_data_is_reported_as_none():
    real = {"backend": "x", "rows": [row("A", "answered_non_llm", call(ok=False))]}
    a = be.analyze(real, STUB, {})
    assert a["baseline_mean_latency_ms"] is None and a["latency"] is None and a["tokens"]["share_of_baseline"] is None
    assert "Breakeven" in be.render_markdown(a)


def test_markdown_states_the_limits():
    md = be.render_markdown(be.analyze(REAL, STUB, {"B": "rag_small_model"}))
    assert "pays for itself: True" in md and "ceiling" in md and "OI-005" in md


def test_cli_refuses_swapped_inputs_and_reads_files(tmp_path, capsys):
    r, s = tmp_path / "r.json", tmp_path / "s.json"
    r.write_text(json.dumps(REAL)), s.write_text(json.dumps(STUB))
    assert be.main(["--real", str(r), "--stub", str(s), "--markdown", str(tmp_path / "o.md")]) == 0
    assert (tmp_path / "o.md").read_text().startswith("# Breakeven")
    assert be.main(["--real", str(s), "--stub", str(r)]) == 2                     # swapped: refused
    assert be.main(["--real", str(tmp_path / "missing.json"), "--stub", str(s)]) == 2
