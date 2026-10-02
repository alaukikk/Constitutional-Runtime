
"""
tiers/retrieval.py -- TF-IDF retrieval over a document folder (Sprint 4 prototype).

*** THIS IS RETRIEVAL, NOT THE RAG TIER. ***
It implements only the "fetch relevant reference material" half of
tiers/rag_small_model.py's contract. The other half -- feeding that material to
a small model that writes the answer -- does not exist yet (OI-006), so
tiers/rag_small_model.py keeps returning None and nothing in the live pipeline
calls this module. Returning an extracted passage as if it were a RAG answer
would misrepresent the architecture; don't.

Basis (see docs/RESEARCH_TRACEABILITY.md):
  [PROJECT]  docs/TAXONOMY.MD 2.13 defines grounded synthesis as retrieval + a
             small model; 2.1 lists semantic retrieval under rag_small_model.py.
  [RESEARCH] "A Review of Prominent Paradigms for LLM-Based Agents", Section 4.2
             (page 5 of the supplied file): in passive RAG a retrieval mechanism
             supplies relevant information that the model then uses to generate
             the response -- i.e. retrieval augments generation, it does not
             replace it.
  [JUDGMENT] TF-IDF + cosine similarity as the retrieval method, chunk size, and
             `min_score`. Chosen for determinism, zero downloads and easy manual
             verification, not because the literature requires it.
  [JUDGMENT] The docs/ folder as the corpus is a CONTROLLED PROTOTYPE corpus
             (versioned, known provenance, answers checkable by hand). It is not
             the evaluation corpus; the experiment needs a separate held-out set.

Abstention: search() returns an empty list when the query shares no vocabulary
with the corpus or no passage clears `min_score`, so a caller can escalate
instead of answering from weak evidence.

Determinism/provenance: passages are ordered by (source, chunk_index), ties
break on the same key, and `Retriever.corpus_fingerprint` is a SHA-256 of every
passage, so a result can be tied to the exact corpus version it came from.
Loading reads only regular *.md files that live directly in the folder
(symlinks pointing elsewhere are skipped) and resolves the folder from this
file's location, not the working directory.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from sklearn.feature_extraction.text import TfidfVectorizer

DEFAULT_MAX_CHARS = 800
DEFAULT_MIN_SCORE = 0.10          # [JUDGMENT] calibration parameter, uncalibrated
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


@dataclass(frozen=True)
class Passage:
    source: str          # e.g. "docs/ARCHITECTURE.md"
    chunk_index: int     # position within that source
    text: str


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float         # cosine similarity in [0, 1]


def chunk_markdown(text: str, source: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Passage]:
    """Split markdown into passages: a new passage at every heading, paragraphs
    packed up to max_chars, oversized paragraphs hard-split."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 50:
        raise ValueError("max_chars must be an int >= 50")
    passages: list[Passage] = []

    def emit(body: str) -> None:
        if body.strip():
            passages.append(Passage(source, len(passages), body.strip()))

    for section in re.split(r"(?m)^(?=#{1,6}\s)", text):
        buf = ""
        for para in (p.strip() for p in re.split(r"\n\s*\n", section)):
            if not para:
                continue
            if buf and len(buf) + 2 + len(para) > max_chars:
                emit(buf)
                buf = ""
            while len(para) > max_chars:
                if buf:
                    emit(buf)
                    buf = ""
                emit(para[:max_chars])
                para = para[max_chars:]
            if para:
                buf = f"{buf}\n\n{para}" if buf else para
        emit(buf)
    return passages


def load_docs_corpus(docs_dir: Optional[Path] = None,
                     max_chars: int = DEFAULT_MAX_CHARS) -> list[Passage]:
    base = Path(docs_dir) if docs_dir is not None else DOCS_DIR
    if not base.is_dir():
        raise FileNotFoundError(f"corpus folder not found: {base}")
    base_resolved = base.resolve()
    files = sorted(
        (p for p in base.iterdir()
         if p.is_file() and p.suffix.lower() == ".md" and p.resolve().parent == base_resolved),
        key=lambda p: p.name.lower())
    passages: list[Passage] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        passages.extend(chunk_markdown(text, f"docs/{path.name}", max_chars))
    if not passages:
        raise ValueError(f"no markdown passages found in {base}")
    return passages


def _check_min_score(value) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"min_score must be a real number, got {value!r}")
    v = float(value)
    if not math.isfinite(v) or not (0.0 <= v <= 1.0):
        raise ValueError(f"min_score must be in [0, 1], got {value!r}")
    return v


class Retriever:
    def __init__(self, passages: Sequence[Passage], *, min_score: float = DEFAULT_MIN_SCORE) -> None:
        self._passages = tuple(passages)
        if not self._passages:
            raise ValueError("corpus is empty")
        if not all(isinstance(p, Passage) for p in self._passages):
            raise TypeError("passages must be Passage instances")
        self.min_score = _check_min_score(min_score)
        self._vectorizer = TfidfVectorizer(lowercase=True, stop_words="english",
                                           ngram_range=(1, 2), sublinear_tf=True)
        self._matrix = self._vectorizer.fit_transform([p.text for p in self._passages])
        self.corpus_fingerprint = hashlib.sha256(json.dumps(
            [[p.source, p.chunk_index, p.text] for p in self._passages],
            ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()

    def __len__(self) -> int:
        return len(self._passages)

    def search(self, query: str, k: int = 3) -> list[Hit]:
        """Up to k passages with score >= min_score, best first. [] means no
        usable evidence (abstain / escalate)."""
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k must be an int >= 1")
        if not isinstance(query, str) or not query.strip():
            return []
        q = self._vectorizer.transform([query])
        if q.nnz == 0:
            return []
        scores = (self._matrix @ q.T).toarray().ravel()
        order = sorted(range(len(self._passages)),
                       key=lambda i: (-scores[i], self._passages[i].source, self._passages[i].chunk_index))
        return [Hit(self._passages[i], float(scores[i]))
                for i in order[:k] if scores[i] > 0 and scores[i] >= self.min_score]
