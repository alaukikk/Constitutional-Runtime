
"""Stage 5 LLM rung: the most expensive tier. Delegates to llm.gateway, which defaults to a stub
(offline, deterministic) and only calls a real model when LLM_BACKEND=anthropic, a key and an
explicit model map are configured. The signature is unchanged, so Stage 5, repair and the
adversarial harness (which patches this name) are unaffected."""
from llm.gateway import get_gateway


def call_llm(request_text: str, model_name: str = "stub-model") -> str:
    return get_gateway().complete(request_text, model_name)
