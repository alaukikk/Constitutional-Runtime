
"""Breakeven: does skipping model calls pay for the runtime's own overhead? (ARCHITECTURE.md, cost/breakeven.py)

Inputs are MEASURED, from two runs of ``python -m evaluation.e2e_runner ... --json``:
  * a REAL run  (Groq etc.): per-call latency and tokens of the always-LLM baseline, which requests the
    runtime answered without a model;
  * a STUB run  (free, no network): the model takes ~0 ms, so each request's wall time is the runtime's
    own overhead (screen, policy, session, routing, validation, audit write).
Nothing here uses the catalog's placeholder cost or energy numbers, so no energy or dollar figure is
produced; those stay out until OI-005 is measured.

What it computes (all on the golden set, so only as representative as that set):
  * overhead per request (mean / median / p95), from the stub run;
  * the baseline's mean latency and tokens per model call, from the real run;
  * the share of requests that must skip a call for latency to break even, and the observed share;
  * net latency saved = (skipped calls x mean call latency) - (all requests x mean overhead);
  * tokens: the runtime adds no model tokens of its own, so every skipped call is a net token saving; the
    report states that figure, not an invented ratio;
  * an UPPER BOUND on what a RAG tier could still save: baseline tokens on requests the golden labels say
    a RAG small model could answer, assuming it answers them all correctly at zero token cost. The real
    saving is lower, because RAG itself spends tokens (retrieved context plus a small-model call).

Limits stated on purpose: overhead is measured on one machine and one run; the real run's latency
includes network time to the provider; blocked requests are not counted as savings (the baseline's
behaviour on them is unknown); answer quality is not part of a cost breakeven.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Iterable, Optional

RAG_TIER = "rag_small_model"


def _pct(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def overhead_stats(stub_report: dict) -> Optional[dict]:
    """Per-request wall time (ms) from a stub-backend run: the runtime's own cost. None if no rows."""
    vals = sorted(float(r["wall_ms"]) for r in stub_report.get("rows", []))
    if not vals:
        return None
    return {"n": len(vals), "mean_ms": round(statistics.fmean(vals), 3),
            "median_ms": round(statistics.median(vals), 3), "p95_ms": round(_pct(vals, 0.95), 3)}


def _ok_baseline(rows: Iterable[dict]) -> list[dict]:
    return [r for r in rows if r.get("baseline_call") and r["baseline_call"]["ok"]]


def analyze(real_report: dict, stub_report: dict, golden_tiers: dict[str, str]) -> dict:
    """golden_tiers maps item id -> cheapest_adequate_tier label."""
    rows = real_report.get("rows", [])
    answered = [r for r in rows if r["outcome"] in ("answered_non_llm", "answered_llm")]
    avoided = [r for r in answered if r["outcome"] == "answered_non_llm"]
    with_base = _ok_baseline(answered)
    ov = overhead_stats(stub_report)

    mean_lat = statistics.fmean(r["baseline_call"]["latency_ms"] for r in with_base) if with_base else None
    toks = [r["baseline_call"]["input_tokens"] + r["baseline_call"]["output_tokens"] for r in with_base
            if r["baseline_call"]["input_tokens"] is not None and r["baseline_call"]["output_tokens"] is not None]
    mean_tok = statistics.fmean(toks) if toks else None

    n_req = len(rows)
    out: dict = {"requests": n_req, "answered": len(answered), "skipped_calls": len(avoided),
                 "skipped_share_of_answered": round(len(avoided) / len(answered), 4) if answered else None,
                 "overhead": ov, "baseline_mean_latency_ms": round(mean_lat, 3) if mean_lat is not None else None,
                 "baseline_mean_tokens_per_call": round(mean_tok, 1) if mean_tok is not None else None}

    if ov and mean_lat:
        total_overhead = n_req * ov["mean_ms"]
        saved = len(avoided) * mean_lat
        out["latency"] = {
            "overhead_total_ms": round(total_overhead, 1), "skipped_calls_latency_ms": round(saved, 1),
            "net_ms_saved": round(saved - total_overhead, 1),
            "overhead_as_share_of_one_call": round(ov["mean_ms"] / mean_lat, 5),
            "breakeven_skipped_share_of_requests": round(ov["mean_ms"] / mean_lat, 5),
            "observed_skipped_share_of_requests": round(len(avoided) / n_req, 4) if n_req else None,
            "pays_for_itself": saved >= total_overhead}
    else:
        out["latency"] = None
    # Tokens: the runtime itself adds none, so the saving is exactly the tokens the baseline spent on the
    # requests the runtime answered without a model.
    avoided_ids = {r["id"] for r in avoided}
    avoided_tok = sum(r["baseline_call"]["input_tokens"] + r["baseline_call"]["output_tokens"]
                      for r in with_base if r["id"] in avoided_ids and r["baseline_call"]["input_tokens"] is not None
                      and r["baseline_call"]["output_tokens"] is not None)
    base_total = sum(toks) if toks else None
    out["tokens"] = {"avoided_call_tokens": avoided_tok,
                     "share_of_baseline": round(avoided_tok / base_total, 4) if base_total else None,
                     "runtime_adds_model_tokens": False}

    rag = [r for r in with_base if r["outcome"] == "answered_llm" and golden_tiers.get(r["id"]) == RAG_TIER
           and r["baseline_call"]["input_tokens"] is not None and r["baseline_call"]["output_tokens"] is not None]
    rag_tok = sum(r["baseline_call"]["input_tokens"] + r["baseline_call"]["output_tokens"] for r in rag)
    out["rag_upper_bound"] = {"requests": len(rag), "baseline_tokens": rag_tok,
                              "share_of_baseline": round(rag_tok / base_total, 4) if base_total else None,
                              "assumes": "RAG answers all of them correctly at zero token cost; real saving is lower"}
    return out


def render_markdown(a: dict) -> str:
    L = ["# Breakeven: runtime overhead vs model calls skipped", "",
         "Measured on the golden set from one real run and one stub run. Not a claim about real traffic; no energy or "
         "dollar figures (catalog inputs are placeholders, OI-005).", ""]
    ov = a["overhead"]
    L.append(f"- requests {a['requests']}, answered {a['answered']}, model calls skipped {a['skipped_calls']} "
             f"({a['skipped_share_of_answered']} of answered)")
    if ov:
        L.append(f"- runtime overhead per request (stub run): mean {ov['mean_ms']} ms, median {ov['median_ms']} ms, p95 {ov['p95_ms']} ms")
    L.append(f"- baseline model call: mean {a['baseline_mean_latency_ms']} ms, {a['baseline_mean_tokens_per_call']} tokens")
    lat = a["latency"]
    if lat:
        L += ["", "## Latency", f"- overhead is {lat['overhead_as_share_of_one_call']} of one model call; breakeven needs "
              f"{lat['breakeven_skipped_share_of_requests']} of requests to skip a call, observed {lat['observed_skipped_share_of_requests']}",
              f"- net latency saved: {lat['net_ms_saved']} ms ({lat['skipped_calls_latency_ms']} ms of calls skipped minus "
              f"{lat['overhead_total_ms']} ms overhead); pays for itself: {lat['pays_for_itself']}"]
    t = a["tokens"]
    L += ["", "## Tokens", f"- skipped calls would have cost {t['avoided_call_tokens']} tokens ({t['share_of_baseline']} of the baseline total); "
          "the runtime adds no model tokens, so this is a net saving."]
    r = a["rag_upper_bound"]
    L += ["", "## Upper bound for a RAG tier", f"- {r['requests']} request(s) the labels say RAG could answer; the baseline spent "
          f"{r['baseline_tokens']} tokens on them ({r['share_of_baseline']} of the baseline total).",
          f"- {r['assumes']}.", "- Read it as a ceiling that decides whether RAG is worth building: if the ceiling is small, it is not."]
    return "\n".join(L) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--real", type=Path, required=True, help="e2e --json report from a real backend")
    ap.add_argument("--stub", type=Path, required=True, help="e2e --json report from the stub backend (free)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    a = ap.parse_args(argv)
    from evaluation import golden_set as gs
    try:
        real = json.loads(a.real.read_text(encoding="utf-8"))
        stub = json.loads(a.stub.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("could not read the two report files (paths or JSON)", file=sys.stderr)
        return 2
    if real.get("backend") == "stub":
        print("--real points at a stub-backend report; it has no real latency or tokens", file=sys.stderr)
        return 2
    if stub.get("backend") != "stub":
        print("--stub must be a stub-backend report (otherwise model latency is counted as overhead)", file=sys.stderr)
        return 2
    res = analyze(real, stub, {i.id: i.cheapest_adequate_tier for i in gs.load()})
    if a.json:
        a.json.write_text(json.dumps(res, indent=2, sort_keys=True), encoding="utf-8")
    md = render_markdown(res)
    if a.markdown:
        a.markdown.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
