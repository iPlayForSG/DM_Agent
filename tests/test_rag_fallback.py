import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from lexical_rag import LexicalRuleIndex
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

    def test_disambiguates_duplicate_default_titles_with_parent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            (source / "Player Handbook").mkdir(parents=True)
            (source / "Rules Glossary").mkdir(parents=True)
            (source / "Player Handbook" / "Actions.md").write_text("## Attack\n", encoding="utf-8")
            (source / "Rules Glossary" / "Actions.md").write_text("## Help\n", encoding="utf-8")

            manifest = normalize_corpus(source, output, root / "missing-overrides.json")

            self.assertEqual(
                [document["title"] for document in manifest["documents"]],
                ["Player Handbook — Actions", "Rules Glossary — Actions"],
            )
            self.assertTrue((output / "Player Handbook" / "Actions.md").read_text(encoding="utf-8").startswith(
                "# Player Handbook — Actions\n"
            ))

    def test_inherits_directory_aliases_and_deduplicates_document_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            document_root = source / "Core" / "Player Handbook"
            document_root.mkdir(parents=True)
            (document_root / "Combat.md").write_text("## Combat\n", encoding="utf-8")
            overrides = root / "overrides.json"
            overrides.write_text(json.dumps({
                "directories": {
                    "Core": {"aliases": ["core rules"]},
                    "Core/Player Handbook": {"aliases": ["PHB 2024"]},
                },
                "documents": {
                    "Core/Player Handbook/Combat.md": {"aliases": ["phb 2024", "战斗规则"]},
                },
            }), encoding="utf-8")

            manifest = normalize_corpus(source, output, overrides)
            normalized = (document_root.relative_to(source) / "Combat.md")
            normalized_text = (output / normalized).read_text(encoding="utf-8")

            self.assertEqual(manifest["documents"][0]["aliases"], ["core rules", "PHB 2024", "战斗规则"])
            self.assertIn("> Search aliases: core rules, PHB 2024, 战斗规则", normalized_text)

    def test_repairs_generated_table_separator_without_editing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            original = "| d100 | Anchor | Destination | Key |\n| --- | --- | --- |\n| 1 | Arch | Sigil | Coin |\n"
            source_path = source / "Portals.md"
            source_path.write_text(original, encoding="utf-8")

            normalize_corpus(source, output, root / "missing-overrides.json")

            self.assertEqual(source_path.read_text(encoding="utf-8"), original)
            normalized = (output / "Portals.md").read_text(encoding="utf-8")
            self.assertIn("| --- | --- | --- | --- |", normalized)

    def test_separates_flattened_table_from_heading_and_reports_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            flattened_table = " | ".join(["cell"] * 260)
            (source / "Weapons.md").write_text(
                f"### Weapons | {flattened_table} |\n",
                encoding="utf-8",
            )

            manifest = normalize_corpus(source, output, root / "missing-overrides.json")
            normalized = (output / "Weapons.md").read_text(encoding="utf-8")

            self.assertIn("\n### Weapons\n| cell", normalized)
            self.assertNotIn("### Weapons | cell", normalized)
            self.assertEqual(manifest["quality_warning_counts"], {"flattened-table-line": 1})
            self.assertEqual(manifest["documents"][0]["quality_warnings"], ["flattened-table-line:6"])


class RAGFallbackTests(unittest.TestCase):
    def test_uses_normalized_lexical_corpus_by_default_without_vector_probe(self) -> None:
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
                "RAG_RETRIEVAL_MODE": "",
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
            self.assertEqual(status["retrieval_mode"], "lexical")
            self.assertFalse(status["vector_ready"])
            self.assertEqual(status["vector_error"], "")
            self.assertTrue(status["lexical_ready"])
            self.assertEqual(status["fallback_reason"], "")

    def test_lexical_mode_does_not_query_embedding_when_collection_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lexical = root / "grep_corpus"
            lexical.mkdir()
            (lexical / "combat.md").write_text(
                "# Combat\n\n## Grappling\nA grapple uses an Unarmed Strike.\n",
                encoding="utf-8",
            )
            env = {
                "RAG_RETRIEVAL_MODE": "lexical",
                "RAG_SOURCE_ROOT": str(root / "raw"),
                "RAG_LEXICAL_ROOT": str(lexical),
            }
            with patch.dict(os.environ, env, clear=False):
                engine = RAGEngine()
                engine.collection = object()
                with patch.object(engine, "_query_collection") as vector_query:
                    results = engine.search("grapple", n_results=1)

            vector_query.assert_not_called()
            self.assertTrue(results)
            self.assertEqual(engine.backend, "lexical-grep")

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
                "RAG_RETRIEVAL_MODE": "vector",
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

    def test_document_aliases_are_scored_for_every_heading_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "monster.md").write_text(
                "# Red Dragon\n\n> Source: monster.md\n> Search aliases: MM 2025, Monster Manual 2025\n\n"
                "## Red Dragon Lairs\nA dragon guards its lair.\n",
                encoding="utf-8",
            )
            (root / "spell.md").write_text(
                "# Summon Dragon\n\nA dragon spell mentions dragon several times.\n",
                encoding="utf-8",
            )
            index = LexicalRuleIndex([root])

            results = index.search(["MM dragon"], limit=2)

            self.assertEqual(results[0]["source"], "monster.md")
            self.assertIn("Red Dragon Lairs", results[0]["heading"])


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
