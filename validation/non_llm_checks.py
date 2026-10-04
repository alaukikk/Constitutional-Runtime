
"""
validation/non_llm_checks.py — Stage 6 cheap, rule-based output checks.

ARCHITECTURE.md Stage 6 #4: prefer non-LLM checks wherever they suffice.
No AI is used here, so these checks need no cost accounting beyond the
runtime-overhead line (cost/estimator.py "stage6_non_llm_checks").

Scope is deliberately narrow and honest: these checks catch *structural and
leakage* problems (empty output, runaway length, control characters, leaked
credentials / jailbreak acknowledgements). A pass means "passed automated
checks", NOT "correct" and NOT "verified". Correctness checks (retrieval-
grounded fact-check, re-computation of deterministic answers) are later work.

Output-side policy: per the Sprint 5 decision, guardrails/output_filter.py is
the ONLY output-side policy check this sprint. constitution.yaml rules are
request rules and are intentionally NOT applied to generated output here.

Failure behavior of an individual check: an exception inside a check is
reported as a FAILED check with reason "check_internal_error" (fail closed at
the check level, same philosophy as Stage 0 / output_filter). Whether the
*validator as a whole* then fails open or closed is decided in validator.py,
from policy flags, not here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from guardrails.output_filter import check_output

# Upper bound on a single response, in characters. PLACEHOLDER: a sanity cap
# against runaway output (OWASP "Unbounded Consumption"), not a calibrated
# limit. Calibrate with real usage data (cost/calibration) before relying on it.
MAX_OUTPUT_CHARS = 50_000

# Control characters other than tab / newline / carriage return.
_BAD_CONTROL = {chr(c) for c in range(32)} - {"\t", "\n", "\r"}
_BAD_CONTROL.add("\x7f")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    reason: str = ""


def _non_empty(output: Optional[str]) -> CheckResult:
    if output is None or not isinstance(output, str) or not output.strip():
        return CheckResult("non_empty", False, "empty_output")
    return CheckResult("non_empty", True)


def _within_length(output: Optional[str]) -> CheckResult:
    if isinstance(output, str) and len(output) > MAX_OUTPUT_CHARS:
        return CheckResult("within_length", False,
                           f"output_length_{len(output)}_exceeds_{MAX_OUTPUT_CHARS}")
    return CheckResult("within_length", True)


def _no_control_chars(output: Optional[str]) -> CheckResult:
    if isinstance(output, str) and any(ch in _BAD_CONTROL for ch in output):
        return CheckResult("no_control_chars", False, "control_characters_present")
    return CheckResult("no_control_chars", True)


def _no_safety_leakage(output: Optional[str]) -> CheckResult:
    res = check_output(output)  # already fails closed on its own errors
    if res.passed:
        return CheckResult("no_safety_leakage", True)
    return CheckResult("no_safety_leakage", False, ",".join(res.reasons))


# Order matters only for reporting; all checks always run so the audit record
# shows every failure, not just the first.
_CHECKS: tuple[tuple[str, Callable[[Optional[str]], CheckResult]], ...] = (
    ("non_empty", _non_empty),
    ("within_length", _within_length),
    ("no_control_chars", _no_control_chars),
    ("no_safety_leakage", _no_safety_leakage),
)


def run_non_llm_checks(output: Optional[str]) -> list[CheckResult]:
    """Run every check. Never raises: a crashing check becomes a failed check."""
    results: list[CheckResult] = []
    for name, fn in _CHECKS:
        try:
            results.append(fn(output))
        except Exception:
            results.append(CheckResult(name, False, "check_internal_error"))
    return results
