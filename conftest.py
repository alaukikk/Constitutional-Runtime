"""Repo-wide test safety: no test may reach a real model, whatever the environment says.

If LLM_BACKEND=anthropic (and a key) happen to be exported in the shell that runs pytest, an
unpatched call_llm would make a real, billable call. This autouse fixture installs the stub gateway
for every test; tests that exercise the real backend build their own gateway with a fake transport."""
import pytest

from llm import gateway as _gw


@pytest.fixture(autouse=True)
def _offline_llm_gateway():
    _gw.set_gateway(_gw.LLMGateway(_gw.GatewayConfig()))
    yield
    _gw.set_gateway(None)
