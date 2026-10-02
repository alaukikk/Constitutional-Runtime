
"""
audit/metrics.py -- offline evaluation metrics for the cheap tiers.

Answers the capstone's two-sided question for a tier that can abstain:
  (1) can the cheaper mechanism answer ADEQUATELY?  -> accuracy, precision,
      recall, incorrect-answer rate, abstention/escalation rate;
  (2) did using it avoid resource spend?             -> latency, CPU time, and an
      ESTIMATED energy figure.

Basis:
  [RESEARCH] "From Prompts to Power", Section VI (page 11 of the supplied file):
             judge quality and energy together, not accuracy alone. "Energy
             Considerations of LLM Inference and Efficiency Optimizations", page 1
             (abstract/introduction): idealized settings miss real-world
             workloads, so real workloads should be measured.
  [PROJECT]  docs/RESEARCH_TRACEABILITY.md evaluation framework (resource
             efficiency, decision quality, runtime overhead) and
             README: audit/metrics.py "tracks numbers over time".
  [JUDGMENT] The exact metric definitions below.

!! `estimated_cpu_wh` IS AN ESTIMATE, NOT A MEASUREMENT. It is process CPU time
multiplied by cost.estimator.CPU_POWER_W, itself an unmeasured PLACEHOLDER (see
OI-005). The final experiment must measure actual resource consumption on the
target hardware; do not report this figure as empirical energy savings.

Metric definitions (n = number of examples):
  coverage / abstention_rate   answered/n and abstained/n. Here abstaining means
                               returning None, i.e. the ladder escalates, so
                               escalation_rate is the same number.
  accuracy_on_answered         correct / answered (None if nothing was answered).
  incorrect_answer_rate        wrong / n. The costly failure: a wrong answer
                               delivered instead of an escalation.
  precision (per class)        TP / answers predicted as that class.
  recall (per class)           TP / examples of that class. An abstention counts
                               as NOT recalled (conservative).

Also here, to protect the experiment's integrity:
  assert_no_overlap(...)   fail if any evaluation text also appears in the
                           training data (after whitespace/case normalization).
  dataset_fingerprint(...) order-insensitive SHA-256 of a labeled set, to be
                           recorded when an evaluation set is frozen, BEFORE any
                           threshold is tuned.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence


@dataclass(frozen=True)
class ClassMetrics:
    support: int
    predicted: int
    true_positive: int
    precision: Optional[float]
    recall: float


@dataclass(frozen=True)
class AbstentionReport:
    n: int
    answered: int
    abstained: int
    correct: int
    incorrect: int
    coverage: float
    abstention_rate: float
    accuracy_on_answered: Optional[float]
    incorrect_answer_rate: float
    per_class: dict
    mean_latency_ms: float
    p95_latency_ms: float
    total_cpu_ms: float
    estimated_cpu_wh: float          # ESTIMATE from a placeholder power figure

    @property
    def escalation_rate(self) -> float:
        return self.abstention_rate


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _validate_labeled(examples: Iterable) -> list[tuple[str, str]]:
    out = []
    for item in examples:
        if (not isinstance(item, (tuple, list)) or len(item) != 2
                or not isinstance(item[0], str) or not isinstance(item[1], str) or not item[1]):
            raise TypeError("examples must be (text, label) pairs of strings with a non-empty label")
        out.append((item[0], item[1]))
    if not out:
        raise ValueError("no examples")
    return out


def evaluate_abstaining_classifier(
    classify_fn: Callable[[str], Optional[str]],
    examples: Iterable[tuple[str, str]],
    *,
    cpu_power_w: Optional[float] = None,
) -> AbstentionReport:
    if not callable(classify_fn):
        raise TypeError("classify_fn must be callable")
    pairs = _validate_labeled(examples)
    if cpu_power_w is None:
        from cost.estimator import CPU_POWER_W      # placeholder, see module docstring
        cpu_power_w = CPU_POWER_W
    if isinstance(cpu_power_w, bool) or not isinstance(cpu_power_w, (int, float)) \
            or not math.isfinite(cpu_power_w) or cpu_power_w < 0:
        raise ValueError("cpu_power_w must be a finite number >= 0")

    latencies_ms: list[float] = []
    predictions: list[Optional[str]] = []
    cpu_start = time.process_time()
    for text, _ in pairs:
        t0 = time.perf_counter()
        pred = classify_fn(text)
        latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        if pred is not None and not isinstance(pred, str):
            raise TypeError("classify_fn must return str or None")
        predictions.append(pred)
    total_cpu_ms = (time.process_time() - cpu_start) * 1000.0

    n = len(pairs)
    answered = sum(p is not None for p in predictions)
    correct = sum(p is not None and p == gold for p, (_, gold) in zip(predictions, pairs))
    incorrect = answered - correct

    per_class = {}
    for label in sorted({gold for _, gold in pairs} | {p for p in predictions if p is not None}):
        support = sum(gold == label for _, gold in pairs)
        predicted = sum(p == label for p in predictions)
        tp = sum(p == label and gold == label for p, (_, gold) in zip(predictions, pairs))
        per_class[label] = ClassMetrics(support, predicted, tp,
                                        tp / predicted if predicted else None,
                                        tp / support if support else 0.0)

    ordered = sorted(latencies_ms)
    p95 = ordered[max(0, math.ceil(0.95 * n) - 1)]
    return AbstentionReport(
        n=n, answered=answered, abstained=n - answered, correct=correct, incorrect=incorrect,
        coverage=answered / n, abstention_rate=(n - answered) / n,
        accuracy_on_answered=(correct / answered) if answered else None,
        incorrect_answer_rate=incorrect / n, per_class=per_class,
        mean_latency_ms=sum(latencies_ms) / n, p95_latency_ms=p95,
        total_cpu_ms=total_cpu_ms,
        estimated_cpu_wh=cpu_power_w * total_cpu_ms / 3_600_000.0,
    )


@dataclass(frozen=True)
class RetrievalReport:
    n_answerable: int
    n_unanswerable: int
    hit_rate_at_k: Optional[float]          # answerable queries with the right source in top-k
    mrr: Optional[float]                    # mean reciprocal rank of the right source
    correct_abstention_rate: Optional[float]  # unanswerable queries that returned nothing
    false_answer_rate: Optional[float]      # unanswerable queries that returned something
    mean_latency_ms: float


def evaluate_retrieval(
    search_fn: Callable[[str, int], Sequence],
    cases: Iterable[tuple[str, Optional[str]]],
    k: int = 3,
) -> RetrievalReport:
    """cases: (query, expected_source). expected_source None means the corpus has
    no answer, so the correct behavior is to return nothing. Relevance is judged
    at SOURCE-FILE level only (passage-level labels would be needed for finer
    claims)."""
    if not callable(search_fn):
        raise TypeError("search_fn must be callable")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be an int >= 1")
    items = list(cases)
    if not items:
        raise ValueError("no cases")
    hits_at_k, reciprocal, abstained_ok, answered_wrong, latencies = [], [], [], [], []
    for query, expected in items:
        t0 = time.perf_counter()
        hits = list(search_fn(query, k))
        latencies.append((time.perf_counter() - t0) * 1000.0)
        sources = [h.passage.source for h in hits]
        if expected is None:
            (abstained_ok if not sources else answered_wrong).append(1)
        else:
            rank = next((i + 1 for i, s in enumerate(sources) if s == expected), None)
            hits_at_k.append(1 if rank else 0)
            reciprocal.append(1.0 / rank if rank else 0.0)
    n_ans = len(hits_at_k)
    n_un = len(abstained_ok) + len(answered_wrong)
    return RetrievalReport(
        n_answerable=n_ans, n_unanswerable=n_un,
        hit_rate_at_k=sum(hits_at_k) / n_ans if n_ans else None,
        mrr=sum(reciprocal) / n_ans if n_ans else None,
        correct_abstention_rate=len(abstained_ok) / n_un if n_un else None,
        false_answer_rate=len(answered_wrong) / n_un if n_un else None,
        mean_latency_ms=sum(latencies) / len(items),
    )


def assert_no_overlap(training_texts: Iterable[str], eval_examples: Iterable[tuple[str, str]]) -> None:
    """Raise ValueError if any evaluation text also appears in the training data."""
    train = {_normalize(t) for t in training_texts}
    leaked = [t for t, _ in _validate_labeled(eval_examples) if _normalize(t) in train]
    if leaked:
        raise ValueError(f"{len(leaked)} evaluation example(s) also appear in the training data")


def dataset_fingerprint(examples: Iterable[tuple[str, str]]) -> str:
    """Order-insensitive SHA-256 of a labeled set. Record it when the set is frozen."""
    rows = sorted([_normalize(t), label] for t, label in _validate_labeled(examples))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()
