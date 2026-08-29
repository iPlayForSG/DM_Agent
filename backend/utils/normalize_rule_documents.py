"""Command-line entry point for the local rulebook normalization pipeline."""

import argparse
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from rule_document_normalizer import normalize_corpus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize local D&D rule documents for lexical lookup.")
    parser.add_argument(
        "--source",
        type=Path,
        default=BACKEND_ROOT / "Documents" / "DND5e 2024",
        help="Source directory containing Markdown or text rulebooks.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND_ROOT / "Knowledge" / "grep_corpus",
        help="Generated normalized corpus directory.",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=BACKEND_ROOT / "rule_document_overrides.json",
        help="Tracked title and search-alias overrides.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = normalize_corpus(args.source, args.output, args.overrides)
    print(json.dumps({
        "document_count": manifest["document_count"],
        "output": str(args.output.resolve()),
        "manifest": str((args.output / "manifest.json").resolve()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
