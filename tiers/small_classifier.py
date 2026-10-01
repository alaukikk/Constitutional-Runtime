
"""
tiers/small_classifier.py -- Stage 3/5 small-classifier tier (Sprint 4).

A narrow, cheap, discriminative tier: decides "spam" vs "not spam" for a message
with TF-IDF features and logistic regression, and ABSTAINS (returns None, so the
ladder escalates) whenever it is not confident. Same contract as every other
tier: str answer, or None meaning "I can't handle this reliably".

Basis (every claim tagged; see docs/RESEARCH_TRACEABILITY.md):

  [SPEC]     ARCHITECTURE.md Stage 3 #4 lists a "small classifier" tier; #10 says
             a tier returning None escalates automatically.
  [PROJECT]  docs/TAXONOMY.MD 2.8: "statistical classification (spam, sentiment,
             language ID) -> classical ML model -> tiers/small_classifier.py".
  [RESEARCH] The case for a lightweight discriminative tier rather than a
             generative call for classification: "Energy Considerations of LLM
             Inference and Efficiency Optimizations" -- classification involves
             minimal generation, often a single token (page 3 of the supplied
             file), and decoding dominates workload energy except for tasks with
             short generation such as classification (page 4). "From Prompts to
             Power", Section VI (page 11): task quality and energy should be
             judged together, and some smaller models beat much larger ones at a
             fraction of the energy -- so this tier must be evaluated on both
             adequacy and resource cost (see audit/metrics.py), not accuracy alone.
  [JUDGMENT] The algorithm (TF-IDF + logistic regression), its hyperparameters,
             and every threshold below. The literature supports having a cheap
             tier; it does not mandate this algorithm. Thresholds are
             calibration parameters, NOT validated values (OPEN_ENDS).

What this module deliberately does NOT do:

  * It does not change routing. CLASSIFICATION is not in
    triage.taxonomy.CHEAP_TIER_ELIGIBLE (OI-031, a routing-policy decision for
    the owner), so the planner never attempts this rung for a request the
    classifier labels CLASSIFICATION. extract_message() only accepts phrasings
    that contain a CLASSIFICATION keyword ("is this spam", "classify"), which
    outranks the cheap-eligible categories in CATEGORY_PRIORITY, so this tier is
    unreachable from the live pipeline until OI-031 is decided.
    tests/tiers/test_small_classifier.py guards that invariant: if it fails,
    someone has changed eligibility and the decision must go through OI-031.
  * It is trained on SYNTHETIC data (tiers/spam_seed_synthetic.py). Nothing
    measured on that data is evidence about real traffic.

Safety/robustness:
  * Abstains on empty/oversized input, on messages with too little known
    vocabulary (a zero vector would otherwise yield the class prior, which can
    look confident), and below `abstain_below` probability.
  * Any internal error returns None (escalate), never an exception and never a
    guess. No pickled model is loaded: the model is retrained from the seed in
    memory on first use, so there is no deserialization attack surface.
  * Pure function of its input once trained; no network, no I/O.
"""
from __future__ import annotations

import logging
import math
import numbers
import re
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from tiers.spam_seed_synthetic import LABEL_HAM, LABEL_SPAM, SEED_EXAMPLES

log = logging.getLogger(__name__)

# [JUDGMENT] calibration parameters, uncalibrated placeholders.
ABSTAIN_BELOW = 0.80       # minimum probability of the predicted label to answer
MIN_KNOWN_TERMS = 3        # minimum distinct in-vocabulary features, else abstain
MAX_INPUT_CHARS = 5000     # longer messages abstain


@dataclass(frozen=True)
class Prediction:
    label: str
    probability: float     # probability of the predicted label
    known_terms: int       # distinct in-vocabulary features seen in the message


def _check_threshold(value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"abstain_below must be a real number, got {value!r}")
    v = float(value)
    if not math.isfinite(v) or not (0.0 < v <= 1.0):
        raise ValueError(f"abstain_below must be in (0, 1], got {value!r}")
    return v


def _check_min_terms(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"min_known_terms must be an int >= 1, got {value!r}")
    return value


class SmallClassifier:
    """TF-IDF + logistic regression with first-class abstention."""

    def __init__(self, examples: Sequence[tuple[str, str]] = SEED_EXAMPLES, *,
                 abstain_below: float = ABSTAIN_BELOW,
                 min_known_terms: int = MIN_KNOWN_TERMS) -> None:
        self.abstain_below = _check_threshold(abstain_below)
        self.min_known_terms = _check_min_terms(min_known_terms)

        pairs = list(examples)
        for item in pairs:
            if (not isinstance(item, tuple) or len(item) != 2
                    or not isinstance(item[0], str) or not isinstance(item[1], str)):
                raise TypeError("examples must be (text, label) string pairs")
        labels = [label for _, label in pairs]
        for label in set(labels):
            if labels.count(label) < 2:
                raise ValueError(f"need at least 2 training examples per label; '{label}' has fewer")
        if len(set(labels)) < 2:
            raise ValueError("need examples of at least two labels")

        self._vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True)
        features = self._vectorizer.fit_transform([text for text, _ in pairs])
        # liblinear + fixed seed: deterministic training.
        self._model = LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=0)
        self._model.fit(features, labels)

    def predict(self, message: str) -> Optional[Prediction]:
        """A Prediction, or None to abstain (escalate)."""
        if not isinstance(message, str):
            return None
        message = message.strip()
        if not message or len(message) > MAX_INPUT_CHARS:
            return None
        features = self._vectorizer.transform([message])
        known = int(features.nnz)
        if known < self.min_known_terms:
            return None
        probabilities = self._model.predict_proba(features)[0]
        best = int(probabilities.argmax())
        probability = float(probabilities[best])
        if probability < self.abstain_below:
            return None
        return Prediction(str(self._model.classes_[best]), probability, known)


# ---- request -> message extraction (self-gating, like tiers/deterministic.py) ----
# Literal single spaces on purpose: Stage 0 does not collapse internal
# whitespace, and the CLASSIFICATION keywords in triage/taxonomy.py are plain
# substrings. Matching exactly those substrings keeps every accepted request
# labeled CLASSIFICATION (or something more severe) by triage/classifier.py,
# which is what keeps this tier unreachable until OI-031 is decided.
_PATTERNS = (
    re.compile(r"^\s*is this spam\s*\??\s*[:\-]\s*(?P<m>.+)$", re.IGNORECASE | re.DOTALL),
    re.compile(
        r"^\s*classify this (?:(?:message|email|text|sms) )?as spam or (?:not spam|not|ham)"
        r"\s*[:\-]\s*(?P<m>.+)$",
        re.IGNORECASE | re.DOTALL),
)


def extract_message(request_text: str) -> Optional[str]:
    """The message to classify, or None if the request isn't this tier's task."""
    if not isinstance(request_text, str):
        return None
    for pattern in _PATTERNS:
        match = pattern.match(request_text)
        if match:
            message = match.group("m").strip()
            return message or None
    return None


# ---- default instance + the tier function ----
_default: Optional[SmallClassifier] = None
_default_lock = threading.Lock()


def get_default_classifier() -> SmallClassifier:
    global _default
    with _default_lock:
        if _default is None:
            _default = SmallClassifier()
        return _default


def try_small_classifier(request_text: str) -> Optional[str]:
    """Returns "spam" / "not spam", or None to escalate. Never raises."""
    try:
        message = extract_message(request_text)
        if message is None:
            return None
        prediction = get_default_classifier().predict(message)
        return None if prediction is None else prediction.label
    except Exception:
        log.exception("small classifier failed; abstaining so the ladder escalates")
        return None
