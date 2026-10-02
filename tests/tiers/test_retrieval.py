
import tempfile
import unittest
from pathlib import Path

from tiers.retrieval import (
    DOCS_DIR, Hit, Passage, Retriever, chunk_markdown, load_docs_corpus,
)

FILES = {
    "cache.md": "# Cache tier\n\nThe cache tier answers exact repeats of a normalized message.\n"
                "It never bypasses the security screen.\n",
    "energy.md": "# Energy\n\nInference energy depends on model size, output length and reasoning depth.\n",
    "session.md": "# Session context\n\nThe session floor is a ratchet that can only tighten constraints.\n",
}


def make_corpus(files=FILES):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    return tmp, root


class TestChunking(unittest.TestCase):
    def test_new_passage_at_every_heading_with_provenance(self):
        passages = chunk_markdown("# A\n\none\n\n## B\n\ntwo\n", "docs/x.md")
        self.assertEqual([p.chunk_index for p in passages], [0, 1])
        self.assertTrue(all(p.source == "docs/x.md" for p in passages))
        self.assertIn("one", passages[0].text)
        self.assertIn("two", passages[1].text)

    def test_paragraphs_pack_up_to_max_chars(self):
        text = "# H\n\n" + "\n\n".join(["w " * 20] * 6)
        passages = chunk_markdown(text, "s", max_chars=100)
        self.assertGreater(len(passages), 1)
        self.assertTrue(all(len(p.text) <= 100 for p in passages))

    def test_oversized_paragraph_is_hard_split_and_nothing_is_lost(self):
        body = "x" * 250
        passages = chunk_markdown(body, "s", max_chars=100)
        self.assertEqual("".join(p.text for p in passages), body)

    def test_bad_max_chars_rejected(self):
        for bad in (0, 49, True, "100"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                chunk_markdown("text", "s", max_chars=bad)


class TestLoading(unittest.TestCase):
    def test_loads_only_markdown_sorted_with_provenance(self):
        tmp, root = make_corpus({**FILES, "notes.txt": "ignored", "UP.MD": "# Upper\n\nbody text here\n"})
        self.addCleanup(tmp.cleanup)
        sources = [p.source for p in load_docs_corpus(root)]
        self.assertIn("docs/UP.MD", sources)
        self.assertNotIn("docs/notes.txt", sources)
        self.assertEqual(sources, sorted(sources, key=str.lower))

    def test_symlink_escaping_the_folder_is_skipped(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        secret = Path(outside.name) / "secret.md"
        secret.write_text("# Secret\n\ndo not index me\n")
        tmp, root = make_corpus()
        self.addCleanup(tmp.cleanup)
        try:
            (root / "link.md").symlink_to(secret)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available here")
        self.assertNotIn("docs/link.md", [p.source for p in load_docs_corpus(root)])

    def test_missing_or_empty_folder_fails_loudly(self):
        with self.assertRaises(FileNotFoundError):
            load_docs_corpus(Path("/definitely/not/here"))
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(ValueError):
            load_docs_corpus(Path(empty))

    def test_real_docs_folder_loads_with_provenance(self):
        if not DOCS_DIR.is_dir():
            self.skipTest("docs/ not present in this checkout")
        passages = load_docs_corpus()
        self.assertGreater(len(passages), 0)
        self.assertTrue(all(p.source.startswith("docs/") and p.source.lower().endswith(".md")
                            for p in passages))

    def test_real_docs_known_answer_is_in_the_top_results(self):
        if not (DOCS_DIR / "ARCHITECTURE.md").is_file():
            self.skipTest("docs/ARCHITECTURE.md not present in this checkout")
        hits = Retriever(load_docs_corpus()).search("stateless security screen runs first on every request", k=5)
        self.assertIn("docs/ARCHITECTURE.md", [h.passage.source for h in hits])


class TestRetriever(unittest.TestCase):
    def setUp(self):
        tmp, root = make_corpus()
        self.addCleanup(tmp.cleanup)
        self.retriever = Retriever(load_docs_corpus(root))

    def test_relevant_query_ranks_the_right_source_first(self):
        hits = self.retriever.search("what answers exact repeats of a message", k=3)
        self.assertEqual(hits[0].passage.source, "docs/cache.md")
        self.assertGreater(hits[0].score, 0)
        self.assertTrue(all(isinstance(h, Hit) for h in hits))

    def test_scores_are_sorted_and_within_bounds(self):
        hits = self.retriever.search("model size output length energy tier", k=3)
        scores = [h.score for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 < s <= 1.0 + 1e-9 for s in scores))

    def test_no_vocabulary_overlap_abstains(self):
        self.assertEqual(self.retriever.search("zxqv wlkj plmn"), [])

    def test_blank_or_non_string_query_abstains(self):
        for q in ("", "   ", None, 123):
            with self.subTest(q=q):
                self.assertEqual(self.retriever.search(q), [])

    def test_min_score_abstains_on_weak_evidence(self):
        strict = Retriever(self.retriever._passages, min_score=1.0)
        self.assertEqual(strict.search("cache tier"), [])

    def test_k_limits_results_and_is_validated(self):
        self.assertLessEqual(len(self.retriever.search("tier session energy cache", k=1)), 1)
        for bad in (0, -1, True, 2.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.retriever.search("cache", k=bad)

    def test_bad_construction_rejected(self):
        with self.assertRaises(ValueError):
            Retriever([])
        with self.assertRaises(TypeError):
            Retriever(["not a passage"])
        for bad in (-0.1, 1.1, float("nan")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Retriever(self.retriever._passages, min_score=bad)

    def test_ties_break_deterministically(self):
        twin = [Passage("docs/b.md", 0, "alpha beta gamma"), Passage("docs/a.md", 0, "alpha beta gamma")]
        hits = Retriever(twin).search("alpha beta gamma", k=2)
        self.assertEqual([h.passage.source for h in hits], ["docs/a.md", "docs/b.md"])

    def test_corpus_fingerprint_is_stable_and_changes_with_content(self):
        base = [Passage("docs/a.md", 0, "alpha beta gamma delta")]
        self.assertEqual(Retriever(base).corpus_fingerprint, Retriever(list(base)).corpus_fingerprint)
        edited = [Passage("docs/a.md", 0, "alpha beta gamma delta!")]
        self.assertNotEqual(Retriever(base).corpus_fingerprint, Retriever(edited).corpus_fingerprint)

    def test_nothing_in_the_live_pipeline_depends_on_retrieval(self):
        import tiers.rag_small_model as rag
        self.assertIsNone(rag.try_rag_small_model("what does the architecture say about the cache tier?"))


if __name__ == "__main__":
    unittest.main()
