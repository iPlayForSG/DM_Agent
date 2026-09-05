import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("LANGGRAPH_CHECKPOINT_MODE", "memory")
os.environ.setdefault("RAG_AUTO_CONTEXT_RESULTS", "0")

import main as api
from models import Character, GameState, InventoryItem, Spellbook


class PartyDescriptionTests(unittest.TestCase):
    def test_action_options_publish_catalog_descriptions_without_mutating_state(self):
        spells = {
            "Friends": {"name": "交友术", "nameEN": "Friends", "level": 0, "desc": "合成戏法说明。",
                        "castingTime": "动作", "range": "10 尺", "duration": "1 分钟", "concentration": True},
            "Charm Person": {"name": "魅惑人类", "nameEN": "Charm Person", "level": 1,
                             "description": "合成法术说明。", "higherLevels": "合成升环说明。"},
        }
        def lookup(name):
            return spells.get(name) or next((value for value in spells.values() if value["name"] == name), {})
        character = Character(name="合成法师", class_name="Wizard", hp_current=8, hp_max=8,
                              spells=Spellbook(cantrips=["Friends"], prepared=["Charm Person"], slots={"1": {"total": 2}}),
                              inventory=[InventoryItem(name="合成物品", quantity=3, notes="记录于物品的说明。")])
        state = GameState(game_id="description-fixture", characters={character.character_id: character})
        before = state.model_dump(mode="json")
        with patch.object(api.library, "get_spell_details", side_effect=lookup):
            actor = api.action_options_payload(state)["actors"][0]
        options = {spell["name"]: spell for spell in actor["spells"]["options"]}
        self.assertEqual(actor["spells"]["cantrips"], ["交友术"])
        self.assertEqual(options["交友术"]["description"], "合成戏法说明。")
        self.assertTrue(options["交友术"]["concentration"])
        self.assertEqual(options["魅惑人类"]["higher_levels"], "合成升环说明。")
        self.assertEqual(actor["items"][0]["description"], "记录于物品的说明。")
        self.assertEqual(actor["items"][0]["quantity"], 3)
        self.assertEqual(state.model_dump(mode="json"), before)

    def test_item_catalog_fallback_preserves_custom_notes_and_empty_description(self):
        character = Character(name="测试角色", inventory=[
            InventoryItem(name="有目录说明", notes="玩家自己的备注。"),
            InventoryItem(name="只有目录备注"), InventoryItem(name="未描述物品"),
        ])
        catalog = {"有目录说明": {"description": "目录说明。", "notes": "目录默认备注。"},
                   "只有目录备注": {"notes": "目录备注。"}}
        with patch.object(api, "get_shop_item_by_name", side_effect=lambda name: catalog.get(name)):
            items = api._build_item_options(character)
        self.assertEqual(items[0]["description"], "目录说明。\n\n玩家自己的备注。")
        self.assertEqual(items[1]["description"], "目录备注。")
        self.assertEqual(items[2]["description"], "")
        self.assertEqual(character.inventory[1].notes, "")

    def test_missing_spell_description_does_not_invent_rules(self):
        character = Character(name="测试角色", spells=Spellbook(cantrips=["未收录戏法"]))
        with patch.object(api.library, "get_spell_details", return_value={}):
            options = api._build_spell_options(character)
        self.assertEqual(options[0]["description"], "")
        self.assertEqual(options[0]["name"], "未收录戏法")


if __name__ == "__main__":
    unittest.main()
