
"""Live smoke test for the LLM gateway: the owner's first real call. Run it locally.

Option A, a free Groq key (no billing; OpenAI-style API). Windows cmd syntax, no quotes around values:
    set LLM_BACKEND=openai_compat
    set LLM_BASE_URL=https://api.groq.com/openai/v1
    set LLM_API_KEY=<your Groq key>                (never commit or paste the key)
    set LLM_MODEL_MAP={"stub-small":"openai/gpt-oss-20b","stub-medium":"openai/gpt-oss-120b","stub-large":"openai/gpt-oss-120b"}
    set LLM_MIN_INTERVAL_S=6
    set LLM_MAX_OUTPUT_TOKENS=1024
Why these values (Groq's published free limits at the time of writing, verify on your console's
limits page): 30 requests/min, 1,000/day, only 8,000 tokens/min and 200,000 tokens/day per model. A
6-second gap keeps token use under the per-minute cap. The gpt-oss models are the ones in Groq's free
table; they spend part of the output budget on hidden reasoning, so do not set max output tokens low
(an empty answer is reported as bad_response). Llama models may or may not be free on your account.
If you get bad_request, set LLM_MAX_TOKENS_PARAM=max_completion_tokens and run again.

Option B, a paid Anthropic key:
    set LLM_BACKEND=anthropic
    set ANTHROPIC_API_KEY=<key>
    set LLM_MODEL_MAP={"stub-small":"<id>","stub-medium":"<id>","stub-large":"<id>"}

Then:
    python -m llm.smoke [--aliases stub-small stub-large] [--json report.json]

The map is YOUR decision: it says which provider model answers for each catalog tier. Use the
model ids shown in your provider console; this repo does not pick them (OI-005 keeps the catalog's
cost, latency and capability numbers as placeholders, and a real mapping makes them measurable).

What it does: sends one fixed, harmless prompt ("Reply with the single word: ok") per alias and
prints, for each, success or a stable error code, the provider-reported token counts, and latency.
It prints no key and no provider error text. Exit code 0 only if every alias succeeded.
Not part of CI: it needs network access and spends a few tokens per alias.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from llm.gateway import GatewayConfig, GatewayConfigError, LLMGateway, LLMGatewayError

PROMPT = "Reply with the single word: ok"


def run(gateway: LLMGateway, aliases: list[str]) -> list[dict]:
    rows = []
    for alias in aliases:
        row = {"alias": alias, "ok": False, "error_code": "", "answer": "", "input_tokens": None,
               "output_tokens": None, "latency_ms": None}
        try:
            row["answer"] = gateway.complete(PROMPT, alias).strip()[:80]
            row["ok"] = True
        except LLMGatewayError as exc:
            row["error_code"] = exc.code
        m = gateway.last_measurement
        if m is not None and m.model_alias == alias:
            row.update(input_tokens=m.input_tokens, output_tokens=m.output_tokens, latency_ms=m.latency_ms)
        rows.append(row)
    return rows


def main(argv: Optional[list[str]] = None, gateway: Optional[LLMGateway] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aliases", nargs="+", help="catalog names to test (default: every name in LLM_MODEL_MAP)")
    ap.add_argument("--json", type=Path, help="also write the rows as JSON")
    args = ap.parse_args(argv)
    if gateway is None:
        try:
            gateway = LLMGateway(GatewayConfig.from_env())
        except GatewayConfigError as exc:
            print(f"configuration error: {exc}", file=sys.stderr)       # names the variable, never a value
            return 2
    cfg = gateway.config
    if cfg.backend == "stub":
        print("LLM_BACKEND is 'stub': nothing to test. See the module docstring.", file=sys.stderr)
        return 2
    aliases = args.aliases or sorted(cfg.model_map)
    if not aliases:
        print("LLM_MODEL_MAP is empty: map at least one catalog name to a provider model id.", file=sys.stderr)
        return 2
    rows = run(gateway, aliases)
    for r in rows:
        status = "ok" if r["ok"] else f"FAILED ({r['error_code']})"
        print(f"{r['alias']:<14} {status:<22} in={r['input_tokens']} out={r['output_tokens']} "
              f"latency_ms={r['latency_ms']} answer={r['answer']!r}")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
