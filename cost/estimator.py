
"""Stage 3 cost estimator: energy / dollars / latency for a request on a given tier.

Energy for LLM tiers comes from measured anchors in cost/model_registry.py
(How Hungry is AI, Table 4), interpolated on total tokens. Requests outside the
measured range (400 - 11,500 total tokens for the catalog models) are flagged and
given a wide range instead of a falsely precise number.

Everything marked PLACEHOLDER below is an unmeasured assumption. Do not put
placeholder-derived numbers in a headline savings claim.
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from typing import Iterable, Optional

from cost.model_registry import EnergyAnchor, ModelInfo
from policy.schemas import MethodTier, RequestType, TierCostEstimate

# ---- token estimate (no tokenizer dependency; PLACEHOLDER heuristic) -------------
# ASCII text is ~4 chars per token. Non-ASCII characters (CJK, Devanagari, emoji, ...) are
# counted as 1 token each: real tokenizers typically need 1-3 tokens per such character, so
# this still leans low for some scripts but avoids the ~25-60% undercount of a bytes/4 rule.
# Replace with a real tokenizer once one is a dependency, and check the result with
# triage/bias_monitor.py, since token counts differ by language.
ASCII_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("request text must be a str")
    # errors="ignore": lone surrogates (valid in JSON input) must not crash the router
    ascii_chars = len(text.encode("ascii", errors="ignore"))
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / ASCII_CHARS_PER_TOKEN) + non_ascii_chars)


# ---- reasoning depth ---------------------------------------------------------------
# How Hungry is AI, GPT-5 case study: medium queries use 2.33 Wh at minimal reasoning and
# 17.15 Wh at high reasoning. Borrowed as a multiplier for our low/high tiers (the anchors
# are for non-reasoning GPT-4.1 models). The same ratio is used as a PROXY for dollars and
# latency, since reasoning tokens are extra generated (and billed) tokens.
REASONING_MULTIPLIER_HIGH = 17.15 / 2.33
_REASONING_MULTIPLIER = {
    MethodTier.LLM_LOW_REASONING: 1.0,
    MethodTier.LLM_HIGH_REASONING: REASONING_MULTIPLIER_HIGH,
}

# ---- non-LLM tiers: CPU time x assumed power (PLACEHOLDER, unmeasured) ---------------
CPU_POWER_W = 20.0
NON_LLM_LATENCY_MS = {
    MethodTier.CACHE: 1.0,
    MethodTier.DETERMINISTIC: 2.0,
    MethodTier.SMALL_CLASSIFIER: 20.0,
}
RAG_CONTEXT_TOKENS = 1000     # PLACEHOLDER: retrieved context added to the input
RAG_RETRIEVAL_MS = 30.0       # PLACEHOLDER

# The runtime's own overhead per stage (PLACEHOLDER), so breakeven can net it out.
RUNTIME_STAGE_MS = {
    "stage0_screen": 0.5,
    "stage1_policy": 1.0,
    "stage2_session": 0.5,
    "stage3_router": NON_LLM_LATENCY_MS[MethodTier.SMALL_CLASSIFIER],
    "stage4_feedforward": 0.2,
    "stage6_non_llm_checks": 2.0,
}

# Expected output tokens by request type (PLACEHOLDER). Output length is the biggest energy
# driver and unknown before execution; UNKNOWN is deliberately the largest.
DEFAULT_OUTPUT_TOKENS = {
    RequestType.CLASSIFICATION: 20,
    RequestType.COMPUTATION: 100,
    RequestType.LOOKUP: 150,
    RequestType.JUDGMENT: 400,
    RequestType.GENERATION: 500,
    RequestType.HIGH_STAKES: 500,
    RequestType.UNKNOWN: 500,
}

MAX_OUTPUT_TOKENS = 10_000_000   # sanity cap: beyond this the request is a caller bug, not a workload

_LLM_TIERS = {MethodTier.RAG_SMALL_MODEL, MethodTier.LLM_LOW_REASONING, MethodTier.LLM_HIGH_REASONING}
LLM_TIERS = frozenset(_LLM_TIERS)   # public: the tiers that take a `model` argument


def _cpu_wh(ms: float) -> float:
    return CPU_POWER_W * ms / 3_600_000   # W * ms -> mJ -> Wh


@dataclass(frozen=True)
class CostEstimate:
    """Richer than TierCostEstimate: adds the +/-1 std range and range-status flag.

    range_status: "in_range" | "below_range" | "above_range" | "n/a" (non-LLM tier).
    Consumers making savings claims must exclude or separately report anything that
    is not "in_range".
    """
    tier_estimate: TierCostEstimate     # est_energy_wh is the central value
    wh_low: float
    wh_high: float
    input_tokens: int
    output_tokens: int
    range_status: str
    notes: tuple[str, ...] = ()


def _energy_range(anchors: tuple[EnergyAnchor, ...], total: int) -> tuple[float, float, float, float, str]:
    """Return (low0, central, high0, std, status) before the +/- std widening."""
    first, last = anchors[0], anchors[-1]
    if total < first.total_tokens:
        # Fixed per-request costs mean energy does not fall to zero, so the measured floor is
        # the upper bound; assuming pure proportionality is the lower bound.
        low0, high0 = first.wh * total / first.total_tokens, first.wh
        return low0, (low0 + high0) / 2, high0, first.wh_std, "below_range"
    if total > last.total_tokens:
        prev = anchors[-2]
        slope = max(0.0, (last.wh - prev.wh) / (last.total_tokens - prev.total_tokens))
        high0 = max(last.wh, last.wh * total / last.total_tokens)      # proportional scaling
        central = min(last.wh + slope * (total - last.total_tokens), high0)
        return last.wh, central, high0, last.wh_std, "above_range"
    for a, b in zip(anchors, anchors[1:]):
        if a.total_tokens <= total <= b.total_tokens:
            f = (total - a.total_tokens) / (b.total_tokens - a.total_tokens)
            wh = a.wh + f * (b.wh - a.wh)
            std = a.wh_std + f * (b.wh_std - a.wh_std)
            return wh, wh, wh, std, "in_range"
    raise AssertionError("unreachable: anchors are sorted and cover the total")


def _resolve_output_tokens(request_type: RequestType, explicit: Optional[int]) -> int:
    if explicit is None:
        return DEFAULT_OUTPUT_TOKENS.get(request_type, DEFAULT_OUTPUT_TOKENS[RequestType.UNKNOWN])
    if isinstance(explicit, bool) or not isinstance(explicit, numbers.Integral) or explicit < 0:
        raise ValueError(f"expected_output_tokens must be a non-negative int, got {explicit!r}")
    if explicit > MAX_OUTPUT_TOKENS:
        raise ValueError(f"expected_output_tokens {explicit} exceeds the sanity cap {MAX_OUTPUT_TOKENS}")
    return int(explicit)


def estimate_tier(
    tier: MethodTier,
    request_text: str,
    model: Optional[ModelInfo] = None,
    request_type: RequestType = RequestType.UNKNOWN,
    expected_output_tokens: Optional[int] = None,
) -> CostEstimate:
    if not isinstance(tier, MethodTier):
        raise ValueError(f"tier must be a MethodTier, got {tier!r}")
    in_tokens = estimate_tokens(request_text)

    if tier not in _LLM_TIERS:
        ms = NON_LLM_LATENCY_MS[tier]
        wh = _cpu_wh(ms)
        return CostEstimate(
            TierCostEstimate(tier, None, 0.0, ms, wh), wh, wh, in_tokens, 0, "n/a",
            ("placeholder: CPU time x assumed power, unmeasured",))

    if model is None:
        raise ValueError(f"{tier.value} requires a model")
    if not isinstance(model, ModelInfo):
        raise TypeError(f"model must be a ModelInfo, got {type(model).__name__}")
    out_tokens = _resolve_output_tokens(request_type, expected_output_tokens)
    notes: list[str] = []
    latency = model.typical_latency_ms
    if tier is MethodTier.RAG_SMALL_MODEL:
        in_tokens += RAG_CONTEXT_TOKENS
        notes.append("placeholder: RAG context tokens and retrieval overhead assumed")
    total = in_tokens + out_tokens

    low0, central, high0, std, status = _energy_range(model.energy_anchors, total)
    mult = _REASONING_MULTIPLIER.get(tier, 1.0)
    if tier is MethodTier.LLM_HIGH_REASONING:
        notes.append("reasoning multiplier borrowed from the GPT-5 case study (17.15/2.33 Wh)")
    if status != "in_range":
        notes.append(f"total {total} tokens is {status.replace('_', ' ')} of the measured "
                     f"anchors; range widened, exclude from headline savings")

    wh_low = max(0.0, low0 - std) * mult
    wh_high = (high0 + std) * mult
    wh = central * mult
    dollars = model.cost_per_1k_tokens * total / 1000 * mult
    latency = latency * mult
    if tier is MethodTier.RAG_SMALL_MODEL:
        latency += RAG_RETRIEVAL_MS
        extra = _cpu_wh(RAG_RETRIEVAL_MS)
        wh, wh_low, wh_high = wh + extra, wh_low + extra, wh_high + extra

    return CostEstimate(TierCostEstimate(tier, model.name, dollars, latency, wh),
                        wh_low, wh_high, in_tokens, out_tokens, status, tuple(notes))


def runtime_overhead_wh(stages: Iterable[str]) -> float:
    """Energy spent by the runtime's own stages (PLACEHOLDER figures)."""
    if isinstance(stages, str):
        raise TypeError("stages must be an iterable of stage names, not a single string")
    total_ms = 0.0
    for s in stages:
        if s not in RUNTIME_STAGE_MS:
            raise ValueError(f"unknown runtime stage {s!r}")
        total_ms += RUNTIME_STAGE_MS[s]
    return _cpu_wh(total_ms)
