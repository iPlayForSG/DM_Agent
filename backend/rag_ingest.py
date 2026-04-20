"""Build the local D&D 2024 RAG vector store with Qwen3 embeddings."""

import argparse
import hashlib
import json
import os
import site
import sys
from dataclasses import dataclass
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


def build_chunks(source_root: str, chunk_size: int, overlap: int, limit: int = 0) -> List[RagChunk]:
    files = iter_source_files(source_root)
    if limit > 0:
        files = files[:limit]

    chunks: List[RagChunk] = []
    for index, path in enumerate(files, start=1):
        file_chunks = chunk_markdown_file(path, source_root, chunk_size=chunk_size, overlap=overlap)
        chunks.extend(file_chunks)
        if index % 100 == 0:
            print(f"Chunked {index}/{len(files)} files, {len(chunks)} chunks...")
    return chunks


def write_manifest(db_path: str, payload: Dict[str, object]) -> None:
    manifest_path = Path(db_path) / "rag_manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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

    chunks = build_chunks(
        source_root=source_root,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        limit=args.limit,
    )
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

    embedder = Qwen3EmbeddingFunction(model_name=model_name, batch_size=args.embed_batch_size)
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

    total_batches = (len(chunks) + args.upsert_batch_size - 1) // args.upsert_batch_size
    for batch_index, start in enumerate(range(0, len(chunks), args.upsert_batch_size), start=1):
        batch = chunks[start : start + args.upsert_batch_size]
        embeddings = embedder.embed_documents(chunk.text for chunk in batch)
        collection.upsert(
            ids=[chunk.chunk_id for chunk in batch],
            documents=[chunk.text for chunk in batch],
            metadatas=[chunk.metadata for chunk in batch],
            embeddings=embeddings,
        )
        print(f"Upserted batch {batch_index}/{total_batches} ({start + len(batch)}/{len(chunks)} chunks).")

    write_manifest(
        db_path,
        {
            "collection": name,
            "embedding_model": model_name,
            "source_root": source_root,
            "chunk_count": len(chunks),
            "chunk_size": args.chunk_size,
            "overlap": args.overlap,
            "source_file_count": len(iter_source_files(source_root)),
        },
    )
    print("RAG ingestion complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the local D&D 2024 RAG index.")
    parser.add_argument("--source-root", default="", help="Directory containing D&D markdown documents.")
    parser.add_argument("--db-path", default="", help="Persistent Chroma database path.")
    parser.add_argument("--collection", default="", help="Chroma collection name.")
    parser.add_argument("--model", default="", help="SentenceTransformer embedding model.")
    parser.add_argument("--chunk-size", type=int, default=int(os.getenv("RAG_CHUNK_SIZE", "1800")))
    parser.add_argument("--overlap", type=int, default=int(os.getenv("RAG_CHUNK_OVERLAP", "240")))
    parser.add_argument("--embed-batch-size", type=int, default=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "4")))
    parser.add_argument("--upsert-batch-size", type=int, default=int(os.getenv("RAG_UPSERT_BATCH_SIZE", "32")))
    parser.add_argument("--limit", type=int, default=0, help="Only ingest the first N files for smoke testing.")
    parser.add_argument("--reset", action="store_true", help="Delete the target collection before ingestion.")
    parser.add_argument("--dry-run", action="store_true", help="Only chunk source files; do not load embeddings or write Chroma.")
    return parser.parse_args()


if __name__ == "__main__":
    ingest(parse_args())
