"""Build the local D&D 2024 RAG vector store with Qwen3 GGUF embeddings."""

import argparse
import hashlib
import json
import os
import site
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

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

import chromadb
from dotenv import load_dotenv

from rag_embeddings import DEFAULT_RAG_COLLECTION, DEFAULT_RAG_EMBEDDING_MODEL, Qwen3EmbeddingFunction

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)

SUPPORTED_SUFFIXES = {".md", ".txt"}
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 80
DEFAULT_CPU_CHUNK_LIMIT = 32


@dataclass
class RagChunk:
    chunk_id: str
    text: str
    metadata: Dict[str, str | int]


def resolve_vector_db_path() -> str:
    explicit_path = os.getenv("RAG_VECTOR_DB_PATH", "").strip()
    if explicit_path:
        return resolve_config_path(explicit_path)
    return os.path.join(os.path.dirname(__file__), "Knowledge", "vector_db")


def resolve_source_root() -> str:
    explicit_path = os.getenv("RAG_SOURCE_ROOT", "").strip()
    if explicit_path:
        return resolve_config_path(explicit_path)
    return os.path.join(os.path.dirname(__file__), "Documents", "DND5e 2024")


def resolve_config_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(__file__), path)


def collection_name() -> str:
    return os.getenv("RAG_COLLECTION_NAME", DEFAULT_RAG_COLLECTION).strip() or DEFAULT_RAG_COLLECTION


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def iter_source_files(source_root: str) -> List[Path]:
    root = Path(source_root)
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return sorted(files, key=lambda item: str(item.relative_to(root)).lower())


def split_paragraphs_with_overlap(paragraphs: Iterable[str], chunk_size: int, overlap: int) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        chunks.append("\n\n".join(current).strip())
        if overlap <= 0:
            current = []
        else:
            overlap_parts: List[str] = []
            overlap_len = 0
            for part in reversed(current):
                if overlap_len + len(part) > overlap and overlap_parts:
                    break
                overlap_parts.insert(0, part)
                overlap_len += len(part) + 2
            current = overlap_parts
        current_len = sum(len(part) + 2 for part in current)

    for raw_para in paragraphs:
        para = raw_para.strip()
        if not para:
            continue
        if len(para) > chunk_size:
            flush()
            step = max(1, chunk_size - overlap)
            for start in range(0, len(para), step):
                piece = para[start : start + chunk_size].strip()
                if piece:
                    chunks.append(piece)
            current = []
            current_len = 0
            continue
        projected = current_len + len(para) + 2
        if current and projected > chunk_size:
            flush()
        current.append(para)
        current_len += len(para) + 2

    flush()
    return [chunk for chunk in chunks if chunk]


def chunk_markdown_file(path: Path, source_root: str, chunk_size: int, overlap: int) -> List[RagChunk]:
    root = Path(source_root)
    rel_path = str(path.relative_to(root)).replace("\\", "/")
    content = normalize_text(path.read_text(encoding="utf-8", errors="replace"))
    if not content:
        return []

    heading_stack: List[str] = []
    section_lines: List[str] = []
    section_heading = ""
    section_start_line = 1
    chunks: List[RagChunk] = []

    def flush_section(end_line: int) -> None:
        nonlocal section_lines, section_heading, section_start_line
        section_text = normalize_text("\n".join(section_lines))
        if not section_text:
            section_lines = []
            return
        heading_prefix = " > ".join(heading_stack) or section_heading
        paragraphs = section_text.split("\n\n")
        section_chunks = split_paragraphs_with_overlap(paragraphs, chunk_size=chunk_size, overlap=overlap)
        for local_index, chunk_text in enumerate(section_chunks):
            enriched_text = (
                f"Source: {rel_path}\n"
                f"Headings: {heading_prefix or '(root)'}\n\n"
                f"{chunk_text}"
            ).strip()
            stable = f"{rel_path}:{section_start_line}:{end_line}:{local_index}:{chunk_text[:96]}"
            chunk_hash = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
            chunks.append(
                RagChunk(
                    chunk_id=f"{rel_path}:{chunk_hash}".replace("/", "::"),
                    text=enriched_text,
                    metadata={
                        "source": rel_path,
                        "heading": heading_prefix,
                        "chunk_index": len(chunks),
                        "section_chunk_index": local_index,
                        "start_line": section_start_line,
                        "end_line": end_line,
                    },
                )
            )
        section_lines = []

    for line_number, line in enumerate(content.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= level <= 6 and stripped[level : level + 1] == " ":
                flush_section(line_number - 1)
                heading = stripped[level:].strip()
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(heading)
                section_heading = " > ".join(heading_stack)
                section_start_line = line_number
        section_lines.append(line)

    flush_section(len(content.split("\n")))
    return chunks


def build_chunks(
    source_root: str,
    chunk_size: int,
    overlap: int,
    limit: int = 0,
    max_chunks: int = 0,
) -> List[RagChunk]:
    files = iter_source_files(source_root)
    if limit > 0:
        files = files[:limit]

    chunks: List[RagChunk] = []
    for index, path in enumerate(files, start=1):
        file_chunks = chunk_markdown_file(path, source_root, chunk_size=chunk_size, overlap=overlap)
        chunks.extend(file_chunks)
        if index % 100 == 0:
            print(f"Chunked {index}/{len(files)} files, {len(chunks)} chunks...")
        if max_chunks > 0 and len(chunks) >= max_chunks:
            return chunks[:max_chunks]
    return chunks


def write_manifest(db_path: str, payload: Dict[str, object]) -> None:
    manifest_path = Path(db_path) / "rag_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def existing_ids(collection, ids: List[str]) -> set[str]:
    try:
        payload = collection.get(ids=ids, include=[])
    except Exception:
        payload = collection.get(ids=ids)
    return set(payload.get("ids", []))


def cuda_available() -> bool:
    if not shutil.which("nvidia-smi"):
        return False
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())


def enforce_cpu_guard(args: argparse.Namespace, chunk_count: int) -> None:
    requested_device = (args.device or os.getenv("RAG_EMBEDDING_DEVICE", "")).strip().lower()
    if requested_device in {"cuda", "gpu"}:
        return
    if cuda_available():
        return
    if args.allow_slow_cpu or os.getenv("RAG_ALLOW_SLOW_CPU", "").lower() in {"1", "true", "yes"}:
        return
    if chunk_count <= args.cpu_chunk_limit:
        return
    raise RuntimeError(
        "Qwen3-Embedding-4B-GGUF is running without CUDA acceleration and the requested ingestion is too large. "
        f"Chunk count: {chunk_count}. Set RAG_EMBEDDING_DEVICE=cuda on a CUDA machine, "
        "use --max-chunks for a smoke test, or pass --allow-slow-cpu if you intentionally "
        "want a very long CPU run."
    )


def ingest(args: argparse.Namespace) -> None:
    source_root = args.source_root or resolve_source_root()
    db_path = args.db_path or resolve_vector_db_path()
    model_name = args.model or os.getenv("RAG_EMBEDDING_MODEL", DEFAULT_RAG_EMBEDDING_MODEL)
    name = args.collection or collection_name()

    if not os.path.exists(source_root):
        raise FileNotFoundError(f"RAG source root not found: {source_root}")

    os.makedirs(db_path, exist_ok=True)
    print(f"RAG source root: {source_root}")
    print(f"Vector DB path: {db_path}")
    print(f"Collection: {name}")
    print(f"Embedding model: {model_name}")
    print(f"Chunk size / overlap: {args.chunk_size} / {args.overlap}")

    all_chunks = build_chunks(
        source_root=source_root,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        limit=args.limit,
        max_chunks=args.max_chunks,
    )
    full_chunk_count = len(all_chunks)
    start_chunk = max(0, int(args.start_chunk or 0))
    chunks = all_chunks[start_chunk:] if start_chunk > 0 else all_chunks
    if start_chunk > 0:
        print(f"Resuming from chunk offset: {start_chunk}")
    print(f"Generated {len(chunks)} chunks.")
    if not chunks:
        raise RuntimeError("No chunks generated from the source documents.")
    if args.dry_run:
        sample = chunks[0]
        print("Dry run complete. No embedding model was loaded and no vector DB writes were made.")
        print(
            "Sample chunk: "
            f"id={sample.chunk_id}, source={sample.metadata.get('source')}, "
            f"heading={sample.metadata.get('heading')}, chars={len(sample.text)}"
        )
        return

    enforce_cpu_guard(args, len(chunks))
    source_file_count = len(iter_source_files(source_root))
    embedder = Qwen3EmbeddingFunction(model_name=model_name, batch_size=args.embed_batch_size, device=args.device)
    client = chromadb.PersistentClient(path=db_path)
    if args.reset:
        try:
            client.delete_collection(name=name)
            print(f"Deleted existing collection: {name}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=name,
        metadata={
            "embedding_model": model_name,
            "source_root": source_root,
            "chunk_size": args.chunk_size,
            "overlap": args.overlap,
        },
    )

    resume_enabled = not args.reset and not args.no_resume
    if resume_enabled:
        print("Resume mode: existing chunk ids in the target collection will be skipped.")

    manifest_base = {
        "collection": name,
        "embedding_model": model_name,
        "source_root": source_root,
        "chunk_count": len(chunks),
        "full_chunk_count": full_chunk_count,
        "remaining_chunk_count": len(chunks),
        "chunk_size": args.chunk_size,
        "overlap": args.overlap,
        "source_file_count": source_file_count,
        "start_chunk": start_chunk,
        "embed_batch_size": args.embed_batch_size,
        "upsert_batch_size": args.upsert_batch_size,
        "embedding_device": args.device or os.getenv("RAG_EMBEDDING_DEVICE", "") or "auto",
        "started_at": now_utc(),
    }
    embedded_count = 0
    skipped_count = 0
    write_manifest(
        db_path,
        {
            **manifest_base,
            "status": "running",
            "embedded_chunk_count": embedded_count,
            "skipped_chunk_count": skipped_count,
            "updated_at": now_utc(),
        },
    )

    total_batches = (len(chunks) + args.upsert_batch_size - 1) // args.upsert_batch_size
    for batch_index, start in enumerate(range(0, len(chunks), args.upsert_batch_size), start=1):
        batch = chunks[start : start + args.upsert_batch_size]
        batch_ids = [chunk.chunk_id for chunk in batch]
        if resume_enabled:
            present_ids = existing_ids(collection, batch_ids)
            batch = [chunk for chunk in batch if chunk.chunk_id not in present_ids]
            skipped_count += len(present_ids)
        if not batch:
            print(f"Skipped batch {batch_index}/{total_batches} ({start + len(batch_ids)}/{len(chunks)} chunks already present).")
            continue

        embeddings = embedder.embed_documents(chunk.text for chunk in batch)
        collection.upsert(
            ids=[chunk.chunk_id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[chunk.metadata for chunk in batch],
            embeddings=embeddings,
        )
        embedded_count += len(batch)
        print(
            f"Upserted batch {batch_index}/{total_batches} "
            f"({min(start + len(batch_ids), len(chunks))}/{len(chunks)} chunks, "
            f"embedded={embedded_count}, skipped={skipped_count})."
        )
        write_manifest(
            db_path,
            {
                **manifest_base,
                "status": "running",
                "embedded_chunk_count": embedded_count,
                "skipped_chunk_count": skipped_count,
                "updated_at": now_utc(),
            },
        )

    write_manifest(
        db_path,
        {
            **manifest_base,
            "status": "complete",
            "embedded_chunk_count": embedded_count,
            "skipped_chunk_count": skipped_count,
            "completed_at": now_utc(),
            "updated_at": now_utc(),
        },
    )
    print("RAG ingestion complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local D&D 2024 RAG index with GGUF embeddings.")
    parser.add_argument("--source-root", default="", help="Directory containing D&D markdown documents.")
    parser.add_argument("--db-path", default="", help="Persistent Chroma database path.")
    parser.add_argument("--collection", default="", help="Chroma collection name.")
    parser.add_argument("--model", default="", help="GGUF model path or model repo identifier.")
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("RAG_CHUNK_SIZE", str(DEFAULT_CHUNK_SIZE))))
    parser.add_argument("--overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", str(DEFAULT_CHUNK_OVERLAP))))
    parser.add_argument("--device", default=os.getenv("RAG_EMBEDDING_DEVICE", ""), help="Embedding device hint for llama.cpp, for example cuda or cpu.")
    parser.add_argument("--embed-batch-size", type=int, default=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "32")))
    parser.add_argument("--upsert-batch-size", type=int, default=int(os.getenv("RAG_UPSERT_BATCH_SIZE", "32")))
    parser.add_argument("--limit", type=int, default=0, help="Only ingest the first N files for smoke testing.")
    parser.add_argument("--max-chunks", type=int, default=0, help="Only ingest the first N generated chunks for smoke testing.")
    parser.add_argument("--start-chunk", type=int, default=0, help="Skip the first N generated chunks before embedding.")
    parser.add_argument("--cpu-chunk-limit", type=int, default=int(os.getenv("RAG_CPU_CHUNK_LIMIT", str(DEFAULT_CPU_CHUNK_LIMIT))))
    parser.add_argument("--allow-slow-cpu", action="store_true", help="Allow large Qwen3 GGUF ingestion on CPU.")
    parser.add_argument("--reset", action="store_true", help="Delete the target collection before ingestion.")
    parser.add_argument("--no-resume", action="store_true", help="Re-embed existing chunk ids instead of skipping them.")
    parser.add_argument("--dry-run", action="store_true", help="Only chunk source files; do not load embeddings or write Chroma.")
    return parser.parse_args()


if __name__ == "__main__":
    ingest(parse_args())
