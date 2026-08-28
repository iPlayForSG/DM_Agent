"""Normalize local rulebook text into a grep-friendly generated corpus."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Mapping


SUPPORTED_SUFFIXES = {".md", ".txt"}


def normalize_rule_text(text: str, title: str, source: str, aliases: List[str] | None = None) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lstrip("\ufeff")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    blank_count = 0
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip()
        line = re.sub(r"^(#{1,6})\s*", lambda match: f"{match.group(1)} ", line)
        line = re.sub(r"^\s*[•●]\s+", "- ", line)
        if not line.strip():
            blank_count += 1
            if blank_count > 1:
                continue
            lines.append("")
        else:
            blank_count = 0
            lines.append(line)
    body = "\n".join(lines).strip()

    header = [f"# {title.strip()}", "", f"> Source: {source}"]
    cleaned_aliases = [" ".join(str(alias or "").split()) for alias in aliases or []]
    cleaned_aliases = [alias for alias in cleaned_aliases if alias]
    if cleaned_aliases:
        header.append(f"> Search aliases: {', '.join(cleaned_aliases)}")
    if re.match(r"^#\s+", body):
        body = re.sub(r"^#\s+.*?(?:\n+|$)", "", body, count=1).strip()
    return "\n".join(header).rstrip() + (f"\n\n{body}" if body else "") + "\n"


def load_overrides(path: Path) -> Mapping[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    documents = payload.get("documents", {}) if isinstance(payload, dict) else {}
    return documents if isinstance(documents, dict) else {}


def normalize_corpus(source_root: Path, output_root: Path, overrides_path: Path) -> Dict[str, Any]:
    source_root = source_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    overrides = load_overrides(overrides_path)
    files = sorted(
        (
            path
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ),
        key=lambda path: path.relative_to(source_root).as_posix().casefold(),
    ) if source_root.exists() else []

    manifest_entries = []
    expected_outputs = set()
    for path in files:
        relative = path.relative_to(source_root).as_posix()
        override = overrides.get(relative, {}) if isinstance(overrides.get(relative, {}), dict) else {}
        title = str(override.get("title") or path.stem.replace("_", " ").replace("-", " ")).strip()
        aliases = override.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []
        output_relative = Path(relative).with_suffix(".md")
        output_path = output_root / output_relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = normalize_rule_text(
            path.read_text(encoding="utf-8", errors="replace"),
            title=title,
            source=relative,
            aliases=aliases,
        )
        output_path.write_text(normalized, encoding="utf-8", newline="\n")
        expected_outputs.add(output_relative.as_posix())
        headings = [
            match.group(2).strip()
            for line in normalized.splitlines()
            if (match := re.match(r"^(#{1,6})\s+(.+)$", line))
        ]
        manifest_entries.append(
            {
                "source": relative,
                "output": output_relative.as_posix(),
                "title": title,
                "aliases": aliases,
                "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "headings": headings,
            }
        )

    manifest_path = output_root / "manifest.json"
    previous_outputs = set()
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_outputs = {
                str(item.get("output") or "")
                for item in previous.get("documents", [])
                if isinstance(item, dict)
            }
        except (json.JSONDecodeError, OSError):
            previous_outputs = set()
    for stale_relative in sorted(previous_outputs - expected_outputs):
        stale_path = output_root / stale_relative
        # 只清理由上一版 manifest 明确声明的生成文件，避免误删本地人工资料。
        if stale_path.is_file() and output_root in stale_path.resolve().parents:
            stale_path.unlink()

    manifest = {
        "schema_version": 1,
        "source_root": source_root.as_posix(),
        "document_count": len(manifest_entries),
        "documents": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
