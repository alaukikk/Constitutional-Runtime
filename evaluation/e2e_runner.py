

"""End-to-end run of the REAL pipeline on the golden set, against an always-call-the-LLM baseline.

Sprint 7-8, steps 2 and 4 of the plan: "does the runtime save anything, and at what cost to safety".
It drives ``api.main.process_request`` (the actual Stage 0 -> 7 pipeline, not a re-implementation)
in-process, one fresh session per item, with a scratch audit log, a scratch HMAC key and an
in-memory cache. Then, for every request the runtime ANSWERED, it makes one baseline call
("send it straight to one fixed model") so token use can be compared like for like.

Spending: with LLM_BACKEND=anthropic this makes REAL, BILLABLE calls (roughly one per answered
LLM-rung item plus one baseline call per answered item, plus any repair call). It therefore
refuses to run without ``--yes-spend`` and prints the upper bound first. The default backend is
the stub, which spends nothing and measures nothing about tokens.

The baseline model is the owner's decision and has no default: ``--baseline-alias`` is required.
The savings figure depends heavily on it (a small baseline makes the runtime look worse, a large
one better), so the report prints it next to every number.

What this DOES report: outcome per item (answered by a non-LLM rung / by the LLM / blocked /
needs confirmation / error), agreement with the golden expected gate, provider-reported token
counts and wall latency for runtime vs baseline on the answered items.
What it does NOT report, on purpose:
  * free-text answer QUALITY (no judge). Only items carrying an expected_answer are scored, by
    containment (golden_set.answer_matches); everything else is unchecked, so a "saving" there is a
    saving in calls and tokens, not proof the answer was as good;
  * the cache tier (cold in-memory cache, stateless run);
  * energy or dollars (catalog cost/energy inputs are placeholders, OI-005; tokens only);
  * anything about confirmation outcomes: a REQUIRE_HUMAN request stops at "needs confirmation".
Single run, temperature 0 by default, hand-written set: diagnostic until the golden set is
owner-reviewed and frozen (the banner says so).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from evaluation import golden_set as gs
from llm.gateway import (GatewayConfig, GatewayConfigError, LLMGateway, LLMGatewayError, STUB_MODEL,
                         set_gateway)

LLM_TIERS = ("llm_low_reasoning", "llm_high_reasoning")
OUTCOMES = ("answered_non_llm", "answered_llm", "blocked", "needs_confirmation", "error")
_EXPECTED_OUTCOME = {"allow": ("answered_non_llm", "answered_llm"), "flag": ("answered_non_llm", "answered_llm"),
                     "require_human": ("needs_confirmation",), "block": ("blocked",)}


@dataclass(frozen=True)
class LLMCall:
    alias: str
    ok: bool
    error_code: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: float                    # the call itself; pacing waits are NOT included
    paced_ms: float = 0.0                # time spent waiting for the pacing interval before the call


@dataclass(frozen=True)
class Observed:
    tier_used: str
    blocked: bool
    needs_confirmation: bool
    block_reason: Optional[str]
    validation_status: Optional[str]
    llm_calls: tuple[LLMCall, ...]
    wall_ms: float
    error: str = ""                      # exception CLASS name only, never a message
    answer: str = ""                     # response text; used ONLY to score expected_answer, never stored in the report


def outcome_of(o: Observed) -> str:
    if o.error:
        return "error"
    if o.needs_confirmation:
        return "needs_confirmation"
    if o.blocked:
        return "blocked"
    return "answered_llm" if o.tier_used in LLM_TIERS else "answered_non_llm"


class RecordingGateway(LLMGateway):
    """The normal gateway, plus a per-call log (alias, tokens, latency) the runner drains per item."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._calls: list[LLMCall] = []

    def complete(self, request_text: str, model_name: str = STUB_MODEL) -> str:
        t0 = time.perf_counter()
        self.last_wait_s = 0.0
        try:
            out = super().complete(request_text, model_name)
        except LLMGatewayError as exc:
            paced = round(self.last_wait_s * 1000, 3)
            self._calls.append(LLMCall(model_name, False, exc.code, None, None,
                                       max(0.0, round((time.perf_counter() - t0) * 1000 - paced, 3)), paced))
            raise
        paced = round(self.last_wait_s * 1000, 3)
        m = self.last_measurement if self.config.backend != "stub" else None
        # A real call's latency is the gateway's own measurement (it starts after the pacing wait).
        latency = m.latency_ms if m else max(0.0, round((time.perf_counter() - t0) * 1000 - paced, 3))
        self._calls.append(LLMCall(model_name, True, "", m.input_tokens if m else None,
                                   m.output_tokens if m else None, latency, paced))
        return out

    def drain(self) -> tuple[LLMCall, ...]:
        calls, self._calls = tuple(self._calls), []
        return calls


# -- the real pipeline, isolated ----------------------------------------------------------------
class _DictRedis:
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value


@contextlib.contextmanager
def scratch_environment(workdir: Optional[Path] = None):
    """Run in a scratch directory (the audit log path is relative), with a throwaway audit HMAC key and
    an in-memory cache, so a run never touches the owner's audit log, key or Redis. Everything is
    restored on exit."""
    import tiers.cache_lookup as cache_lookup
    from audit.request_evidence import ENV_KEY, ENV_KEY_ID

    own = tempfile.TemporaryDirectory() if workdir is None else None
    path = Path(own.name) if own else Path(workdir)
    path.mkdir(parents=True, exist_ok=True)
    old_cwd, old_env, old_client = os.getcwd(), {k: os.environ.get(k) for k in (ENV_KEY, ENV_KEY_ID)}, cache_lookup._client
    try:
        os.chdir(path)
        os.environ[ENV_KEY], os.environ[ENV_KEY_ID] = "e2e-scratch-" + secrets.token_hex(16), "e2e-scratch"
        cache_lookup.configure_client(_DictRedis())
        yield path
    finally:
        os.chdir(old_cwd)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cache_lookup._client = old_client
        if own:
            own.cleanup()


def _unpaced_ms(t0: float, calls: tuple) -> float:
    """Wall time since t0 minus the time spent waiting for the pacing interval (a rate-limit courtesy,
    not part of what the pipeline costs)."""
    return max(0.0, round((time.perf_counter() - t0) * 1000 - sum(c.paced_ms for c in calls), 3))


def real_pipeline(gateway: RecordingGateway) -> Callable[[gs.GoldenItem], Observed]:
    """Adapter over api.main.process_request. Call inside scratch_environment()."""
    import api.main as main
    from session.session_state import SessionManager

    def observe(item: gs.GoldenItem) -> Observed:
        gateway.drain()
        main.configure_session_manager(SessionManager())          # fresh risk/cost state per item
        t0 = time.perf_counter()
        try:
            res = main.process_request(item.text, session_id=f"e2e-{item.id}")
        except Exception as exc:
            calls = gateway.drain()
            return Observed("error", False, False, None, None, calls, _unpaced_ms(t0, calls),
                            error=type(exc).__name__)
        calls = gateway.drain()
        return Observed(res.tier_used, bool(res.blocked), bool(res.needs_confirmation), res.block_reason,
                        res.validation_status, calls, _unpaced_ms(t0, calls), answer=res.response or "")

    return observe


# -- scoring ------------------------------------------------------------------------------------
def run(items: Iterable[gs.GoldenItem], observe: Callable[[gs.GoldenItem], Observed],
        gateway: RecordingGateway, baseline_alias: str,
        progress: Optional[Callable[[str], None]] = None, second_pass: bool = False) -> dict:
    items = list(items)
    rows = []
    for n, it in enumerate(items, 1):
        o = observe(it)
        oc = outcome_of(o)
        base: Optional[LLMCall] = None
        base_text = ""
        if oc in ("answered_non_llm", "answered_llm"):
            gateway.drain()
            try:
                base_text = gateway.complete(it.text, baseline_alias)
            except LLMGatewayError:
                pass                                            # recorded as a failed baseline call
            calls = gateway.drain()
            base = calls[0] if calls else None
        rows.append({"id": it.id, "tags": list(it.tags), "expected_gate": it.expected_gate, "outcome": oc,
                     "tier_used": o.tier_used, "block_reason": o.block_reason, "validation_status": o.validation_status,
                     "error": o.error, "wall_ms": o.wall_ms, "runtime_calls": [asdict(c) for c in o.llm_calls],
                     "baseline_call": asdict(base) if base else None,
                     "gate_agrees": oc in _EXPECTED_OUTCOME[it.expected_gate],
                     # True/False only for answered items that have an expected_answer; None otherwise.
                     "runtime_correct": (gs.answer_matches(it.expected_answer, o.answer)
                                         if it.expected_answer and oc.startswith("answered") else None),
                     "baseline_correct": (gs.answer_matches(it.expected_answer, base_text)
                                          if it.expected_answer and base is not None and base.ok else None)})
        if progress:
            progress(f"[{n}/{len(items)}] {it.id} {oc} tier={o.tier_used} runtime_llm_calls={len(o.llm_calls)}"
                     + (f" baseline={'ok' if base and base.ok else 'failed'}" if oc.startswith("answered") else ""))
    rep = summarize(items, rows, baseline_alias, gateway.config.backend, gateway.config.model_map)
    if second_pass:
        rep["repeat"] = _repeat_pass(items, rows, observe, gateway, progress)
    return rep


def _calls_tokens(calls) -> Optional[int]:
    ok = [c for c in calls if c.ok]
    if any(c.input_tokens is None or c.output_tokens is None for c in ok):
        return None
    return sum(c.input_tokens + c.output_tokens for c in ok)


def _repeat_pass(items: list[gs.GoldenItem], rows: list[dict], observe, gateway, progress) -> dict:
    """Send every request that was ANSWERED in the first pass again, in the same scratch environment
    (the in-memory cache is warm, session state is fresh per item). Measures the cache tier: how many
    repeats are served without a model call and how many tokens that saves. Repeated requests are what a
    cache is for; the golden set has none, so the first pass can never show it."""
    first = {r["id"]: r for r in rows}
    out = []
    for it in items:
        r1 = first[it.id]
        if r1["outcome"] not in ("answered_non_llm", "answered_llm"):
            continue
        o = observe(it)
        oc = outcome_of(o)
        out.append({"id": it.id, "first_outcome": r1["outcome"], "first_tier": r1["tier_used"],
                    "first_runtime_calls": len(r1["runtime_calls"]),
                    "first_tokens": sum(c["input_tokens"] + c["output_tokens"] for c in r1["runtime_calls"] if c["ok"]
                                        and c["input_tokens"] is not None and c["output_tokens"] is not None),
                    "second_outcome": oc, "second_tier": o.tier_used, "second_runtime_calls": len(o.llm_calls),
                    "second_tokens": _calls_tokens(o.llm_calls), "second_wall_ms": o.wall_ms,
                    "first_wall_ms": r1["wall_ms"]})
        if progress:
            progress(f"[repeat] {it.id} {oc} tier={o.tier_used} runtime_llm_calls={len(o.llm_calls)}")
    cache_hits = [x for x in out if x["second_tier"] == "cache_lookup"]
    llm_first = [x for x in out if x["first_runtime_calls"] > 0]
    return {"requests": len(out), "served_from_cache": len(cache_hits),
            "llm_calls_first": sum(x["first_runtime_calls"] for x in out),
            "llm_calls_second": sum(x["second_runtime_calls"] for x in out),
            "tokens_first": sum(x["first_tokens"] for x in out),
            "tokens_second": (None if any(x["second_tokens"] is None for x in out)
                              else sum(x["second_tokens"] for x in out)),
            "llm_requests_first": len(llm_first),
            "llm_requests_cached_second": sum(1 for x in llm_first if x["second_tier"] == "cache_lookup"),
            "wall_ms_first": round(sum(x["first_wall_ms"] for x in out), 3),
            "wall_ms_second": round(sum(x["second_wall_ms"] for x in out), 3), "rows": out}


def summarize(items: list[gs.GoldenItem], rows: list[dict], baseline_alias: str, backend: str,
              model_map: Optional[Mapping[str, str]] = None) -> dict:
    counts = {k: sum(1 for r in rows if r["outcome"] == k) for k in OUTCOMES}
    answered = [r for r in rows if r["outcome"] in ("answered_non_llm", "answered_llm")]
    rt_calls = [c for r in answered for c in r["runtime_calls"]]
    base_calls = [r["baseline_call"] for r in answered if r["baseline_call"]]
    ok_rt, ok_base = [c for c in rt_calls if c["ok"]], [c for c in base_calls if c["ok"]]
    every = ok_rt + ok_base
    have_tokens = bool(ok_base) and all(c["input_tokens"] is not None and c["output_tokens"] is not None for c in every)
    rt_in = sum(c["input_tokens"] for c in ok_rt) if have_tokens else None
    rt_out = sum(c["output_tokens"] for c in ok_rt) if have_tokens else None
    b_in = sum(c["input_tokens"] for c in ok_base) if have_tokens else None
    b_out = sum(c["output_tokens"] for c in ok_base) if have_tokens else None
    b_tot = (b_in + b_out) if have_tokens else None
    saving = round(1 - (rt_in + rt_out) / b_tot, 4) if have_tokens and b_tot else None
    # Spend on requests that were NOT answered (withheld after a model call, errors): real cost the runtime
    # incurred and the answered-only comparison above leaves out.
    unanswered = [r for r in rows if r["outcome"] not in ("answered_non_llm", "answered_llm") and r["runtime_calls"]]
    un_calls = [c for r in unanswered for c in r["runtime_calls"]]
    un_ok = [c for c in un_calls if c["ok"]]
    un_tokens = (sum(c["input_tokens"] + c["output_tokens"] for c in un_ok)
                 if have_tokens and all(c["input_tokens"] is not None for c in un_ok) else None)
    saving_all = (round(1 - ((rt_in + rt_out) + un_tokens) / b_tot, 4)
                  if have_tokens and b_tot and un_tokens is not None else None)
    decomposition = _decompose(answered, baseline_alias, model_map or {}, have_tokens, b_tot)
    prov = {"items": len(items), "labelers": dict(_count(i.labeler for i in items)),
            "reviews": dict(_count(i.review for i in items)), "splits": dict(_count(i.split for i in items)),
            "fingerprint": gs.fingerprint(items) if items else None}
    return {
        "diagnostic_only": bool(gs.unreviewed(items)) or any(i.split != "frozen" for i in items),
        "backend": backend, "baseline_alias": baseline_alias, "provenance": prov, "outcomes": counts,
        "gate_agreement": {"agree": sum(1 for r in rows if r["gate_agrees"]), "n": len(rows),
                           "disagreements": [r["id"] for r in rows if not r["gate_agrees"]]},
        "answered": {"n": len(answered), "non_llm": counts["answered_non_llm"], "llm": counts["answered_llm"],
                     "non_llm_share": round(counts["answered_non_llm"] / len(answered), 4) if answered else None,
                     "by_tier": dict(_count(r["tier_used"] for r in answered))},
        "llm_calls": {"runtime": len(rt_calls), "runtime_failed": len(rt_calls) - len(ok_rt),
                      "baseline": len(base_calls), "baseline_failed": len(base_calls) - len(ok_base)},
        "tokens": {"measured": have_tokens, "runtime_in": rt_in, "runtime_out": rt_out, "baseline_in": b_in,
                   "baseline_out": b_out, "saving_vs_baseline": saving, "decomposition": decomposition,
                   "unanswered_spend": {"requests": len(unanswered), "ids": [r["id"] for r in unanswered],
                                        "calls": len(un_calls), "tokens": un_tokens},
                   "saving_vs_baseline_incl_unanswered": saving_all},
        "correctness": _correctness(rows),
        "latency_ms": {"runtime_total": round(sum(r["wall_ms"] for r in answered), 3),
                       "baseline_total": round(sum(c["latency_ms"] for c in base_calls), 3)},
        "rows": rows,
    }


def _correctness(rows: list[dict]) -> dict:
    """Containment-scored correctness on answered items that have an expected_answer (see
    golden_set.answer_matches for what a pass means). Split by whether the runtime used an LLM, because
    the wrong-answer rate of the NON-LLM tiers is the cost of routing cheaply."""
    scored = [r for r in rows if r.get("runtime_correct") is not None]

    def block(rs: list[dict]) -> dict:
        b = [r for r in rs if r.get("baseline_correct") is not None]
        return {"n": len(rs), "runtime_correct": sum(1 for r in rs if r["runtime_correct"]),
                "wrong_ids": [r["id"] for r in rs if not r["runtime_correct"]],
                "baseline_n": len(b), "baseline_correct": sum(1 for r in b if r["baseline_correct"]),
                "baseline_wrong_ids": [r["id"] for r in b if not r["baseline_correct"]]}
    return {"scored": len(scored),
            "non_llm": block([r for r in scored if r["outcome"] == "answered_non_llm"]),
            "llm": block([r for r in scored if r["outcome"] == "answered_llm"])}


def _tok(call: dict) -> int:
    return call["input_tokens"] + call["output_tokens"]


def _decompose(answered: list[dict], baseline_alias: str, model_map: Mapping[str, str], have_tokens: bool,
               baseline_total: Optional[int]) -> Optional[dict]:
    """Split the token comparison into what routing CAUSED and what is run-to-run variation.

    avoided: requests answered with no LLM call at all. Their cost is exactly what the baseline spent on
             them, so this is the effect attributable to the runtime.
    llm_routed: requests the runtime also sent to a model. If the runtime's model and the baseline's are
             the SAME underlying model, both sides send the same text to the same model, so any
             difference is sampling variation (reasoning models vary between identical calls), not a
             saving. If the models differ, the difference mixes model choice with that variation."""
    if not have_tokens:
        return None
    provider = lambda alias: model_map.get(alias, alias)
    ok_base = lambda r: r["baseline_call"] is not None and r["baseline_call"]["ok"]
    avoided = [r for r in answered if r["outcome"] == "answered_non_llm" and ok_base(r)]
    routed = [r for r in answered if r["outcome"] == "answered_llm" and ok_base(r)
              and r["runtime_calls"] and all(c["ok"] for c in r["runtime_calls"])]
    avoided_tokens = sum(_tok(r["baseline_call"]) for r in avoided)
    rt = sum(_tok(c) for r in routed for c in r["runtime_calls"])
    base = sum(_tok(r["baseline_call"]) for r in routed)
    same = all(provider(c["alias"]) == provider(baseline_alias) for r in routed for c in r["runtime_calls"])
    return {"avoided_calls": len(avoided), "avoided_call_tokens": avoided_tokens,
            "avoided_share_of_baseline": round(avoided_tokens / baseline_total, 4) if baseline_total else None,
            "llm_routed": {"n": len(routed), "runtime_tokens": rt, "baseline_tokens": base,
                           "difference": rt - base, "same_underlying_model": same}}


def _count(it):
    out: dict = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out.items()


def render_markdown(rep: dict) -> str:
    p, a, t, g = rep["provenance"], rep["answered"], rep["tokens"], rep["gate_agreement"]
    L = ["# Golden set: end-to-end run vs always-LLM baseline", ""]
    if rep["diagnostic_only"]:
        L += ["> **DIAGNOSTIC ONLY.** Labels are unreviewed drafts and/or the set is not frozen.", ""]
    L += [f"Backend `{rep['backend']}`; baseline alias `{rep['baseline_alias']}` (owner's choice; the saving depends on it). "
          f"Items {p['items']}; fingerprint `{p['fingerprint']}`.", "",
          "Not measured: free-text answer quality (only items with an expected_answer are scored, by containment), "
          "cache tier, energy or dollars, confirmation outcomes. Single run.", "",
          "## Outcomes", *[f"- {k}: {v}" for k, v in rep["outcomes"].items()],
          f"- agreement with golden expected gate: {g['agree']}/{g['n']}; disagreements {g['disagreements']}", "",
          "## Runtime vs baseline (answered requests only)",
          f"- answered {a['n']}: {a['non_llm']} without the LLM ({a['non_llm_share']}), {a['llm']} by the LLM; by tier {a['by_tier']}",
          f"- LLM calls: runtime {rep['llm_calls']['runtime']} (failed {rep['llm_calls']['runtime_failed']}), "
          f"baseline {rep['llm_calls']['baseline']} (failed {rep['llm_calls']['baseline_failed']})"]
    if t["measured"]:
        L.append(f"- tokens (provider-reported): runtime {t['runtime_in']} in / {t['runtime_out']} out; "
                 f"baseline {t['baseline_in']} in / {t['baseline_out']} out; all-in difference vs baseline "
                 f"{t['saving_vs_baseline']} (includes run-to-run variation, see below)")
        u = t.get("unanswered_spend")
        if u and u["calls"]:
            L.append(f"  - **Spend on requests with no answer delivered** (withheld/error): {u['requests']} request(s) {u['ids']}, "
                     f"{u['calls']} call(s), {u['tokens']} tokens; all-in difference including it: "
                     f"{t.get('saving_vs_baseline_incl_unanswered')}")
        d = t.get("decomposition")
        if d:
            r = d["llm_routed"]
            L.append(f"  - **Caused by routing:** {d['avoided_calls']} request(s) needed no LLM call; the baseline spent "
                     f"{d['avoided_call_tokens']} tokens on them ({d['avoided_share_of_baseline']} of the baseline total).")
            L.append(f"  - LLM-routed requests ({r['n']}): runtime {r['runtime_tokens']} vs baseline {r['baseline_tokens']} tokens "
                     f"(difference {r['difference']}). " + (
                         "Both sides used the same underlying model on the same text, so this difference is "
                         "run-to-run variation, not a saving." if r["same_underlying_model"] else
                         "The models differ, so this mixes model choice with run-to-run variation."))
    else:
        L.append("- tokens: not measured (stub backend or the provider reported none)")
    c = rep.get("correctness") or {"scored": 0}
    if c["scored"]:
        n, m = c["non_llm"], c["llm"]
        L += ["", "## Correctness (items with an expected_answer; containment check, so a pass is generous)",
              f"- answered without the LLM: {n['runtime_correct']}/{n['n']} correct" + (f"; WRONG {n['wrong_ids']}" if n["wrong_ids"] else "")
              + f" (baseline on the same kind of item: {n['baseline_correct']}/{n['baseline_n']})",
              f"- answered by the LLM: {m['runtime_correct']}/{m['n']} correct" + (f"; wrong {m['wrong_ids']}" if m["wrong_ids"] else "")
              + f" (baseline: {m['baseline_correct']}/{m['baseline_n']}" + (f"; wrong {m['baseline_wrong_ids']}" if m["baseline_wrong_ids"] else "") + ")",
              "- Reading: a wrong non-LLM answer is the price of routing cheaply; compare it with the baseline's misses. "
              "Verbose or reasoning-model answers can fail a containment check while being right, so inspect misses by hand.", ""]
    rp = rep.get("repeat")
    if rp:
        L += ["", "## Repeated requests (cache tier; same requests sent a second time, warm in-memory cache)",
              f"- {rp['requests']} answered requests repeated; {rp['served_from_cache']} served from the cache",
              f"- of the {rp['llm_requests_first']} that needed a model call the first time, {rp['llm_requests_cached_second']} "
              f"needed none the second time",
              f"- runtime LLM calls: first pass {rp['llm_calls_first']}, second pass {rp['llm_calls_second']}",
              f"- runtime tokens: first pass {rp['tokens_first']}, second pass {rp['tokens_second']}",
              f"- wall time: first pass {rp['wall_ms_first']} ms, second pass {rp['wall_ms_second']} ms",
              "- A cache saves only what users repeat; the golden set was not written to be repeated, so this is the "
              "ceiling for an all-repeats workload, not an estimate for real traffic.", ""]
    L += [f"- wall latency, summed: runtime {rep['latency_ms']['runtime_total']} ms, baseline {rep['latency_ms']['baseline_total']} ms", "",
          "## Per item", "| id | expected gate | outcome | tier | runtime LLM calls | note |", "|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        note = ("" if r["gate_agrees"] else "GATE DISAGREES; ") + (f"error {r['error']}" if r["error"] else "")
        L.append(f"| {r['id']} | {r['expected_gate']} | {r['outcome']} | {r['tier_used']} | {len(r['runtime_calls'])} | {note} |")
    return "\n".join(L) + "\n"


# -- command line -------------------------------------------------------------------------------
def preflight(cfg: GatewayConfig, baseline_alias: str) -> list[str]:
    if cfg.backend == "stub":
        return []
    from cost.model_registry import MODEL_CATALOG
    out = [] if cfg.api_key else ["the API key variable for this backend is not set (ANTHROPIC_API_KEY or LLM_API_KEY)"]
    need = sorted({m.name for m in MODEL_CATALOG} | {baseline_alias})
    missing = [n for n in need if n not in cfg.model_map]
    if missing:
        out.append(f"LLM_MODEL_MAP has no entry for: {', '.join(missing)}")
    return out


def main(argv: Optional[list[str]] = None, *, observe_factory=None, gateway: Optional[RecordingGateway] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline-alias", required=True, help="catalog name every baseline call is sent to (owner's choice)")
    ap.add_argument("--split", choices=("dev", "frozen", "all"), default="all")
    ap.add_argument("--limit", type=int, help="only the first N items (a cheap trial run)")
    ap.add_argument("--yes-spend", action="store_true", help="required for a real backend: you accept billable calls")
    ap.add_argument("--workdir", type=Path, help="keep the scratch audit log here instead of a temp dir")
    ap.add_argument("--second-pass", action="store_true",
                    help="after the main run, send every answered request again (warm cache) to measure the cache tier")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    a = ap.parse_args(argv)
    items = [i for i in gs.load() if a.split == "all" or i.split == a.split][: a.limit]
    if gateway is None:
        try:
            gateway = RecordingGateway(GatewayConfig.from_env())
        except GatewayConfigError as exc:
            print(f"configuration error: {exc}", file=sys.stderr)
            return 2
    bad = preflight(gateway.config, a.baseline_alias)
    if bad:
        print("not started:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 2
    if gateway.config.backend != "stub":
        print(f"REAL backend: up to about {2 * len(items)} billable calls plus any repair calls "
              f"({len(items)} items, baseline {a.baseline_alias}).", file=sys.stderr)
        if not a.yes_spend:
            print("refusing to spend without --yes-spend", file=sys.stderr)
            return 2
    def _progress(line: str) -> None:
        print(line, file=sys.stderr, flush=True)              # stderr, so the report on stdout stays clean

    set_gateway(gateway)
    try:
        if observe_factory is not None:
            rep = run(items, observe_factory(gateway), gateway, a.baseline_alias, _progress, a.second_pass)
        else:
            with scratch_environment(a.workdir):
                rep = run(items, real_pipeline(gateway), gateway, a.baseline_alias, _progress, a.second_pass)
    finally:
        set_gateway(None)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    md = render_markdown(rep)
    if a.markdown:
        a.markdown.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
