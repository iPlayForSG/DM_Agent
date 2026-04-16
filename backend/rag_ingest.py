"""Offline ingestion script for building the local rulebook vector store."""

import os
import glob
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=env_path, override=True)


def resolve_vector_db_path() -> str:
    explicit_path = os.getenv("RAG_VECTOR_DB_PATH", "").strip()
    if explicit_path:
        return explicit_path
    return os.path.join(os.path.dirname(__file__), "Knowledge", "vector_db")

def split_text(text: str, chunk_size: int = 800, overlap: int = 100):
    """
    Simple text splitter that respects paragraphs but limits chunk size.
    """
    chunks = []
    current_chunk = []
    current_length = 0

    paragraphs = text.split('\n\n')

    for para in paragraphs:
        if len(para.strip()) == 0:
            continue

        para_len = len(para)

        # Very long paragraphs are split bluntly so ingestion never stalls.
        if para_len > chunk_size:
            # Flush the accumulated chunk before hard-splitting the long paragraph.
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_length = 0

            # The overlap is only approximate here; ingestion quality matters more than perfect windowing.
            for k in range(0, para_len, chunk_size - overlap):
                chunks.append(para[k : k + chunk_size])
            continue

        # Start a new chunk when adding one more paragraph would overflow the budget.
        if current_length + para_len + 2 > chunk_size:
            chunks.append("\n\n".join(current_chunk))

            # This simplified splitter resets instead of carrying paragraph overlap.
            current_chunk = [para]
            current_length = para_len
        else:
            current_chunk.append(para)
            current_length += para_len + 2 # +2 for newlines

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks

def ingest():
    print("Initializing RAG Ingestion...")

    # Keep ingestion output aligned with the runtime retrieval path.
    db_path = resolve_vector_db_path()
    if not os.path.exists(db_path):
        os.makedirs(db_path)

    client = chromadb.PersistentClient(path=db_path)

    # Use local embeddings so ingestion does not depend on a remote embedding API.
    print("Using Local ONNX Embeddings (all-MiniLM-L6-v2)...")
    embedding_func = embedding_functions.DefaultEmbeddingFunction()

    # Reuse the same collection name that the runtime retrieval layer expects.
    collection = client.get_or_create_collection(name="dnd_rules", embedding_function=embedding_func)

    # Ingest the preprocessed markdown export instead of the raw HTML backup.
    root_dir = os.path.join(os.path.dirname(__file__), "Knowledge", "dnd_md_output")
    files = glob.glob(os.path.join(root_dir, "**", "*.md"), recursive=True)

    print(f"Found {len(files)} markdown files in {root_dir}")

    documents = []
    metadatas = []
    ids = []

    count = 0
    for i, file_path in enumerate(files):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            chunks = split_text(content)
            rel_path = os.path.relpath(file_path, root_dir)

            for j, chunk in enumerate(chunks):
                if not chunk.strip(): continue

                documents.append(chunk)
                metadatas.append({"source": rel_path, "chunk_index": j})
                # Chroma ids must be unique and filesystem-safe.
                safe_id = f"{rel_path}_{j}".replace("\\", "_").replace(" ", "_")
                ids.append(safe_id)
                count += 1

        except Exception as e:
            print(f"Skipping file {file_path}: {e}")

    print(f"Generated {len(documents)} text chunks.")

    # Batch writes keep Chroma ingestion predictable on large source sets.
    batch_size = 100
    total_batches = (len(documents) + batch_size - 1) // batch_size

    for i in range(0, len(documents), batch_size):
        end = min(i + batch_size, len(documents))
        print(f"Upserting batch {i//batch_size + 1}/{total_batches}...")

        collection.upsert(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=ids[i:end]
        )

    print(f"Ingestion Complete. Data saved to {db_path}")

if __name__ == "__main__":
    ingest()
