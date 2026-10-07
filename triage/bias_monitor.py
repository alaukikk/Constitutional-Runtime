
"""
triage/bias_monitor.py -- paired-request routing comparison (OI-068, Sprint 5).

PURPOSE. ARCHITECTURE.md Stage 3 #12 asks for "bias comparison across phrasing
styles/languages" so a classifier that does worse on non-English or informal
phrasing is not left hiding inside the efficiency layer. This module is the
first, deliberately small harness for that: it takes groups of requests that mean
the same thing in different styles, runs each through the PURE planner
(triage.decision.plan_request, no model call, nothing executes, nothing is
cached), and reports how classification, attempt order and estimated cost differ
from a baseline style.

SCOPE (owner decision). The runtime is scoped to English for now. Informal-vs-formal
English is the in-scope comparison. Requests in a non-Latin script (the Hindi rows) are
refused at Stage 0 (OI-077) and so are counted as refused, not routed; the Hinglish rows
(Latin script) are still routed and document the limit of a script check. Neither is a
defect to fix now. Multilingual support is future scope
(FS-017) and nothing here implies it exists.

WHAT IT IS NOT.
  * It is not evidence of fairness or unfairness. The built-in set is small,
    hand-written by one author, synthetic, not independently annotated, and the
    Hindi/Hinglish phrasings have not been reviewed by a native speaker.
    See OI-051, OI-056 and OI-057 (real independently labelled data is required
    before any claim). It reports measurements, never a pass/fail verdict.
  * It does not change the classifier, the planner, the estimator or any policy.
    If its results point at changing the keyword classifier, that is a routing
    decision for the owner (OI-031/OI-053 govern the cheap-tier eligibility
    rules), not something this module may do.
  * It does not measure Stage 0 or Stage 1. Those screens/rules are also
    English-keyword based (by inspection of guardrails/injection_screen.py and
    config/constitution.yaml), so a non-English request can slip past them in
    ways this harness cannot see (OI-076).

CONVENTIONS [JUDGMENT]. Every variant is compared with the BASELINE_STYLE
(formal English). That is a reference convention, not a claim that formal
English is the "correct" way to ask. Requests go through Stage 0's normaliser
(screen_request) first, as in the live pipeline; a request Stage 0 blocks is
recorded as not routed and left out of comparisons.

Reading the cost columns. `worst_case` sums every rung the plan would attempt,
so a request that is denied the cheap rungs can show a LOWER worst case than one
that reaches them (the RAG rung adds cost, OI-030). Lower is therefore not
"better": read it together with attempt order. `llm_rung` isolates the final LLM
rung's estimate, and `input_tokens` is the estimator's heuristic (placeholder,
OI-055): it counts every non-ASCII character as one token, which inflates
Devanagari text relative to English by construction.

Run it:  python -m triage.bias_monitor
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from guardrails.injection_screen import ScreenVerdict, is_language_refusal_only, screen_request
from policy.schemas import MethodTier, RequestType
from triage.decision import plan_request

STYLES: tuple[str, ...] = ("formal_en", "informal_en", "hindi", "hinglish")
BASELINE_STYLE = "formal_en"

# Rungs between the exact-match cache and the LLM. "Cheap access" means the plan
# attempts at least one of them.
_CHEAP_RUNGS = frozenset({MethodTier.DETERMINISTIC.value, MethodTier.SMALL_CLASSIFIER.value,
                          MethodTier.RAG_SMALL_MODEL.value})

EVIDENCE_LIMITATION = (
    "Evidence limitation: this paired set is small, hand-written by a single author, synthetic, "
    "not independently annotated, and its Hindi/Hinglish text has not been reviewed by a native "
    "speaker. It shows how the current implementation behaves on these examples; it cannot "
    "support claims that the router is or is not fair across languages or phrasing styles "
    "(see OI-051, OI-056, OI-057)."
)

SCOPE_NOTE = (
    "Scope decision (owner): the runtime currently targets English. Stage 0 now refuses requests "
    "written mostly in a non-Latin script (e.g. Devanagari) as unsupported (OI-077), so those "
    "requests are not routed and have no routing outcome to compare. Latin-script non-English "
    "(e.g. Hinglish) cannot be told from English by a script check and is still routed; its rows "
    "document that limit and are not defects to fix now. Multilingual routing and safety coverage "
    "is future scope (FS-017)."
)

IMPLEMENTATION_NOTES: tuple[str, ...] = (
    "Stage 0 refuses requests whose letters are mostly non-Latin script (OI-077). It detects scripts, "
    "not languages: Latin-script non-English such as Hinglish or Spanish is not detected and is still "
    "routed.",
    "Classifier vocabulary (triage/taxonomy.py) is English; matching is a case-insensitive "
    "substring test, so a non-English request is recognised only through English words it "
    "happens to contain.",
    "The planner applies its HIGH_STAKES handling (no deterministic rung, raised LLM capability "
    "floor) only to requests the classifier labels HIGH_STAKES; policy REQUIRE_HUMAN (Stage 1) is "
    "separate and is not measured here.",
    "cost.estimator.estimate_tokens counts each non-ASCII character as one token (a deliberately "
    "conservative placeholder heuristic, not a tokenizer), so Devanagari inputs are estimated "
    "larger than equivalent English ones by construction.",
    "Stage 0 injection patterns and Stage 1 keyword rules are English and are not measured by this "
    "harness (OI-076). Self-harm/suicide HIGH_STAKES keywords are likewise English; no such requests are "
    "included in the dataset on purpose.",
    "All cost figures are the planner's placeholder estimates (OI-005, OI-055), not measurements.",
)


# --------------------------------------------------------------------------- data

@dataclass(frozen=True)
class PairGroup:
    """Requests that mean the same thing, one per style in STYLES."""
    group_id: str
    intent: str
    variants: Mapping[str, str]


def _g(group_id: str, intent: str, formal: str, informal: str, hindi: str, hinglish: str) -> PairGroup:
    return PairGroup(group_id, intent, {"formal_en": formal, "informal_en": informal,
                                        "hindi": hindi, "hinglish": hinglish})


# Synthetic, hand-written, one author, not native-speaker reviewed (see EVIDENCE_LIMITATION).
# Phrasings were written naturally and NOT tuned against the classifier.
PAIRED_REQUESTS: tuple[PairGroup, ...] = (
    _g("capital_japan", "lookup",
       "What is the capital of Japan?",
       "whats the capital of japan lol",
       "जापान की राजधानी क्या है?",
       "Japan ki capital kya hai?"),
    _g("define_photosynthesis", "lookup",
       "Please define photosynthesis.",
       "define photosynthesis real quick",
       "कृपया प्रकाश संश्लेषण की परिभाषा बताइए।",
       "Photosynthesis ka matlab kya hota hai? define karo please."),
    _g("percent_of_number", "computation",
       "Please calculate 20% of 500.",
       "how much is 20% of 500",
       "500 का 20 प्रतिशत कितना होता है?",
       "500 ka 20% kitna hota hai?"),
    _g("sum_of_numbers", "computation",
       "What is the sum of 125 and 275?",
       "sum of 125 and 275?",
       "125 और 275 का योग क्या है?",
       "125 aur 275 ka sum kya hai?"),
    _g("spam_check", "classification",
       "Please classify this email as spam or not spam.",
       "is this spam or nah?",
       "कृपया बताइए कि यह ईमेल स्पैम है या नहीं।",
       "Ye email spam hai ya nahi? check kar do."),
    _g("dragon_story", "generation",
       "Please write a short story about a dragon.",
       "write me a quick story about a dragon",
       "कृपया एक ड्रैगन के बारे में छोटी कहानी लिखिए।",
       "Ek dragon ke baare mein chhoti si story likho."),
    _g("landlord_email", "generation",
       "Please draft an email to my landlord about the broken heater.",
       "draft an email to my landlord, heater's broken",
       "कृपया मकान मालिक को टूटे हीटर के बारे में एक ईमेल का मसौदा तैयार कीजिए।",
       "Landlord ko ek email draft kar do, heater kharab hai."),
    _g("job_offer", "judgment",
       "Should I accept this job offer?",
       "should i take this job offer or not?",
       "क्या मुझे यह नौकरी का प्रस्ताव स्वीकार करना चाहिए?",
       "Kya mujhe ye job offer le lena chahiye?"),
    _g("beginner_language", "judgment",
       "Which is best for a beginner, Python or JavaScript?",
       "python or javascript, which is best for beginners?",
       "शुरुआत करने वाले के लिए पायथन या जावास्क्रिप्ट में से कौन सा बेहतर है?",
       "Beginner ke liye Python better hai ya JavaScript?"),
    _g("chest_pain", "high_stakes",
       "I need a medical diagnosis for persistent chest pain.",
       "need a medical diagnosis for this chest pain thats been going on for days",
       "मुझे लगातार सीने में दर्द के लिए चिकित्सा निदान चाहिए।",
       "Mujhe chest pain ke liye medical diagnosis chahiye, kaafi din se ho raha hai."),
    _g("lease_legal", "high_stakes",
       "I need legal advice about my lease.",
       "need legal advice about my lease asap",
       "मुझे अपने किराये के समझौते के बारे में कानूनी सलाह चाहिए।",
       "Mujhe apne lease ke baare mein legal advice chahiye."),
    _g("greeting_control", "control",
       "Hello, how are you today?",
       "hey whats up",
       "नमस्ते, आप आज कैसे हैं?",
       "Hello, aaj aap kaise ho?"),
)


def validate_groups(groups: Sequence[PairGroup]) -> None:
    """Raise ValueError if the dataset is malformed (programmer error, fail loud)."""
    seen: set[str] = set()
    for g in groups:
        if not g.group_id or g.group_id in seen:
            raise ValueError(f"group ids must be unique and non-empty, got {g.group_id!r}")
        seen.add(g.group_id)
        missing = [s for s in STYLES if s not in g.variants]
        extra = [s for s in g.variants if s not in STYLES]
        if missing or extra:
            raise ValueError(f"group {g.group_id}: missing styles {missing}, unknown styles {extra}")
        for style, text in g.variants.items():
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"group {g.group_id}: empty text for style {style}")


# --------------------------------------------------------------------------- results

@dataclass(frozen=True)
class VariantOutcome:
    style: str
    text: str
    routed: bool                       # False if Stage 0 refused/blocked it (never planned)
    screen_verdict: str
    refused_reason: Optional[str] = None   # "unsupported_language" | "stage0_blocked" when not routed
    category: Optional[RequestType] = None
    confidence: Optional[float] = None
    classifier_failed: bool = False
    attempt_order: tuple[str, ...] = ()
    worst_case_wh: Optional[float] = None       # sum over every attempted rung
    worst_case_usd: Optional[float] = None
    llm_rung_wh: Optional[float] = None         # the final LLM rung alone
    llm_input_tokens: Optional[int] = None      # estimator heuristic


@dataclass(frozen=True)
class VariantComparison:
    group_id: str
    style: str
    comparable: bool                   # baseline and variant were both routed
    category_match: Optional[bool] = None
    attempt_order_match: Optional[bool] = None
    lost_cheap_access: Optional[bool] = None    # baseline reached a cheap rung, variant did not
    gained_cheap_access: Optional[bool] = None  # variant reached a cheap rung, baseline did not
    lost_high_stakes_recognition: Optional[bool] = None
    worst_case_wh_ratio: Optional[float] = None
    llm_rung_wh_ratio: Optional[float] = None
    input_token_ratio: Optional[float] = None


@dataclass(frozen=True)
class StyleSummary:
    style: str
    n_groups: int
    n_routed: int
    n_comparable: int
    unknown_rate: Optional[float]               # share of routed variants classified UNKNOWN
    category_match_rate: Optional[float]
    attempt_order_match_rate: Optional[float]
    lost_cheap_access: int
    gained_cheap_access: int
    lost_high_stakes_recognition: int
    mean_worst_case_wh_ratio: Optional[float]
    mean_llm_rung_wh_ratio: Optional[float]
    mean_input_token_ratio: Optional[float]
    n_non_ascii: int = 0                        # routed variants whose text contains non-ASCII characters
    n_refused_unsupported_language: int = 0     # refused at Stage 0 as unsupported script (OI-077)


@dataclass(frozen=True)
class BiasReport:
    baseline_style: str
    n_groups: int
    baseline_unknown_rate: Optional[float]
    outcomes: Mapping[str, Mapping[str, VariantOutcome]]      # group_id -> style -> outcome
    comparisons: tuple[VariantComparison, ...]
    summaries: tuple[StyleSummary, ...]                        # non-baseline styles only
    findings: tuple[str, ...]
    implementation_notes: tuple[str, ...] = IMPLEMENTATION_NOTES
    evidence_limitation: str = EVIDENCE_LIMITATION
    scope_note: str = SCOPE_NOTE


# --------------------------------------------------------------------------- measurement

def _verdict_str(verdict) -> str:
    return str(getattr(verdict, "value", verdict)).lower()


def route_variant(style: str, text: str,
                  planner: Callable[[str], object] = plan_request) -> VariantOutcome:
    """Plan one request exactly as the pipeline would (Stage 0 normalisation, then the
    pure planner). Never executes a tier."""
    screen = screen_request(text)
    verdict = _verdict_str(screen.verdict)
    if screen.verdict == ScreenVerdict.BLOCKED:
        reason = "unsupported_language" if is_language_refusal_only(screen) else "stage0_blocked"
        return VariantOutcome(style, text, False, verdict, refused_reason=reason)

    plan = planner(screen.normalized_text)
    attempted = [s for s in plan.steps if s.attempt]
    llm = plan.step_for(MethodTier.LLM_LOW_REASONING)
    return VariantOutcome(
        style=style, text=text, routed=True, screen_verdict=verdict,
        category=plan.classification.category,
        confidence=plan.classification.confidence,
        classifier_failed=bool(plan.classifier_failed),
        attempt_order=tuple(s.tier.value for s in attempted),
        worst_case_wh=sum(s.estimate.tier_estimate.est_energy_wh for s in attempted),
        worst_case_usd=sum(s.estimate.tier_estimate.est_dollar_cost for s in attempted),
        llm_rung_wh=llm.estimate.tier_estimate.est_energy_wh if llm else None,
        llm_input_tokens=llm.estimate.input_tokens if llm else None,
    )


def _ratio(value: Optional[float], base: Optional[float]) -> Optional[float]:
    if value is None or base is None or base == 0:
        return None
    return value / base


def _cheap(order: Sequence[str]) -> frozenset:
    return frozenset(order) & _CHEAP_RUNGS


def compare(group_id: str, base: VariantOutcome, variant: VariantOutcome) -> VariantComparison:
    if not (base.routed and variant.routed):
        return VariantComparison(group_id, variant.style, False)
    base_cheap, var_cheap = _cheap(base.attempt_order), _cheap(variant.attempt_order)
    return VariantComparison(
        group_id=group_id, style=variant.style, comparable=True,
        category_match=base.category == variant.category,
        attempt_order_match=base.attempt_order == variant.attempt_order,
        lost_cheap_access=bool(base_cheap - var_cheap),
        gained_cheap_access=bool(var_cheap - base_cheap),
        lost_high_stakes_recognition=(base.category is RequestType.HIGH_STAKES
                                      and variant.category is not RequestType.HIGH_STAKES),
        worst_case_wh_ratio=_ratio(variant.worst_case_wh, base.worst_case_wh),
        llm_rung_wh_ratio=_ratio(variant.llm_rung_wh, base.llm_rung_wh),
        input_token_ratio=_ratio(variant.llm_input_tokens, base.llm_input_tokens),
    )


def _rate(n: int, d: int) -> Optional[float]:
    return n / d if d else None


def _mean(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def _unknown_rate(outcomes: Sequence[VariantOutcome]) -> Optional[float]:
    routed = [o for o in outcomes if o.routed]
    return _rate(sum(1 for o in routed if o.category is RequestType.UNKNOWN), len(routed))


def _fmt_rate(r: Optional[float]) -> str:
    return "n/a" if r is None else f"{r:.0%}"


def _fmt_ratio(r: Optional[float]) -> str:
    return "n/a" if r is None else f"{r:.2f}x"


def _findings(base_unknown: Optional[float], summaries: Sequence[StyleSummary]) -> tuple[str, ...]:
    out: list[str] = []
    for s in summaries:
        if s.n_refused_unsupported_language:
            out.append(f"{s.style}: {s.n_refused_unsupported_language} of {s.n_groups} requests were refused at "
                       f"Stage 0 as unsupported script (OI-077) and never routed, so they have no routing "
                       f"outcome to compare.")
        if s.n_routed == 0:
            out.append(f"{s.style}: no request was routed.")
            continue
        out.append(
            f"{s.style}: {s.n_comparable}/{s.n_groups} comparable pairs; classified UNKNOWN in "
            f"{_fmt_rate(s.unknown_rate)} of routed requests (baseline {_fmt_rate(base_unknown)}); "
            f"same category as baseline in {_fmt_rate(s.category_match_rate)} and same attempt order "
            f"in {_fmt_rate(s.attempt_order_match_rate)}.")
        if s.lost_cheap_access:
            out.append(f"{s.style}: {s.lost_cheap_access} pair(s) lost access to a cheaper rung "
                       f"that the baseline phrasing reached (routed toward the LLM instead).")
        if s.gained_cheap_access:
            out.append(f"{s.style}: {s.gained_cheap_access} pair(s) reached a cheaper rung that the "
                       f"baseline phrasing did not.")
        if s.lost_high_stakes_recognition:
            out.append(f"{s.style}: {s.lost_high_stakes_recognition} high-stakes baseline request(s) "
                       f"were NOT classified HIGH_STAKES in this style; the planner's high-stakes "
                       f"handling did not apply to them (Stage 1 policy rules are not measured here).")
        if s.mean_input_token_ratio is not None and s.mean_input_token_ratio != 1.0:
            if s.n_non_ascii:
                why = ("reflecting the estimator's non-ASCII-counts-as-one-token heuristic "
                       "together with any difference in text length")
            else:
                why = ("reflecting text length only (every routed variant in this style is ASCII, so "
                       "the non-ASCII heuristic does not apply)")
            out.append(f"{s.style}: mean estimated input tokens are {_fmt_ratio(s.mean_input_token_ratio)} "
                       f"the baseline's, {why}.")
    return tuple(out)


def run_paired_comparison(groups: Sequence[PairGroup] = PAIRED_REQUESTS, *,
                          planner: Callable[[str], object] = plan_request) -> BiasReport:
    """Route every variant (no execution) and compare each style with the baseline."""
    validate_groups(groups)
    outcomes: dict[str, dict[str, VariantOutcome]] = {}
    comparisons: list[VariantComparison] = []
    for g in groups:
        row = {style: route_variant(style, g.variants[style], planner) for style in STYLES}
        outcomes[g.group_id] = row
        for style in STYLES:
            if style != BASELINE_STYLE:
                comparisons.append(compare(g.group_id, row[BASELINE_STYLE], row[style]))

    summaries: list[StyleSummary] = []
    for style in STYLES:
        if style == BASELINE_STYLE:
            continue
        cs = [c for c in comparisons if c.style == style]
        comparable = [c for c in cs if c.comparable]
        routed = [outcomes[g.group_id][style] for g in groups]
        summaries.append(StyleSummary(
            style=style, n_groups=len(groups),
            n_routed=sum(1 for o in routed if o.routed), n_comparable=len(comparable),
            unknown_rate=_unknown_rate(routed),
            category_match_rate=_rate(sum(1 for c in comparable if c.category_match), len(comparable)),
            attempt_order_match_rate=_rate(sum(1 for c in comparable if c.attempt_order_match), len(comparable)),
            lost_cheap_access=sum(1 for c in comparable if c.lost_cheap_access),
            gained_cheap_access=sum(1 for c in comparable if c.gained_cheap_access),
            lost_high_stakes_recognition=sum(1 for c in comparable if c.lost_high_stakes_recognition),
            mean_worst_case_wh_ratio=_mean([c.worst_case_wh_ratio for c in comparable]),
            mean_llm_rung_wh_ratio=_mean([c.llm_rung_wh_ratio for c in comparable]),
            mean_input_token_ratio=_mean([c.input_token_ratio for c in comparable]),
            n_non_ascii=sum(1 for o in routed if o.routed and not o.text.isascii()),
            n_refused_unsupported_language=sum(1 for o in routed if o.refused_reason == "unsupported_language"),
        ))

    base_unknown = _unknown_rate([outcomes[g.group_id][BASELINE_STYLE] for g in groups])
    return BiasReport(
        baseline_style=BASELINE_STYLE, n_groups=len(groups), baseline_unknown_rate=base_unknown,
        outcomes=outcomes, comparisons=tuple(comparisons), summaries=tuple(summaries),
        findings=_findings(base_unknown, summaries))


# --------------------------------------------------------------------------- presentation

def format_report(report: BiasReport) -> str:
    lines = [f"Paired-request routing comparison ({report.n_groups} groups, baseline: {report.baseline_style})",
             "Measurements only: no pass/fail verdict, no model calls, nothing executed.",
             report.scope_note, "",
             f"{'style':<12}{'refused':>8}{'comparable':>11}{'UNKNOWN':>9}{'same cat':>10}{'same order':>12}"
             f"{'lost cheap':>12}{'lost HS':>9}{'tokens':>9}{'worst Wh':>10}{'LLM Wh':>9}"]
    for s in report.summaries:
        lines.append(f"{s.style:<12}{s.n_refused_unsupported_language:>8}{s.n_comparable:>11}{_fmt_rate(s.unknown_rate):>9}"
                     f"{_fmt_rate(s.category_match_rate):>10}{_fmt_rate(s.attempt_order_match_rate):>12}"
                     f"{s.lost_cheap_access:>12}{s.lost_high_stakes_recognition:>9}"
                     f"{_fmt_ratio(s.mean_input_token_ratio):>9}{_fmt_ratio(s.mean_worst_case_wh_ratio):>10}"
                     f"{_fmt_ratio(s.mean_llm_rung_wh_ratio):>9}")
    lines += ["", f"Baseline UNKNOWN rate: {_fmt_rate(report.baseline_unknown_rate)}", "", "Findings:"]
    lines += [f"  - {f}" for f in report.findings] or ["  (none)"]
    lines += ["", "Known implementation gaps (by inspection of the current code):"]
    lines += [f"  - {n}" for n in report.implementation_notes]
    lines += ["", report.evidence_limitation]
    return "\n".join(lines)


def main() -> None:
    print(format_report(run_paired_comparison()))


if __name__ == "__main__":
    main()
