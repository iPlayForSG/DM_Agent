"""Derived campaign memory for compact prompt injection."""

from __future__ import annotations

from typing import Iterable, List

from library import Library
from models import Character, EvidenceRecord, GameState, SearchRecord


class CampaignMemoryCompiler:
    """Builds a concise memory block from authoritative GameState fields."""

    def __init__(
        self,
        *,
        max_completed_chapters: int = 6,
        max_evidence: int = 10,
        max_searches: int = 8,
        max_experiences_per_character: int = 4,
        max_log_entries: int = 6,
        max_chars: int = 3600,
    ) -> None:
        self.max_completed_chapters = max_completed_chapters
        self.max_evidence = max_evidence
        self.max_searches = max_searches
        self.max_experiences_per_character = max_experiences_per_character
        self.max_log_entries = max_log_entries
        self.max_chars = max_chars
        self.library = Library()

    def compile(self, state: GameState) -> str:
        sections: List[str] = []
        self._add_chapter_memory(sections, state)
        self._add_evidence_memory(sections, state.evidence_records[-self.max_evidence :])
        self._add_search_memory(sections, state.search_records[-self.max_searches :])
        self._add_character_memory(sections, state.characters.values())
        self._add_log_memory(sections, state.adventure_log[-self.max_log_entries :])

        if not sections:
            return "No durable campaign memory has been recorded yet."
        return self._truncate("\n".join(sections), self.max_chars)

    def _add_chapter_memory(self, sections: List[str], state: GameState) -> None:
        lines: List[str] = []
        selected = state.campaign.selected_adventure()
        if selected:
            lines.append(f"- Adventure: {self._clean(selected.title)} | {self._clean(selected.summary)}")
        if state.campaign.current_chapter_title:
            lines.append(
                f"- Current: {state.campaign.current_chapter_number or '?'} - "
                f"{self._clean(state.campaign.current_chapter_title)} | "
                f"{self._clean(state.campaign.current_chapter_summary)}"
            )
        completed = state.campaign.completed_chapters[-self.max_completed_chapters :]
        for chapter in completed:
            lines.append(
                f"- Completed {chapter.chapter_number}: {self._clean(chapter.title)} | "
                f"{self._clean(chapter.summary)}"
            )
        self._append_section(sections, "Campaign arc", lines)

    def _add_evidence_memory(self, sections: List[str], records: Iterable[EvidenceRecord]) -> None:
        lines = []
        for record in records:
            source = record.source_ref or record.location or "unknown source"
            holder = record.holder_character_id or "party"
            tags = f" | tags={', '.join(record.tags)}" if record.tags else ""
            lines.append(
                f"- {self._clean(record.title)} [{record.evidence_id}] | holder={holder} | "
                f"source={self._clean(source)} | {self._clean(record.summary)}{tags}"
            )
        self._append_section(sections, "Durable evidence", lines)

    def _add_search_memory(self, sections: List[str], records: Iterable[SearchRecord]) -> None:
        lines = []
        for record in records:
            items = ", ".join(record.recovered_items) if record.recovered_items else "none"
            evidence = ", ".join(record.recovered_evidence_ids) if record.recovered_evidence_ids else "none"
            target = record.target_ref or record.location or "unknown target"
            lines.append(
                f"- {record.search_id} | target={self._clean(target)} | "
                f"{self._clean(record.summary)} | items={self._clean(items)} | evidence={evidence}"
            )
        self._append_section(sections, "Search outcomes", lines)

    def _add_character_memory(self, sections: List[str], characters: Iterable[Character]) -> None:
        lines = []
        for character in characters:
            experiences = [
                self._clean(item)
                for item in character.major_experiences[-self.max_experiences_per_character :]
                if str(item or "").strip()
            ]
            if not experiences:
                continue
            lines.append(f"- {character.name}: " + " | ".join(experiences))
        self._append_section(sections, "Character milestones", lines)

    def _add_log_memory(self, sections: List[str], log_entries: Iterable[str]) -> None:
        lines = [f"- {self._clean(entry)}" for entry in log_entries if str(entry or "").strip()]
        self._append_section(sections, "Recent durable log", lines)

    def _append_section(self, sections: List[str], title: str, lines: List[str]) -> None:
        clean_lines = [line for line in lines if line.strip()]
        if clean_lines:
            sections.append(f"{title}:\n" + "\n".join(clean_lines))

    def _clean(self, value: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        text = self.library.localize_game_terms(text)
        return self._truncate(text, 240)

    @staticmethod
    def _truncate(value: str, max_chars: int) -> str:
        text = str(value or "")
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 1)].rstrip() + "…"


def compile_campaign_memory(state: GameState, *, max_chars: int = 3600) -> str:
    return CampaignMemoryCompiler(max_chars=max_chars).compile(state)
