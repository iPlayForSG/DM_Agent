import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from rag import RAGEngine
from rag_embeddings import Qwen3EmbeddingFunction
from rule_document_normalizer import normalize_corpus


class RuleDocumentNormalizationTests(unittest.TestCase):
    def test_normalizes_markdown_and_applies_search_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            (source / "Combat.txt").write_text("COMBAT\r\n\r\n\r\n##Grapple\r\n•  Make a check.  \r\n", encoding="utf-8")
            overrides = root / "overrides.json"
            overrides.write_text(json.dumps({
                "documents": {
                    "Combat.txt": {"title": "Combat Rules", "aliases": ["grapple", "擒抱"]},
                },
            }), encoding="utf-8")

            manifest = normalize_corpus(source, output, overrides)
            normalized = (output / "Combat.md").read_text(encoding="utf-8")

            self.assertEqual(manifest["document_count"], 1)
            self.assertTrue(normalized.startswith("# Combat Rules\n"))
            self.assertIn("> Search aliases: grapple, 擒抱", normalized)
            self.assertIn("## Grapple", normalized)
            self.assertIn("- Make a check.", normalized)
            self.assertNotIn("\r", normalized)


class RAGFallbackTests(unittest.TestCase):
    def test_uses_normalized_lexical_corpus_when_vector_db_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lexical = root / "grep_corpus"
            raw = root / "raw"
            lexical.mkdir()
            raw.mkdir()
            (lexical / "combat.md").write_text(
                "# Combat\n\n## Grappling\nA grapple uses an Unarmed Strike and an escape DC.\n",
                encoding="utf-8",
            )
            env = {
                "RAG_VECTOR_DB_PATH": str(root / "missing-vector-db"),
                "RAG_SOURCE_ROOT": str(raw),
                "RAG_LEXICAL_ROOT": str(lexical),
            }
            with patch.dict(os.environ, env, clear=False):
                engine = RAGEngine()
                results = engine.search("grapple escape DC", n_results=2)

            self.assertTrue(engine.is_ready())
            self.assertEqual(engine.backend, "lexical-grep")
            self.assertTrue(results)
            self.assertEqual(results[0]["source"], "combat.md")
            self.assertIn("escape DC", results[0]["content"])
            status = engine.status_payload()
            self.assertFalse(status["vector_ready"])
            self.assertTrue(status["lexical_ready"])
            self.assertTrue(status["fallback_reason"])

    def test_falls_back_after_embedding_query_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lexical = root / "grep_corpus"
            lexical.mkdir()
            (lexical / "magic.md").write_text(
                "# Magic\n\n## Concentration\nTaking damage can trigger a Constitution saving throw.\n",
                encoding="utf-8",
            )
            env = {
                "RAG_VECTOR_DB_PATH": str(root / "missing-vector-db"),
                "RAG_SOURCE_ROOT": str(root / "raw"),
                "RAG_LEXICAL_ROOT": str(lexical),
            }
            with patch.dict(os.environ, env, clear=False):
                engine = RAGEngine()
                engine.collection = object()
                engine.backend = "chroma-llama-cpp-gguf"
                with patch.object(engine, "_query_collection", side_effect=RuntimeError("embedding missing")):
                    results = engine.search("concentration Constitution", n_results=1)

            self.assertTrue(results)
            self.assertEqual(engine.backend, "lexical-grep")
            self.assertIn("embedding missing", engine.vector_error)


class CrossPlatformLlamaServerTests(unittest.TestCase):
    def test_resolves_posix_llama_server_from_path(self) -> None:
        embedder = Qwen3EmbeddingFunction.__new__(Qwen3EmbeddingFunction)
        embedder.llama_cpp_dir = "/missing/local/llama_cpp"
        with patch.dict(os.environ, {"RAG_LLAMA_SERVER_PATH": ""}, clear=False), patch(
            "rag_embeddings.shutil.which",
            side_effect=lambda command: "/opt/local/bin/llama-server" if command == "llama-server" else None,
        ):
            resolved = embedder._resolve_llama_server_path()

        self.assertEqual(resolved, "/opt/local/bin/llama-server")


if __name__ == "__main__":
    unittest.main()
