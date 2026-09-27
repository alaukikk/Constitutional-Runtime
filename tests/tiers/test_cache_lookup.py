
import pytest
import tiers.cache_lookup as cache_lookup


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.last_ex = None
    def ping(self): return True
    def get(self, key): return self.store.get(key)
    def set(self, key, value, ex=None):
        self.last_ex = ex
        self.store[key] = value


@pytest.fixture(autouse=True)
def reset_client():
    cache_lookup._client = None
    yield
    cache_lookup._client = None


def test_graceful_degradation_with_no_client_available(monkeypatch):
    monkeypatch.setattr(cache_lookup, "redis", None)  # force "package unavailable" path deterministically
    cache_lookup._client = None
    assert cache_lookup.try_cache_lookup("anything") is None
    cache_lookup.store_cache_entry("anything", "some answer")

def test_hit_after_store():
    cache_lookup.configure_client(FakeRedis())
    assert cache_lookup.try_cache_lookup("what is the capital of France?") is None
    cache_lookup.store_cache_entry("what is the capital of France?", "Paris")
    assert cache_lookup.try_cache_lookup("what is the capital of France?") == "Paris"


@pytest.mark.parametrize("variant", [
    "What is the capital of France?",
    "what is the capital of France? ",
    "what's the capital of France?",
])
def test_exact_match_only_no_fuzzy_matching(variant):
    fake = FakeRedis()
    cache_lookup.configure_client(fake)
    cache_lookup.store_cache_entry("what is the capital of France?", "Paris")
    assert cache_lookup.try_cache_lookup(variant) is None


def test_keys_are_hashed_not_raw_text():
    fake = FakeRedis()
    cache_lookup.configure_client(fake)
    cache_lookup.store_cache_entry("what is the capital of France?", "Paris")
    keys = list(fake.store.keys())
    assert all("what is the capital" not in k for k in keys)
    assert all(k.startswith("cache_lookup:v1:") for k in keys)


def test_ttl_passed_through():
    fake = FakeRedis()
    cache_lookup.configure_client(fake)
    cache_lookup.store_cache_entry("q", "a")
    assert fake.last_ex == 60 * 60 * 24
