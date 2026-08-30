import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as api_main  # noqa: E402


ASCII_WORD = re.compile(r"[A-Za-z]")


class BuilderLocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = api_main.builder_payload()

    def assert_display_field_is_chinese(self, entry, field: str) -> None:
        raw = entry.get(field)
        if not isinstance(raw, str) or not ASCII_WORD.search(raw):
            return
        display_field = f"{field}_display"
        self.assertIn(display_field, entry, f"{raw!r} 缺少 {display_field}")
        display = entry[display_field]
        self.assertNotEqual(display, raw)
        self.assertIsNone(ASCII_WORD.search(display), f"{raw!r} 仍显示为 {display!r}")

    def test_all_primary_character_choices_have_chinese_display_names(self) -> None:
        for category in ("species", "backgrounds", "classes", "origin_feats"):
            with self.subTest(category=category):
                for entry in self.payload[category]:
                    self.assert_display_field_is_chinese(entry, "name")

        for background in self.payload["backgrounds"]:
            self.assert_display_field_is_chinese(background, "origin_feat")

    def test_species_traits_and_equipment_copy_are_localized_recursively(self) -> None:
        for species in self.payload["species"]:
            raw_traits = species.get("traits") or []
            if not any(ASCII_WORD.search(str(trait)) for trait in raw_traits):
                continue
            self.assertEqual(len(species.get("traits_display") or []), len(raw_traits))
            for trait in species["traits_display"]:
                self.assertIsNone(ASCII_WORD.search(trait), f"种族特性仍显示为 {trait!r}")

        for class_def in self.payload["classes"]:
            for resource_name, resource in (class_def.get("resources") or {}).items():
                display_name = api_main.library.localize_game_terms(resource_name)
                self.assertIsNone(ASCII_WORD.search(display_name), f"职业资源仍显示为 {display_name!r}")
                self.assert_display_field_is_chinese(resource, "description")
                self.assert_display_field_is_chinese(resource, "recovery")

            for option in class_def.get("starter_equipment_options") or []:
                self.assert_display_field_is_chinese(option, "label")
                self.assert_display_field_is_chinese(option, "description")
                for item in option.get("items") or []:
                    for field in ("name", "type", "notes", "damage_type"):
                        self.assert_display_field_is_chinese(item, field)
                for choice in option.get("choices") or []:
                    self.assert_display_field_is_chinese(choice, "label")
                    self.assert_display_field_is_chinese(choice, "description")
                    for choice_option in choice.get("options") or []:
                        self.assert_display_field_is_chinese(choice_option, "label")

        for item in self.payload.get("equipment_shop_items") or []:
            for field in ("name", "type", "notes", "damage_type"):
                self.assert_display_field_is_chinese(item, field)

    def test_spell_display_fields_support_english_source_data(self) -> None:
        localized = api_main._add_display_fields(
            {"name": "Blade Ward", "school": "Abjuration"}
        )

        self.assertEqual(localized["name_display"], "剑刃防护")
        self.assertEqual(localized["school_display"], "防护")


if __name__ == "__main__":
    unittest.main()
