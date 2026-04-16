"""Optional Chroma-backed rules retrieval used by the DM agent."""

import os
import json
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.api.models.Collection import Collection
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None
    Collection = Any
    embedding_functions = None


class RAGEngine:
    """Load a persisted vector store when available and fail soft otherwise."""

    def __init__(self) -> None:
        self.db_path = self._resolve_db_path()
        self.source_root = self._resolve_source_root()
        self.client = None
        self.collection: Optional[Collection] = None
        self.last_error = ""
        self.backend = "unavailable"
        self.rg_path = shutil.which("rg")

        if chromadb is None or embedding_functions is None:
            self.last_error = "chromadb is not installed"
            if self._fallback_ready():
                self.backend = "ripgrep"
                self.last_error = ""
            return

        if not self.db_path or not os.path.exists(self.db_path):
            self.last_error = "vector db path not found"
            if self._fallback_ready():
                self.backend = "ripgrep"
                self.last_error = ""
            return

        try:
            self.client = chromadb.PersistentClient(path=self.db_path)
            embedding_function = embedding_functions.DefaultEmbeddingFunction()
            self.collection = self.client.get_collection(
                name="dnd_rules",
                embedding_function=embedding_function,
            )
            if self.collection.count() == 0:
                self.collection = None
                self.last_error = "dnd_rules collection is empty"
            else:
                self.backend = "chroma"
        except Exception as exc:
            self.collection = None
            self.last_error = str(exc)
            if self._fallback_ready():
                self.backend = "ripgrep"
                self.last_error = ""

    def _resolve_db_path(self) -> str:
        explicit_path = os.getenv("RAG_VECTOR_DB_PATH", "").strip()
        if explicit_path:
            return explicit_path

        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "Knowledge", "vector_db"),
            os.path.join(base_dir, "data", "vector_db"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[0]

    def _resolve_source_root(self) -> str:
        explicit_path = os.getenv("RAG_SOURCE_ROOT", "").strip()
        if explicit_path:
            return explicit_path

        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, "Knowledge", "dnd_md_output"),
            os.path.join(base_dir, "Documents", "DND5e 2024"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[-1]

    def _fallback_ready(self) -> bool:
        return bool(self.rg_path and self.source_root and os.path.exists(self.source_root))

    def is_ready(self) -> bool:
        return self.collection is not None or self._fallback_ready()

    def status_payload(self) -> Dict[str, Any]:
        return {
            "enabled": self.is_ready(),
            "db_path": self.db_path,
            "source_root": self.source_root,
            "collection_name": "dnd_rules",
            "backend": self.backend,
            "error": self.last_error,
        }

    def search(self, query: str, n_results: int = 3) -> List[Dict[str, str]]:
        normalized_query = (query or "").strip()
        if not normalized_query or not self.collection:
            if self._fallback_ready():
                return self._fallback_search(normalized_query, n_results=n_results)
            return []

        try:
            results = self.collection.query(
                query_texts=[normalized_query],
                n_results=max(1, min(int(n_results or 3), 5)),
            )
        except Exception as exc:
            self.last_error = str(exc)
            return []

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        snippets: List[Dict[str, str]] = []

        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
            snippets.append(
                {
                    "source": str(metadata.get("source", "unknown")),
                    "chunk_index": str(metadata.get("chunk_index", index)),
                    "content": str(document).strip(),
                }
            )

        return snippets

    def _fallback_search(self, query: str, n_results: int = 3) -> List[Dict[str, str]]:
        terms = self._extract_terms(query)
        if not terms or not self.rg_path:
            return []

        command = [
            self.rg_path,
            "--json",
            "-n",
            "-S",
            "-m",
            "2",
            "--glob",
            "*.md",
        ]
        for term in terms:
            command.extend(["-e", term])
        command.append(self.source_root)

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return []

        matches: List[Dict[str, Any]] = []
        for raw_line in completed.stdout.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if payload.get("type") != "match":
                continue
            data = payload.get("data", {})
            path = str(data.get("path", {}).get("text", ""))
            line_number = int(data.get("line_number", 0) or 0)
            line_text = str(data.get("lines", {}).get("text", "")).strip()
            if not path or line_number <= 0:
                continue
            score = sum(line_text.lower().count(term.lower()) for term in terms)
            matches.append(
                {
                    "path": path,
                    "line_number": line_number,
                    "score": score,
                    "line_text": line_text,
                }
            )

        matches.sort(key=lambda item: (-item["score"], item["path"], item["line_number"]))
        snippets: List[Dict[str, str]] = []
        for match in matches[: max(1, min(int(n_results or 3), 5))]:
            snippet_text = self._read_snippet(match["path"], match["line_number"])
            snippets.append(
                {
                    "source": os.path.relpath(match["path"], self.source_root),
                    "chunk_index": str(match["line_number"]),
                    "content": snippet_text or match["line_text"],
                }
            )
        return snippets

    def _extract_terms(self, query: str) -> List[str]:
        terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}", query)
        if not terms:
            terms = [query.strip()]
        deduped: List[str] = []
        for term in terms:
            if term not in deduped:
                deduped.append(term)
        return deduped[:6]

    def _read_snippet(self, path: str, line_number: int, context_lines: int = 2) -> str:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except Exception:
            return ""

        start = max(0, line_number - 1 - context_lines)
        end = min(len(lines), line_number + context_lines)
        snippet_parts = []
        for offset in range(start, end):
            snippet_parts.append(f"{offset + 1}: {lines[offset].rstrip()}")
        return "\n".join(snippet_parts).strip()

    def retrieve_context(self, query: str, n_results: int = 3) -> str:
        snippets = self.search(query, n_results=n_results)
        if not snippets:
            return ""

        formatted = []
        for snippet in snippets:
            formatted.append(
                f"--- Rule Snippet ({snippet['source']}#{snippet['chunk_index']}) ---\n{snippet['content']}"
            )
        return "\n\n".join(formatted)
