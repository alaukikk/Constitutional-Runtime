
"""
validation/validator.py — Stage 6 Output Validator.

Input: raw response text, original request, selected tier, the request's
policy flags. Output: ValidationResult (pass/fail, reason for the repair
router on failure, which check type was used).

AI permitted: no, this sprint. Only validation/non_llm_checks.py runs. If an
LLM-based check is ever added it must be costed/audited like any other model
call (ARCHITECTURE.md Stage 6 #5); `check_type` exists so the audit record can
say which kind ran.

Two different failures, kept separate on purpose:

1. A CHECK FAILS (the output is empty, leaks a credential, ...). That is a
   normal validation failure: passed=False, reason goes to
   escalation/repair_router.py. It is never "failed open".

2. THE VALIDATOR ITSELF ERRORS. Failure behavior follows failure_modes.yaml
   (ARCHITECTURE.md Stage 6 #7). Resolved as OI-046 option (a): "high-stakes"
   is determined ONLY from the request's policy flags: if any triggered rule's
   failure mode is fail_closed (unknown rule ids default to fail_closed, per
   the yaml default), the validator fails closed. The classifier's
   HIGH_STAKES category is deliberately NOT consulted, so the classifier never
   becomes a second safety-policy authority. With no fail_closed flag, the
   validator fails open and logs it loudly.

   Consequence worth knowing: a request that triggered no policy rule at all
   is treated as low-stakes here, so a validator error on it releases the
   output unvalidated (logged, and marked failed_open=True for the audit
   record).

`confidence` is Optional and None until a calibrated meaning exists. A fixed
number for "all non-LLM checks passed" would imply a reliability nobody has
measured; user-facing wording stays "passed automated checks", never
"verified".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from policy.schemas import MethodTier, PolicyFlag
from validation.non_llm_checks import CheckResult, run_non_llm_checks

logger = logging.getLogger("validation.validator")

CHECK_TYPE_NON_LLM = "non_llm"


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reason: str                              # "" on a clean pass; otherwise what failed
    check_type: str = CHECK_TYPE_NON_LLM     # audit: which kind of check ran (Stage 6 #9)
    checks: tuple[CheckResult, ...] = ()
    validator_errored: bool = False          # the validator itself raised
    failed_open: bool = False                # errored AND released anyway (low-stakes)
    confidence: Optional[float] = None       # intentionally uncalibrated, see module docstring


def _default_fail_closed_for(rule_id: str) -> bool:
    # Reuse the policy engine's already-loaded failure_modes.yaml semantics
    # (per-rule value, falling back to the yaml default). Private accessor on
    # purpose: one source of truth for failure behavior, not a second parser.
    from policy.engine import get_policy_engine
    return get_policy_engine()._fail_closed_for(rule_id)


def _is_high_stakes(flags: Sequence[PolicyFlag],
                    fail_closed_for: Callable[[str], bool]) -> bool:
    return any(fail_closed_for(f.rule_id) for f in flags)


def validate_output(
    request_text: str,
    output_text: Optional[str],
    tier: MethodTier,
    policy_flags: Sequence[PolicyFlag] = (),
    *,
    fail_closed_for: Optional[Callable[[str], bool]] = None,
) -> ValidationResult:
    """Validate a response before release. Never raises."""
    resolver = fail_closed_for or _default_fail_closed_for
    try:
        results = tuple(run_non_llm_checks(output_text))
        failed = [r for r in results if not r.passed]
        if failed:
            reason = "; ".join(f"{r.name}: {r.reason}" for r in failed)
            return ValidationResult(False, reason, CHECK_TYPE_NON_LLM, results)
        return ValidationResult(True, "", CHECK_TYPE_NON_LLM, results)
    except Exception as exc:  # validator-level error, see module docstring
        try:
            high_stakes = _is_high_stakes(policy_flags, resolver)
        except Exception:
            high_stakes = True  # cannot even decide stakes -> fail closed
        if high_stakes:
            logger.warning("validator errored (%s) on tier %s; fail-closed, output withheld",
                           exc, getattr(tier, "value", tier))
            return ValidationResult(False, "validator_error_failed_closed",
                                    CHECK_TYPE_NON_LLM, (), validator_errored=True)
        logger.warning("validator errored (%s) on tier %s; no fail-closed policy flag, "
                       "FAILING OPEN: output released unvalidated",
                       exc, getattr(tier, "value", tier))
        return ValidationResult(True, "validator_error_failed_open", CHECK_TYPE_NON_LLM, (),
                                validator_errored=True, failed_open=True)
