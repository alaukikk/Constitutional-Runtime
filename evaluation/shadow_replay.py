
"""Shadow replay: what would the runtime have done with a set of REAL prompts? (Sprint 7-8, step 5)

Runs Stage 0 (screen), Stage 1 (policy), Stage 3 (classifier + planner) and the deterministic tier on each
prompt, and records what it WOULD do. No model call, no network, no session state, no tuning, and the
output carries counts only: no prompt text is written anywhere (a duplicate share is computed from
hashes held in memory and discarded).

Input: a .txt file (one prompt per line) or a .jsonl file whose lines carry the prompt under "text",
"prompt" or "content", or a chat record with "conversation"/"messages" (the first user turn is used).
The owner supplies the prompts; use a source whose licence and terms allow it, and prompts you may
process (do not use other people's private conversations).

What it says: the share of real prompts the gate would refuse, the share the deterministic tier would
answer with no model, the share whose ladder offers a non-LLM rung, and how often prompts repeat (the
ceiling for a cache). What it does not say: whether any answer would be correct, or what the savings are
in tokens, energy or dollars. A replay of someone else's traffic is not shadow mode on your own users.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator, Optional

from evaluation.offline_runner import _gate
from policy.schemas import MethodTier
from tiers.deterministic import try_deterministic
from triage.classifier import classify
from triage.decision import plan_request

_MID = {MethodTier.SMALL_CLASSIFIER.value, MethodTier.RAG_SMALL_MODEL.value}
_LLM = {MethodTier.LLM_LOW_REASONING.value, MethodTier.LLM_HIGH_REASONING.value}


def _first_user(turns) -> Optional[str]:
    for t in turns or []:
        if isinstance(t, dict) and t.get("role") in ("user", "human") and isinstance(t.get("content"), str):
            return t["content"]
    return None


def read_prompts(path: Path) -> Iterator[str]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if path.suffix.lower() != ".jsonl":
                yield line
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = None
            if isinstance(rec, dict):
                for k in ("text", "prompt", "content"):
                    if isinstance(rec.get(k), str):
                        text = rec[k]
                        break
                text = text or _first_user(rec.get("conversation") or rec.get("messages"))
            elif isinstance(rec, str):
                text = rec
            if text and text.strip():
                yield text


def replay(prompts: Iterable[str]) -> dict:
    n = 0
    gate, stage0, classes, first_rung = Counter(), Counter(), Counter(), Counter()
    answered_det = mid_on_ladder = llm_only = passed = 0
    seen: Counter = Counter()
    errors = 0
    for text in prompts:
        n += 1
        seen[hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()] += 1
        try:
            sr, g, _ = _gate(text)
            gate[g] += 1
            stage0[sr.verdict.value] += 1
            if g == "block":
                continue
            passed += 1
            norm = sr.normalized_text
            classes[classify(norm).category.value] += 1
            order = tuple(t.value for t in plan_request(norm).attempt_order)
            if try_deterministic(norm) is not None:
                answered_det += 1
            if _MID & set(order):
                mid_on_ladder += 1
            if order and all(t in _LLM for t in order[-1:]) and not (set(order) - _LLM - {MethodTier.CACHE.value}):
                llm_only += 1
            first_rung[order[0] if order else "none"] += 1
        except Exception as exc:                       # a crash on one prompt is a finding, not a stop
            errors += 1
            gate["error:" + type(exc).__name__] += 1
    dup = sum(c - 1 for c in seen.values())
    pct = lambda x, d: round(x / d, 4) if d else None
    return {"prompts": n, "errors": errors, "gate": dict(gate), "stage0": dict(stage0), "passed_gate": passed,
            "classified_as": dict(classes), "first_rung": dict(first_rung),
            "deterministic_would_answer": answered_det, "non_llm_rung_on_ladder": mid_on_ladder,
            "ladder_is_llm_only": llm_only,
            "share_of_all": {"refused_by_gate": pct(gate.get("block", 0), n),
                             "needs_human_confirmation": pct(gate.get("require_human", 0), n),
                             "deterministic_would_answer": pct(answered_det, n),
                             "exact_repeats": pct(dup, n)},
            "share_of_passed": {"deterministic_would_answer": pct(answered_det, passed),
                                "non_llm_rung_on_ladder": pct(mid_on_ladder, passed)},
            "exact_repeat_prompts": dup}


def render_markdown(rep: dict, source: str) -> str:
    s, p = rep["share_of_all"], rep["share_of_passed"]
    L = ["# Shadow replay (no model calls; counts only)", "",
         f"Source file `{source}`; {rep['prompts']} prompts; {rep['errors']} raised an exception. "
         "A replay of other people's traffic, not shadow mode on your own users. No answer quality, tokens, energy or dollars.", "",
         "## Gate", *[f"- {k}: {v}" for k, v in sorted(rep["gate"].items())],
         f"- Stage 0 verdicts: {rep['stage0']}", "",
         "## What would happen to prompts that pass the gate "
         f"({rep['passed_gate']})",
         f"- classified as: {rep['classified_as']}", f"- first rung attempted: {rep['first_rung']}",
         f"- deterministic tier would answer with no model: {rep['deterministic_would_answer']} "
         f"({p['deterministic_would_answer']} of passed, {s['deterministic_would_answer']} of all)",
         f"- a non-LLM mid rung (small classifier / RAG) is on the ladder: {rep['non_llm_rung_on_ladder']} "
         f"({p['non_llm_rung_on_ladder']} of passed); those rungs are not fully built, so this is a ceiling",
         f"- refused by the gate: {s['refused_by_gate']} of all; needs human confirmation: {s['needs_human_confirmation']}",
         f"- exact repeats of an earlier prompt: {rep['exact_repeat_prompts']} ({s['exact_repeats']} of all), "
         "the ceiling for a cache on this traffic", ""]
    return "\n".join(L) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("prompts", type=Path, help=".txt (one per line) or .jsonl")
    ap.add_argument("--limit", type=int, help="use only the first N prompts")
    ap.add_argument("--sample", type=int, help="random sample of N prompts (reproducible with --seed)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--markdown", type=Path)
    a = ap.parse_args(argv)
    if not a.prompts.exists():
        print(f"no such file: {a.prompts}", file=sys.stderr)
        return 2
    prompts = list(read_prompts(a.prompts))
    if a.sample and a.sample < len(prompts):
        prompts = random.Random(a.seed).sample(prompts, a.sample)
    if a.limit:
        prompts = prompts[: a.limit]
    rep = replay(prompts)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    md = render_markdown(rep, a.prompts.name)
    if a.markdown:
        a.markdown.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
