from evaluation.coverage_savings import curve


def _row(tier, section, sub):
    return {"taxonomy_tier": tier, "section": section, "subcategory": sub}


def test_curve_excludes_gate_items_and_orders_cheapest_first():
    labels = [
        _row("rag_small_model", "2.1", "Semantic retrieval"),
        _row("deterministic", "2.2", "Basic arithmetic"),
        _row("deterministic", "2.2", "Basic arithmetic"),
        _row("(gate decides)", "n/a", "gate"),
        _row("llm_low_reasoning", "2.14", "creative"),
    ]
    n, rows = curve(labels, 100)
    assert n == 4  # gate item excluded, LLM item counted in the denominator
    assert [r["tier"] for r in rows] == ["deterministic", "rag_small_model"]
    assert rows[-1]["cumulative"] == 3 and rows[-1]["tokens"] == 300
