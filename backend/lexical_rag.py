"""Deterministic rules lookup used when vector embeddings are unavailable."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


SUPPORTED_RULE_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class LexicalChunk:
    source: str
    chunk_index: int
    heading: str
    start_line: int
    end_line: int
    content: str
    aliases: str
    searchable: str


def lexical_terms(text: str) -> List[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    terms: List[str] = []
    seen = set()
    for token in re.findall(r"[a-z0-9_+\-]{2,}|[\u4e00-\u9fff]+", normalized):
        candidates = [token]
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            candidates.extend(token[index : index + 2] for index in range(len(token) - 1))
        for candidate in candidates:
            if candidate in {"2024", "rules", "rule", "规则"} or candidate in seen:
                continue
            seen.add(candidate)
            terms.append(candidate)
            if len(terms) >= 48:
                return terms
    return terms


class LexicalRuleIndex:
    """Build a small heading-aware in-memory index over Markdown/text rulebooks."""

    def __init__(self, source_roots: Sequence[Path], max_chunk_chars: int = 2400) -> None:
        self.source_roots = [Path(root) for root in source_roots]
        self.max_chunk_chars = max(400, int(max_chunk_chars))
        self.active_root: Path | None = None
        self.chunks: List[LexicalChunk] = []
        self.document_count = 0
        self.last_error = ""

    def refresh(self) -> bool:
        self.active_root = None
        self.chunks = []
        self.document_count = 0
        self.last_error = ""
        for root in self.source_roots:
            files = self._source_files(root)
            if not files:
                continue
            self.active_root = root
            self.document_count = len(files)
            for path in files:
                self.chunks.extend(self._chunk_file(path, root))
            if self.chunks:
                return True
        self.last_error = "No normalized or raw Markdown/text rule documents were found."
        return False

    def search(self, queries: Sequence[str], limit: int) -> List[Dict[str, Any]]:
        if not self.chunks and not self.refresh():
            return []
        normalized_queries = [unicodedata.normalize("NFKC", str(query or "")).casefold().strip() for query in queries]
        terms = lexical_terms(" ".join(normalized_queries))
        if not terms:
            return []

        scored: List[tuple[int, LexicalChunk]] = []
        for chunk in self.chunks:
            source = chunk.source.casefold()
            heading = chunk.heading.casefold()
            aliases = chunk.aliases
            content = chunk.searchable
            score = 0
            for query in normalized_queries:
                if query and query in content:
                    score += 16
            for term in terms:
                if term in aliases:
                    score += 9
                if term in heading:
                    score += 7
                if term in source:
                    score += 5
                occurrences = content.count(term)
                score += min(occurrences, 4) * 2
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].source, item[1].chunk_index))
        return [
            {
                "source": chunk.source,
                "chunk_index": str(chunk.chunk_index),
                "heading": chunk.heading,
                "start_line": str(chunk.start_line),
                "end_line": str(chunk.end_line),
                "distance": "",
                "content": chunk.content,
                "_lexical_score": score,
                "_distance_value": float("inf"),
            }
            for score, chunk in scored[: max(1, limit)]
        ]

    @staticmethod
    def _source_files(root: Path) -> List[Path]:
        if not root.exists():
            return []
        return sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_RULE_SUFFIXES
            ),
            key=lambda path: path.relative_to(root).as_posix().casefold(),
        )

    def _chunk_file(self, path: Path, root: Path) -> List[LexicalChunk]:
        text = unicodedata.normalize("NFKC", path.read_text(encoding="utf-8", errors="replace"))
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines()
        source = path.relative_to(root).as_posix()
        document_aliases = " ".join(
            match.group(1).strip()
            for line in lines
            if (match := re.match(r"^>\s*Search aliases:\s*(.+?)\s*$", line, re.IGNORECASE))
        )
        normalized_aliases = unicodedata.normalize("NFKC", document_aliases).casefold()
        heading_stack: List[str] = []
        chunks: List[LexicalChunk] = []
        buffer: List[str] = []
        start_line = 1

        def flush(end_line: int) -> None:
            nonlocal buffer, start_line
            content = "\n".join(buffer).strip()
            if content:
                for part_start, part in self._split_content(content):
                    chunk_index = len(chunks)
                    part_line_count = max(1, part.count("\n") + 1)
                    chunks.append(
                        LexicalChunk(
                            source=source,
                            chunk_index=chunk_index,
                            heading=" > ".join(heading_stack),
                            start_line=start_line + part_start,
                            end_line=min(end_line, start_line + part_start + part_line_count - 1),
                            content=part,
                            aliases=normalized_aliases,
                            searchable=unicodedata.normalize(
                                "NFKC",
                                f"{source}\n{' > '.join(heading_stack)}\n{document_aliases}\n{part}",
                            ).casefold(),
                        )
                    )
            buffer = []

        for line_number, line in enumerate(lines, start=1):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                flush(line_number - 1)
                level = len(match.group(1))
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(match.group(2).strip())
                start_line = line_number
            elif not buffer:
                start_line = line_number
            buffer.append(line.rstrip())
        flush(len(lines))
        return chunks

    def _split_content(self, content: str) -> Iterable[tuple[int, str]]:
        if len(content) <= self.max_chunk_chars:
            yield 0, content
            return
        lines = content.splitlines()
        current: List[str] = []
        current_chars = 0
        part_start = 0
        for line_index, line in enumerate(lines):
            projected = current_chars + len(line) + 1
            if current and projected > self.max_chunk_chars:
                yield part_start, "\n".join(current).strip()
                current = []
                current_chars = 0
                part_start = line_index
            current.append(line)
            current_chars += len(line) + 1
        if current:
            yield part_start, "\n".join(current).strip()
