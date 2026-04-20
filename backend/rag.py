"""Optional Chroma-backed rules retrieval used by the DM agent."""

import os
import sys
import site
from typing import Any, Dict, List, Optional

from rag_embeddings import DEFAULT_RAG_COLLECTION, DEFAULT_RAG_EMBEDDING_MODEL, get_query_embedder

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


def _remove_user_site_packages() -> None:
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        user_sites = [user_site]
    else:
        user_sites = list(user_site or [])
    normalized = {os.path.normcase(os.path.abspath(path)) for path in user_sites}
    sys.path[:] = [
        path
        for path in sys.path
        if os.path.normcase(os.path.abspath(path or os.curdir)) not in normalized
    ]


_remove_user_site_packages()

try:
    import chromadb
    from chromadb.api.models.Collection import Collection
except ImportError:
    chromadb = None
    Collection = Any


class RAGEngine:
    """Load a persisted Qwen3 vector store when available."""

    def __init__(self) -> None:
        self.db_path = self._resolve_db_path()
        self.source_root = self._resolve_source_root()
        self.collection_name = os.getenv("RAG_COLLECTION_NAME", DEFAULT_RAG_COLLECTION).strip() or DEFAULT_RAG_COLLECTION
        self.embedding_model = os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL).strip()
        self.max_context_chars = self._env_int("RAG_MAX_CONTEXT_CHARS", 6000)
        self.max_snippet_chars = self._env_int("RAG_MAX_SNIPPET_CHARS", 1800)
        self.max_results_per_source = max(1, self._env_int("RAG_MAX_RESULTS_PER_SOURCE", 2))
        self.client = None
        self.collection: Optional[Collection] = None
        self.collection_count = 0
        self.last_error = ""
        self.backend = "unavailable"
        self._load_collection()

    def _load_collection(self) -> None:
        self.client = None
        self.collection = None
        self.collection_count = 0
        self.backend = "unavailable"
        self.last_error = ""
        if chromadb is None:
            self.last_error = "chromadb is not installed"
            return

        if not self.db_path or not os.path.exists(self.db_path):
            self.last_error = "vector db path not found"
            return

        try:
            self.client = chromadb.PersistentClient(path=self.db_path)
            self.collection = self.client.get_collection(name=self.collection_name)
            self.collection_count = self.collection.count()
            if self.collection_count == 0:
                self.collection = None
                self.last_error = f"{self.collection_name} collection is empty"
            else:
                self.backend = "chroma-qwen3"
        except Exception as exc:
            self.collection = None
            self.last_error = str(exc)

    @staticmethod
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.getenv(name, str(default)) or default)
        except ValueError:
            return default

    def _resolve_db_path(self) -> str:
        explicit_path = os.getenv("RAG_VECTOR_DB_PATH", "").strip()
        if explicit_path:
            return self._resolve_config_path(explicit_path)

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
            return self._resolve_config_path(explicit_path)

        base_dir = os.path.dirname(__file__)
        candidates = [os.path.join(base_dir, "Documents", "DND5e 2024")]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[0]

    @staticmethod
    def _resolve_config_path(path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(os.path.dirname(__file__), path)

    def is_ready(self) -> bool:
        return self.collection is not None

    def refresh(self) -> bool:
        self.db_path = self._resolve_db_path()
        self.source_root = self._resolve_source_root()
        self.collection_name = os.getenv("RAG_COLLECTION_NAME", DEFAULT_RAG_COLLECTION).strip() or DEFAULT_RAG_COLLECTION
        self.embedding_model = os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL).strip()
        self.max_context_chars = self._env_int("RAG_MAX_CONTEXT_CHARS", self.max_context_chars)
        self.max_snippet_chars = self._env_int("RAG_MAX_SNIPPET_CHARS", self.max_snippet_chars)
        self.max_results_per_source = max(1, self._env_int("RAG_MAX_RESULTS_PER_SOURCE", self.max_results_per_source))
        self._load_collection()
        return self.is_ready()

    def status_payload(self) -> Dict[str, Any]:
        return {
            "enabled": self.is_ready(),
            "db_path": self.db_path,
            "source_root": self.source_root,
            "collection_name": self.collection_name,
            "collection_count": self.collection_count,
            "embedding_model": self.embedding_model,
            "backend": self.backend,
            "error": self.last_error,
            "max_context_chars": self.max_context_chars,
            "max_snippet_chars": self.max_snippet_chars,
        }

    def search(self, query: str, n_results: int = 3) -> List[Dict[str, str]]:
        normalized_query = (query or "").strip()
        if not normalized_query:
            return []
        if not self.collection:
            if not self.refresh():
                return []

        try:
            requested = max(1, min(int(n_results or 3), 8))
            query_limit = max(requested, min(requested * 4, 24))
            query_embedding = get_query_embedder().embed_queries([normalized_query])[0]
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=query_limit,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            self.last_error = str(exc)
            return []

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        candidates: List[Dict[str, str]] = []

        for index, document in enumerate(documents):
            metadata = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
            distance = distances[index] if index < len(distances) else ""
            candidates.append(
                {
                    "source": str(metadata.get("source", "unknown")),
                    "chunk_index": str(metadata.get("chunk_index", index)),
                    "heading": str(metadata.get("heading", "")),
                    "start_line": str(metadata.get("start_line", "")),
                    "end_line": str(metadata.get("end_line", "")),
                    "distance": str(distance),
                    "content": self._truncate_text(str(document).strip(), self.max_snippet_chars),
                }
            )

        return self._select_diverse(candidates, requested)

    def _select_diverse(self, snippets: List[Dict[str, str]], limit: int) -> List[Dict[str, str]]:
        selected: List[Dict[str, str]] = []
        deferred: List[Dict[str, str]] = []
        per_source: Dict[str, int] = {}

        for snippet in snippets:
            source = snippet.get("source", "unknown")
            source_count = per_source.get(source, 0)
            if source_count < self.max_results_per_source:
                selected.append(snippet)
                per_source[source] = source_count + 1
            else:
                deferred.append(snippet)
            if len(selected) >= limit:
                return selected

        selected.extend(deferred[: max(0, limit - len(selected))])
        return selected[:limit]

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return f"{text[:max_chars].rstrip()}\n..."

    def retrieve_context(self, query: str, n_results: int = 3) -> str:
        snippets = self.search(query, n_results=n_results)
        if not snippets:
            return ""

        formatted = []
        remaining = self.max_context_chars
        for snippet in snippets:
            heading = f" | {snippet['heading']}" if snippet.get("heading") else ""
            lines = ""
            if snippet.get("start_line") and snippet.get("end_line"):
                lines = f":L{snippet['start_line']}-L{snippet['end_line']}"
            block = (
                f"--- Rule Snippet ({snippet['source']}#{snippet['chunk_index']}{lines}{heading}) ---\n"
                f"{snippet['content']}"
            )
            if formatted:
                remaining -= 2
            if remaining <= 0:
                break
            block = self._truncate_text(block, remaining)
            formatted.append(block)
            remaining -= len(block)
        return "\n\n".join(formatted)
