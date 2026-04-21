"""Local GGUF embedding helpers backed by llama.cpp server."""

import atexit
import json
import math
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from functools import lru_cache
from glob import glob
from pathlib import Path
from typing import Iterable, List


DEFAULT_RAG_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B-GGUF"
DEFAULT_RAG_GGUF_FILENAME = "Qwen3-Embedding-4B-Q6_K.gguf"
DEFAULT_RAG_COLLECTION = "dnd_rules_qwen3_embedding_4b_q6_k"
DEFAULT_QUERY_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query"


def resolve_config_path(path: str) -> str:
    if not path or os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), path)


class Qwen3EmbeddingFunction:
    """llama.cpp-backed embedding function using a local OpenAI-compatible endpoint."""

    def __init__(
        self,
        model_name: str = "",
        cache_folder: str = "",
        batch_size: int = 32,
        device: str = "",
    ) -> None:
        self.model_name = model_name or os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL)
        self.cache_folder = resolve_config_path(
            cache_folder
            or os.getenv("RAG_MODEL_CACHE", os.path.join(os.path.dirname(__file__), "Knowledge", "hf_cache"))
        )
        self.batch_size = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", str(batch_size)) or batch_size)
        self.device = (device or os.getenv("RAG_EMBEDDING_DEVICE", "cuda") or "cuda").strip().lower()
        self.port = int(os.getenv("RAG_LLAMA_SERVER_PORT", "8092") or 8092)
        self.host = os.getenv("RAG_LLAMA_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
        self.base_url = (
            os.getenv("RAG_EMBEDDING_SERVER_BASE_URL", "").strip() or f"http://{self.host}:{self.port}"
        ).rstrip("/")
        self.context_size = int(os.getenv("RAG_LLAMA_SERVER_CTX", "4096") or 4096)
        self.ubatch = int(os.getenv("RAG_LLAMA_SERVER_UBATCH", "8192") or 8192)
        self.n_gpu_layers = int(os.getenv("RAG_LLAMA_SERVER_GPU_LAYERS", "999") or 999)
        self.startup_timeout_s = int(os.getenv("RAG_LLAMA_SERVER_STARTUP_TIMEOUT_S", "180") or 180)
        self.request_timeout_s = int(os.getenv("RAG_EMBEDDING_TIMEOUT_S", "600") or 600)
        self.max_retries = int(os.getenv("RAG_EMBEDDING_MAX_RETRIES", "3") or 3)
        self.min_batch_size = max(1, int(os.getenv("RAG_EMBEDDING_MIN_BATCH_SIZE", "8") or 8))
        self.pooling = os.getenv("RAG_GGUF_POOLING", "last").strip() or "last"
        self.query_instruct = os.getenv("RAG_QUERY_INSTRUCT", DEFAULT_QUERY_INSTRUCT).strip() or DEFAULT_QUERY_INSTRUCT
        self.llama_cpp_dir = self._resolve_llama_cpp_dir()
        self.llama_server_path = self._resolve_llama_server_path()
        self.model_path = self._resolve_model_path()
        self.model_label = os.path.basename(self.model_path)
        self._process = None
        self._started_local_process = False
        atexit.register(self.shutdown)

    def _resolve_llama_cpp_dir(self) -> str:
        configured = os.getenv("RAG_LLAMA_CPP_DIR", "").strip()
        if configured:
            return resolve_config_path(configured)

        candidates = [
            os.path.join(os.path.dirname(__file__), "Knowledge", "llama_cpp", "b8833-cuda12"),
            os.path.join(os.path.dirname(__file__), "Knowledge", "llama_cpp"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return candidates[0]

    def _resolve_llama_server_path(self) -> str:
        configured = os.getenv("RAG_LLAMA_SERVER_PATH", "").strip()
        if configured:
            resolved = resolve_config_path(configured)
            if os.path.exists(resolved):
                return resolved

        if self.llama_cpp_dir:
            server_path = os.path.join(self.llama_cpp_dir, "llama-server.exe")
            if os.path.exists(server_path):
                return server_path
        return ""

    def _resolve_model_path(self) -> str:
        configured = os.getenv("RAG_GGUF_MODEL_PATH", "").strip()
        if configured:
            resolved = resolve_config_path(configured)
            if os.path.exists(resolved):
                return resolved
            raise FileNotFoundError(f"Configured GGUF model path not found: {resolved}")

        if self.model_name.endswith(".gguf"):
            resolved = resolve_config_path(self.model_name)
            if os.path.exists(resolved):
                return resolved

        filename = os.getenv("RAG_GGUF_FILENAME", DEFAULT_RAG_GGUF_FILENAME).strip() or DEFAULT_RAG_GGUF_FILENAME
        repo_name = (self.model_name or DEFAULT_RAG_EMBEDDING_MODEL).replace("/", "--")
        patterns = [
            os.path.join(self.cache_folder, f"models--{repo_name}", "snapshots", "*", filename),
            os.path.join(self.cache_folder, "**", filename),
        ]
        for pattern in patterns:
            matches = sorted(glob(pattern, recursive=True))
            if matches:
                return matches[-1]

        raise FileNotFoundError(
            "Could not locate the GGUF embedding model. "
            "Download the model first or set RAG_GGUF_MODEL_PATH explicitly."
        )

    @staticmethod
    def _clean_texts(texts: Iterable[str]) -> List[str]:
        return [str(text or "").strip() for text in texts if str(text or "").strip()]

    def _prepare_query(self, query: str) -> str:
        return f"Instruct: {self.query_instruct}\nQuery:{query}"

    def _server_running(self) -> bool:
        if not self._port_open():
            return False
        try:
            self._post_embeddings(["ping"], timeout_s=15)
            return True
        except Exception:
            return False

    def _port_open(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            return sock.connect_ex((self.host, self.port)) == 0
        finally:
            sock.close()

    def _start_local_server(self) -> None:
        if not self.llama_server_path or not os.path.exists(self.llama_server_path):
            raise FileNotFoundError(
                "llama-server.exe not found. Set RAG_LLAMA_SERVER_PATH or place llama.cpp binaries under backend/Knowledge/llama_cpp."
            )

        args = [
            self.llama_server_path,
            "-m",
            self.model_path,
            "--embedding",
            "--pooling",
            self.pooling,
            "--host",
            self.host,
            "--port",
            str(self.port),
            "-c",
            str(self.context_size),
            "-ub",
            str(self.ubatch),
            "--no-warmup",
        ]
        if self.device != "cpu":
            args.extend(["-ngl", str(self.n_gpu_layers)])
        else:
            args.extend(["-ngl", "0"])

        log_dir = Path(self.llama_cpp_dir or os.path.dirname(self.llama_server_path) or os.path.dirname(__file__))
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "llama_server_runtime.out.log"
        stderr_path = log_dir / "llama_server_runtime.err.log"
        stdout_handle = open(stdout_path, "a", encoding="utf-8")
        stderr_handle = open(stderr_path, "a", encoding="utf-8")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(
            args,
            cwd=self.llama_cpp_dir or os.path.dirname(self.llama_server_path),
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )
        self._started_local_process = True

        deadline = time.time() + self.startup_timeout_s
        while time.time() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError("llama-server exited before it became ready.")
            try:
                self._post_embeddings(["ping"], timeout_s=15)
                return
            except Exception:
                time.sleep(2)
        raise TimeoutError("Timed out waiting for llama-server embedding endpoint to become ready.")

    def _ensure_server(self) -> None:
        if self._server_running():
            return
        self._start_local_server()

    def _post_embeddings(self, inputs: List[str], timeout_s: int | None = None) -> List[List[float]]:
        payload = json.dumps({"input": inputs, "model": self.model_label}).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_s or self.request_timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
        data = sorted(body.get("data", []), key=lambda item: int(item.get("index", 0)))
        return [self._normalize_vector(item.get("embedding", [])) for item in data]

    @staticmethod
    def _normalize_vector(values: List[float]) -> List[float]:
        if not values:
            return []
        norm = math.sqrt(sum(float(value) * float(value) for value in values))
        if norm <= 0:
            return [float(value) for value in values]
        return [float(value) / norm for value in values]

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        last_error = None
        for attempt in range(self.max_retries):
            try:
                self._ensure_server()
                return self._post_embeddings(texts)
            except Exception as exc:
                last_error = exc
                self.shutdown()
                time.sleep(min(2 * (attempt + 1), 8))

        if len(texts) > self.min_batch_size:
            midpoint = len(texts) // 2
            return self._embed_batch(texts[:midpoint]) + self._embed_batch(texts[midpoint:])

        raise RuntimeError(f"Embedding batch failed after retries: {last_error}")

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        cleaned = self._clean_texts(texts)
        if not cleaned:
            return []

        embeddings: List[List[float]] = []
        for start in range(0, len(cleaned), self.batch_size):
            batch = cleaned[start : start + self.batch_size]
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    def embed_queries(self, texts: Iterable[str]) -> List[List[float]]:
        cleaned = self._clean_texts(texts)
        if not cleaned:
            return []

        prepared = [self._prepare_query(text) for text in cleaned]
        embeddings: List[List[float]] = []
        for start in range(0, len(prepared), self.batch_size):
            batch = prepared[start : start + self.batch_size]
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    def shutdown(self) -> None:
        if self._process is None or not self._started_local_process:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        self._started_local_process = False


@lru_cache(maxsize=1)
def get_query_embedder() -> Qwen3EmbeddingFunction:
    return Qwen3EmbeddingFunction()
