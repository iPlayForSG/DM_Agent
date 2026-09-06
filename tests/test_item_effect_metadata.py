import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import main as api
from agent_tools import AgentToolService
from action_service import GameActionService
from dm_graph import LANGGRAPH_TOOL_SCHEMAS
from models import Character, GameState, InventoryItem, Stats
from rules_catalog import RuleCatalog
from starter_shop import get_shop_item_by_name
from item_effects import effect_display


class ItemEffectMetadataTests(unittest.TestCase):
    def setUp(self):
        self.hero = Character(name="测试角色", class_name="Bard", stats=Stats(strength=8, dexterity=14))
        self.state = GameState(game_id="item-fixture", characters={self.hero.character_id: self.hero})
        self.rules = RuleCatalog()
        self.service = AgentToolService(rag_engine=None, monster_storage=None, rules_catalog=self.rules)

    def acquire(self, name, **kwargs):
        return self.service.add_inventory_item(self.state, self.hero.character_id, name, **kwargs)

    def test_chinese_weapon_pickup_persists_rules_and_preserves_quantity_notes(self):
        result = self.acquire("弯刀", notes="地精掉落", source="loot")
        self.assertTrue(result.ok)
        item = self.hero.inventory[0]
        self.assertEqual((item.name, item.damage_expression, item.damage_type), ("弯刀", "1d6+2", "slashing"))
        self.assertEqual(item.rules_name, "Scimitar")
        self.assertIn("Finesse", item.properties)
        self.assertFalse(item.is_equipped)
        self.assertEqual(item.notes, "地精掉落")
        self.assertEqual(result.payload["item"]["damage_expression"], "1d6+2")
        self.acquire("弯刀", quantity=2)
        self.assertEqual(self.hero.inventory[0].quantity, 3)
        self.assertEqual(self.hero.inventory[0].notes, "地精掉落")

    def test_catalog_aliases_do_not_guess_descriptive_names(self):
        self.assertEqual(get_shop_item_by_name(" scimitar ")["name"], "Scimitar")
        self.assertIsNone(get_shop_item_by_name("地精的未知魔法弯刀"))
        self.assertIsNone(get_shop_item_by_name(""))
        self.assertTrue(self.acquire("地精的旧弯刀", rules_name="Scimitar").ok)
        self.assertEqual(self.hero.inventory[0].damage_expression, "1d6+2")

    def test_old_inventory_display_and_attack_share_authoritative_profile_without_writes(self):
        self.hero.inventory = [InventoryItem(name="弯刀", type="misc", quantity=1)]
        before = self.state.model_dump(mode="json")
        actor = api.action_options_payload(self.state)["actors"][0]
        attack = actor["attacks"][0]
        profile = self.rules.resolve_character_attack_profile(self.hero, attack_name="Scimitar")
        self.assertEqual(attack["damage_expression"], "1d6+2")
        self.assertEqual(attack["damage_type"], "slashing")
        self.assertEqual(attack["attack_bonus"], profile["attack_bonus"])
        self.assertEqual(actor["items"][0]["damage_expression"], profile["damage_expression"])
        self.assertEqual(self.state.model_dump(mode="json"), before)
        self.hero.stats.dexterity = 18
        self.assertEqual(api._build_item_options(self.hero)[0]["damage_expression"], "1d6+4")

    def test_thrown_and_ranged_weapon_modifiers_match_execution(self):
        self.hero.stats.strength = 18
        self.hero.stats.dexterity = 8
        self.hero.inventory = [InventoryItem(name="长弓"), InventoryItem(name="标枪")]
        attacks = api._derive_character_attack_options(self.hero)
        self.assertEqual(attacks[0]["damage_expression"], "1d8-1")
        self.assertEqual(attacks[1]["damage_expression"], "1d6+4")

    def test_potions_and_throwables_have_effects_without_becoming_weapon_attacks(self):
        for name in ("治疗药水", "强酸瓶", "炼金火"):
            self.assertTrue(self.acquire(name).ok)
        before = self.state.model_dump(mode="json")
        items = api._build_item_options(self.hero)
        self.assertEqual(items[0]["healing_expression"], "2d4+2")
        self.assertIn("附赠动作", items[0]["effect_summary"])
        self.assertEqual((items[1]["damage_expression"], items[1]["damage_type"]), ("2d6", "acid"))
        self.assertIn("敏捷豁免", items[1]["effect_summary"])
        self.assertEqual((items[2]["damage_expression"], items[2]["damage_type"]), ("1d4", "fire"))
        self.assertEqual(api._derive_character_attack_options(self.hero), [])
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_scroll_keeps_per_missile_context_and_upcast_rules(self):
        details = {"name": "合成飞弹", "level": 1,
                   "desc": "制造三枚飞镖。每发飞镖造成1d4+1点力场伤害。",
                   "higherLevels": "每升一环额外制造一枚飞镖。"}
        with patch.object(self.rules.library, "get_spell_details", return_value=details):
            result = self.acquire("卷轴（合成飞弹）", spell_level=2)
            self.assertTrue(result.ok)
            item = self.hero.inventory[0]
            display = effect_display(item, library=self.rules.library)
        self.assertEqual(item.type, "scroll")
        self.assertEqual(item.spell_name, "合成飞弹")
        self.assertIn("基础法术效果", display["effect_summary"])
        self.assertIn("每发飞镖造成1d4+1", display["effect_summary"])
        self.assertIn("每升一环", display["effect_description"])
        self.assertEqual(item.damage_expression, "")

    def test_unknown_effect_never_invents_dice(self):
        result = self.acquire("未知武器", item_type="weapon", notes="尚待鉴定")
        self.assertTrue(result.ok)
        item = api._build_item_options(self.hero)[0]
        self.assertEqual(item["damage_expression"], "")
        self.assertIn("未完整记录", item["effect_summary"])
        self.assertIn("尚待鉴定", item["description"])
        self.assertIsNone(api._derive_character_attack_options(self.hero)[0]["attack_bonus"])
        self.assertTrue(self.acquire("未鉴定卷轴", item_type="scroll").ok)
        scroll = api._build_item_options(self.hero)[1]
        self.assertEqual(scroll["spell_name"], "")
        self.assertIsNone(scroll["spell_level"])
        self.assertIn("未完整记录", scroll["effect_summary"])

    def test_custom_effect_round_trip_and_local_service_match_agent_service(self):
        result = GameActionService().add_inventory_item(self.state, self.hero.character_id, "合成治疗包",
            item_type="consumable", healing_expression="1d6+3", effect_description="仅对活物，治疗1d6+3。")
        self.assertEqual(result["game_state"].characters[self.hero.character_id].inventory[0].healing_expression, "1d6+3")
        restored = GameState.model_validate_json(self.state.model_dump_json())
        self.assertEqual(restored.characters[self.hero.character_id].inventory[0].effect_description, "仅对活物，治疗1d6+3。")

    def test_invalid_metadata_never_increments_existing_stack(self):
        self.acquire("合成治疗包", item_type="consumable", healing_expression="1d6+3")
        before = self.state.model_dump(mode="json")
        result = self.acquire("合成治疗包", healing_expression="1d6+未知数")
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)
        result = self.acquire("合成治疗包", rules_name="不存在的目录条目")
        self.assertFalse(result.ok)
        self.assertEqual(self.state.model_dump(mode="json"), before)

    def test_pickup_never_auto_equips_armor_or_changes_combat_resources(self):
        before_ac = self.hero.ac
        self.assertTrue(self.acquire("盾牌").ok)
        self.assertFalse(self.hero.inventory[0].is_equipped)
        self.assertEqual(self.hero.ac, before_ac)

    def test_registered_pickup_schema_accepts_effect_metadata(self):
        schema = next(x for x in LANGGRAPH_TOOL_SCHEMAS if x["name"] == "add_inventory_item")
        self.assertTrue({"rules_name", "damage_expression", "damage_type", "healing_expression", "effect_description", "spell_name", "spell_level"} <= schema["parameters"]["properties"].keys())

    def test_scroll_level_change_cannot_upgrade_existing_stack(self):
        details = {"name": "合成飞弹", "level": 1, "desc": "每发造成1d4+1力场伤害。"}
        with patch.object(self.rules.library, "get_spell_details", return_value=details):
            self.assertTrue(self.acquire("合成飞弹卷轴", spell_level=1).ok)
            before = self.state.model_dump(mode="json")
            self.assertFalse(self.acquire("合成飞弹卷轴", spell_level=2).ok)
            self.assertEqual(self.state.model_dump(mode="json"), before)


if __name__ == "__main__":
    unittest.main()
