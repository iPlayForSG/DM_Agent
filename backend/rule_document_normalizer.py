"""Normalize local rulebook text into a grep-friendly generated corpus."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping


SUPPORTED_SUFFIXES = {".md", ".txt"}
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _display_name(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").split())


def _markdown_table_column_count(line: str) -> int:
    stripped = str(line or "").strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return 0
    cells = re.split(r"(?<!\\)\|", stripped[1:-1])
    return len(cells)


def _split_inline_table_heading(raw_line: str) -> List[str]:
    if len(raw_line) <= 500 or raw_line.count("|") < 8:
        return [raw_line]
    pipe_index = raw_line.find("|")
    if pipe_index < 0:
        return [raw_line]
    prefix = raw_line[:pipe_index].strip()
    table = raw_line[pipe_index:].strip()
    if re.fullmatch(r"#{1,6}", prefix):
        return [table]
    if re.match(r"^#{1,6}\s+\S", prefix):
        return [prefix, table]
    return [raw_line]


def _quality_warnings(normalized: str, source_text: str) -> List[str]:
    warnings: List[str] = []
    if len(str(source_text or "").strip()) < 40:
        warnings.append("short-source")
    for line_number, line in enumerate(normalized.splitlines(), start=1):
        if len(line) > 1000 and line.count("|") >= 8:
            warnings.append(f"flattened-table-line:{line_number}")
    return warnings


def _contextual_title(relative: str, base_title: str, parent_depth: int) -> str:
    path = Path(relative)
    parents = [_display_name(part) for part in path.parent.parts[-parent_depth:]]
    components = [part for part in parents + [base_title] if part]
    deduplicated: List[str] = []
    for component in components:
        if not deduplicated or deduplicated[-1].casefold() != component.casefold():
            deduplicated.append(component)
    return " — ".join(deduplicated)


def _disambiguate_default_titles(specs: List[Dict[str, Any]]) -> None:
    title_counts = Counter(str(spec["title"]).casefold() for spec in specs)
    duplicate_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    occupied = {
        str(spec["title"]).casefold()
        for spec in specs
        if title_counts[str(spec["title"]).casefold()] == 1
    }
    for spec in specs:
        key = str(spec["title"]).casefold()
        if title_counts[key] > 1:
            duplicate_groups[key].append(spec)

    for key in sorted(duplicate_groups):
        group = duplicate_groups[key]
        max_depth = max(len(Path(str(spec["relative"])).parent.parts) for spec in group)
        for depth in range(1, max_depth + 1):
            candidates = [
                str(spec["title"])
                if spec["explicit_title"]
                else _contextual_title(str(spec["relative"]), str(spec["title"]), depth)
                for spec in group
            ]
            folded = [candidate.casefold() for candidate in candidates]
            if len(set(folded)) != len(folded) or any(candidate in occupied for candidate in folded):
                continue
            for spec, candidate in zip(group, candidates):
                if not spec["explicit_title"]:
                    spec["title"] = candidate
            occupied.update(folded)
            break


def normalize_rule_text(text: str, title: str, source: str, aliases: List[str] | None = None) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or "")).lstrip("\ufeff")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    blank_count = 0
    raw_lines = [
        logical_line
        for raw_line in normalized.split("\n")
        for logical_line in _split_inline_table_heading(raw_line)
    ]
    for raw_line in raw_lines:
        line = raw_line.rstrip()
        line = re.sub(r"^(#{1,6})\s*", lambda match: f"{match.group(1)} ", line)
        line = re.sub(r"^\s*[•●]\s+", "- ", line)
        if TABLE_SEPARATOR_RE.fullmatch(line) and lines:
            header_columns = _markdown_table_column_count(lines[-1])
            separator_columns = _markdown_table_column_count(line)
            if header_columns and header_columns != separator_columns:
                # 原始规则书保持只读；只在可由紧邻表头确定列数时修复生成副本。
                line = "| " + " | ".join("---" for _ in range(header_columns)) + " |"
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


def load_overrides(path: Path) -> Dict[str, Mapping[str, Dict[str, Any]]]:
    if not path.exists():
        return {"documents": {}, "directories": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"documents": {}, "directories": {}}
    documents = payload.get("documents", {})
    directories = payload.get("directories", {})
    return {
        "documents": documents if isinstance(documents, dict) else {},
        "directories": directories if isinstance(directories, dict) else {},
    }


def _clean_aliases(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    aliases: List[str] = []
    seen = set()
    for raw_alias in value:
        alias = " ".join(str(raw_alias or "").split())
        folded = alias.casefold()
        if alias and folded not in seen:
            aliases.append(alias)
            seen.add(folded)
    return aliases


def _aliases_for_document(
    relative: str,
    document_override: Mapping[str, Any],
    directory_overrides: Mapping[str, Dict[str, Any]],
) -> List[str]:
    aliases: List[str] = []
    path = Path(relative)
    parent_parts = path.parent.parts
    for depth in range(1, len(parent_parts) + 1):
        directory = Path(*parent_parts[:depth]).as_posix()
        override = directory_overrides.get(directory, {})
        if isinstance(override, dict):
            aliases.extend(_clean_aliases(override.get("aliases", [])))
    aliases.extend(_clean_aliases(document_override.get("aliases", [])))
    return _clean_aliases(aliases)


def normalize_corpus(source_root: Path, output_root: Path, overrides_path: Path) -> Dict[str, Any]:
    source_root = source_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    override_config = load_overrides(overrides_path)
    document_overrides = override_config["documents"]
    directory_overrides = override_config["directories"]
    files = sorted(
        (
            path
            for path in source_root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ),
        key=lambda path: path.relative_to(source_root).as_posix().casefold(),
    ) if source_root.exists() else []

    specs: List[Dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(source_root).as_posix()
        override = (
            document_overrides.get(relative, {})
            if isinstance(document_overrides.get(relative, {}), dict)
            else {}
        )
        explicit_title = bool(str(override.get("title") or "").strip())
        specs.append(
            {
                "path": path,
                "relative": relative,
                "override": override,
                "explicit_title": explicit_title,
                "title": str(override.get("title") or _display_name(path.stem)).strip(),
            }
        )
    # 文件名在大型语料中经常重复；最短父目录上下文既能消歧，也避免所有标题都变成长路径。
    _disambiguate_default_titles(specs)

    manifest_entries = []
    expected_outputs = set()
    for spec in specs:
        path = spec["path"]
        relative = str(spec["relative"])
        override = spec["override"]
        title = str(spec["title"])
        aliases = _aliases_for_document(relative, override, directory_overrides)
        output_relative = Path(relative).with_suffix(".md")
        output_path = output_root / output_relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        source_text = path.read_text(encoding="utf-8", errors="replace")
        normalized = normalize_rule_text(
            source_text,
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
                "quality_warnings": _quality_warnings(normalized, source_text),
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

    warning_counts = Counter(
        warning.split(":", 1)[0]
        for item in manifest_entries
        for warning in item["quality_warnings"]
    )
    manifest = {
        "schema_version": 1,
        "source_root": source_root.as_posix(),
        "document_count": len(manifest_entries),
        "quality_warning_counts": dict(sorted(warning_counts.items())),
        "documents": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
