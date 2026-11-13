
import json
import pytest
from tiers.deterministic import try_deterministic
from tiers.fact_table import FactTableError, load, try_fact
from tiers.unit_convert import try_unit_conversion

CONVERT = [
    ("convert 5 km to miles", "approx. 3.1069 miles"), ("5 km to miles", "approx. 3.1069 miles"),
    ("how many miles are in 5 km", "approx. 3.1069 miles"), ("how many cm are in 2 m", "200 cm"),
    ("convert 0 celsius to fahrenheit", "32 fahrenheit"), ("convert 100 c to f", "212 f"),
    ("convert 1 in to cm", "2.54 cm"), ("convert 1 lb to kg", "approx. 0.4536 kg"),
    ("convert 32 f to c", "0 c"), ("convert 0 c to k", "273.15 k"),
]
NO = ["convert 5 kg to km", "convert 5 ton to kg", "convert -300 c to k", "convert 5 to km", "what is 5 km",
      "convert 5 km to miles and back", "convert 5 foo to bar", "convert 5 gallons to litres"]


@pytest.mark.parametrize("q,a", CONVERT)
def test_convert(q, a):
    assert try_unit_conversion(q) == a and try_deterministic(q) == a


@pytest.mark.parametrize("q", NO)
def test_convert_falls_through(q):
    assert try_unit_conversion(q) is None


FACTS = [("What is the capital of Germany?", "Berlin"), ("capital of the UK", "London"),
         ("what's the capital of Canada?!", "Ottawa"), ("What is the chemical symbol for gold", "Au")]


@pytest.mark.parametrize("q,a", FACTS)
def test_fact(q, a):
    assert try_fact(q) == a and try_deterministic(q) == a


@pytest.mark.parametrize("q", ["what is the capital of Atlantis", "who is the prime minister of France", "capital", "what is the capital of Germany and Italy"])
def test_fact_falls_through(q):
    assert try_fact(q) is None


def _write(tmp_path, rel):
    p = tmp_path / "f.json"
    p.write_text(json.dumps({"relations": [rel]}))
    return str(p)


def test_loader_rejects_time_sensitive_and_duplicates(tmp_path):
    base = dict(name="r", kind="stable", source="s", checked="d", templates=["x {e}"], facts={"a": "1"})
    load.cache_clear()
    with pytest.raises(FactTableError):
        load(_write(tmp_path, {**base, "kind": "time_sensitive"}))
    with pytest.raises(FactTableError):
        load(_write(tmp_path, {**base, "facts": {"A": "1", "a": "2"}}))
    with pytest.raises(FactTableError):
        load(_write(tmp_path, {**base, "templates": ["no slot"]}))


def test_new_relations_and_expiry(tmp_path):
    from datetime import date
    assert try_fact("who wrote Pride and Prejudice") == "Jane Austen"
    assert try_fact("who wrote the odyssey?") == "Homer (traditionally attributed)"
    assert "100" in try_fact("what is the boiling point of water at sea level") and "212" in try_fact("what is the boiling point of water at sea level")
    assert try_fact("what does HTTP stand for") == "Hypertext Transfer Protocol"
    assert try_fact("when did the Berlin Wall fall") == "1989 (9 November)"
    assert try_fact("who is the president of France", today=date(2026, 11, 13)).startswith("As of 2026-11")
    assert try_fact("who is the president of France", today=date(2027, 4, 1)) is None     # expired: falls through
    for q in ("who wrote Atlantis", "what is the boiling point of unobtainium", "what does XYZ stand for"):
        assert try_fact(q) is None


def test_expiring_relation_requires_dates(tmp_path):
    base = dict(name="r", kind="expiring", source="s", checked="d", templates=["x {e}"], facts={"a": "1"})
    load.cache_clear()
    with pytest.raises(FactTableError):
        load(_write(tmp_path, base))
