"""Local embedding helpers for the D&D rules RAG index."""

import os
from functools import lru_cache
from typing import Iterable, List


DEFAULT_RAG_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_RAG_COLLECTION = "dnd_rules_qwen3_embedding_8b"


class Qwen3EmbeddingFunction:
    """SentenceTransformer-backed embedding function with separate query prompts."""

    def __init__(
        self,
        model_name: str = "",
        cache_folder: str = "",
        batch_size: int = 4,
        device: str = "",
    ) -> None:
        self.model_name = model_name or os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL)
        self.cache_folder = self._resolve_cache_folder(cache_folder or os.getenv(
            "RAG_MODEL_CACHE",
            os.path.join(os.path.dirname(__file__), "Knowledge", "hf_cache"),
        ))
        self.batch_size = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", str(batch_size)) or batch_size)
        self.device = device or os.getenv("RAG_EMBEDDING_DEVICE", "")
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        from sentence_transformers import SentenceTransformer

        kwargs = {}
        if self.cache_folder:
            kwargs["cache_folder"] = self.cache_folder
        if self.device:
            kwargs["device"] = self.device

        self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model

    @staticmethod
    def _resolve_cache_folder(path: str) -> str:
        if not path or os.path.isabs(path):
            return path
        return os.path.join(os.path.dirname(__file__), path)

    @staticmethod
    def _clean_texts(texts: Iterable[str]) -> List[str]:
        return [str(text or "").strip() for text in texts]

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        cleaned = self._clean_texts(texts)
        if not cleaned:
            return []
        embeddings = self._load_model().encode(
            cleaned,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.astype("float32").tolist()

    def embed_queries(self, texts: Iterable[str]) -> List[List[float]]:
        cleaned = self._clean_texts(texts)
        if not cleaned:
            return []
        embeddings = self._load_model().encode(
            cleaned,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            prompt_name="query",
            show_progress_bar=False,
        )
        return embeddings.astype("float32").tolist()


@lru_cache(maxsize=1)
def get_query_embedder() -> Qwen3EmbeddingFunction:
    return Qwen3EmbeddingFunction()
