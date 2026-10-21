
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
  * answer QUALITY (no judge, no expected answers); a cheap tier's answer is not checked, so a
    "saving" is a saving in calls and tokens, not proof the answer was as good;
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
from typing import Callable, Iterable, Optional

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
    latency_ms: float


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
        try:
            out = super().complete(request_text, model_name)
        except LLMGatewayError as exc:
            self._calls.append(LLMCall(model_name, False, exc.code, None, None,
                                       round((time.perf_counter() - t0) * 1000, 3)))
            raise
        m = self.last_measurement if self.config.backend == "anthropic" else None
        self._calls.append(LLMCall(model_name, True, "", m.input_tokens if m else None,
                                   m.output_tokens if m else None, round((time.perf_counter() - t0) * 1000, 3)))
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
            return Observed("error", False, False, None, None, gateway.drain(),
                            round((time.perf_counter() - t0) * 1000, 3), error=type(exc).__name__)
        return Observed(res.tier_used, bool(res.blocked), bool(res.needs_confirmation), res.block_reason,
                        res.validation_status, gateway.drain(), round((time.perf_counter() - t0) * 1000, 3))

    return observe


# -- scoring ------------------------------------------------------------------------------------
def run(items: Iterable[gs.GoldenItem], observe: Callable[[gs.GoldenItem], Observed],
        gateway: RecordingGateway, baseline_alias: str) -> dict:
    items = list(items)
    rows = []
    for it in items:
        o = observe(it)
        oc = outcome_of(o)
        base: Optional[LLMCall] = None
        if oc in ("answered_non_llm", "answered_llm"):
            gateway.drain()
            try:
                gateway.complete(it.text, baseline_alias)
            except LLMGatewayError:
                pass                                            # recorded as a failed baseline call
            calls = gateway.drain()
            base = calls[0] if calls else None
        rows.append({"id": it.id, "tags": list(it.tags), "expected_gate": it.expected_gate, "outcome": oc,
                     "tier_used": o.tier_used, "block_reason": o.block_reason, "validation_status": o.validation_status,
                     "error": o.error, "wall_ms": o.wall_ms, "runtime_calls": [asdict(c) for c in o.llm_calls],
                     "baseline_call": asdict(base) if base else None,
                     "gate_agrees": oc in _EXPECTED_OUTCOME[it.expected_gate]})
    return summarize(items, rows, baseline_alias, gateway.config.backend)


def summarize(items: list[gs.GoldenItem], rows: list[dict], baseline_alias: str, backend: str) -> dict:
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
                   "baseline_out": b_out, "saving_vs_baseline": saving},
        "latency_ms": {"runtime_total": round(sum(r["wall_ms"] for r in answered), 3),
                       "baseline_total": round(sum(c["latency_ms"] for c in base_calls), 3)},
        "rows": rows,
    }


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
          "Not measured: answer quality, cache tier, energy or dollars, confirmation outcomes. Single run.", "",
          "## Outcomes", *[f"- {k}: {v}" for k, v in rep["outcomes"].items()],
          f"- agreement with golden expected gate: {g['agree']}/{g['n']}; disagreements {g['disagreements']}", "",
          "## Runtime vs baseline (answered requests only)",
          f"- answered {a['n']}: {a['non_llm']} without the LLM ({a['non_llm_share']}), {a['llm']} by the LLM; by tier {a['by_tier']}",
          f"- LLM calls: runtime {rep['llm_calls']['runtime']} (failed {rep['llm_calls']['runtime_failed']}), "
          f"baseline {rep['llm_calls']['baseline']} (failed {rep['llm_calls']['baseline_failed']})"]
    if t["measured"]:
        L.append(f"- tokens (provider-reported): runtime {t['runtime_in']} in / {t['runtime_out']} out; "
                 f"baseline {t['baseline_in']} in / {t['baseline_out']} out; saving vs baseline {t['saving_vs_baseline']}")
    else:
        L.append("- tokens: not measured (stub backend or the provider reported none)")
    L += [f"- wall latency, summed: runtime {rep['latency_ms']['runtime_total']} ms, baseline {rep['latency_ms']['baseline_total']} ms", "",
          "## Per item", "| id | expected gate | outcome | tier | runtime LLM calls | note |", "|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        note = ("" if r["gate_agrees"] else "GATE DISAGREES; ") + (f"error {r['error']}" if r["error"] else "")
        L.append(f"| {r['id']} | {r['expected_gate']} | {r['outcome']} | {r['tier_used']} | {len(r['runtime_calls'])} | {note} |")
    return "\n".join(L) + "\n"


# -- command line -------------------------------------------------------------------------------
def preflight(cfg: GatewayConfig, baseline_alias: str) -> list[str]:
    if cfg.backend != "anthropic":
        return []
    from cost.model_registry import MODEL_CATALOG
    out = [] if cfg.api_key else ["ANTHROPIC_API_KEY is not set"]
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
    if gateway.config.backend == "anthropic":
        print(f"REAL backend: up to about {2 * len(items)} billable calls plus any repair calls "
              f"({len(items)} items, baseline {a.baseline_alias}).", file=sys.stderr)
        if not a.yes_spend:
            print("refusing to spend without --yes-spend", file=sys.stderr)
            return 2
    set_gateway(gateway)
    try:
        if observe_factory is not None:
            rep = run(items, observe_factory(gateway), gateway, a.baseline_alias)
        else:
            with scratch_environment(a.workdir):
                rep = run(items, real_pipeline(gateway), gateway, a.baseline_alias)
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
