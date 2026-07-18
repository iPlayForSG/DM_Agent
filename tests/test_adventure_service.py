import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from adventure_service import (
    AI_GENERATED_ADVENTURE_ID,
    generate_initial_adventures,
    is_model_generated_adventure_id,
    opening_action_suggestions,
    parse_generated_adventure,
    validate_dnd_adventure_theme,
)
from models import Character


class AdventureServiceTest(unittest.TestCase):
    def test_initial_adventures_include_three_templates_and_ai_option(self) -> None:
        hooks = generate_initial_adventures(
            [Character(name="艾拉", class_name="Wizard", species="Elf", level=1)]
        )

        self.assertEqual(len(hooks), 4)
        self.assertEqual(hooks[-1].adventure_id, AI_GENERATED_ADVENTURE_ID)
        self.assertNotIn(AI_GENERATED_ADVENTURE_ID, [hook.adventure_id for hook in hooks[:-1]])
        self.assertTrue(all(len(opening_action_suggestions(hook)) == 3 for hook in hooks[:-1]))

    def test_parse_generated_adventure_from_fenced_json(self) -> None:
        raw_response = """```json
{
  "title": "雾港血契",
  "summary": "港口夜雾中，一份被盗契约把码头行会和失踪水手的家属推向冲突。",
  "tone": "街头诡秘",
  "difficulty": "中等",
  "opening_scene": "你们抵达雾港时，潮水已经漫过旧码头的第二级石阶。一个浑身湿透的书记员把蜡封残片塞进你手里，身后传来行会打手的脚步声。远处钟楼只敲了半下，雾里却有人回答。",
  "opening_suggestions": [
    {"label": "护住书记员", "action": "我挡在书记员和行会打手之间，要求他们先说明来意。"},
    {"label": "检查蜡封", "action": "我检查书记员塞来的蜡封残片，辨认纹章和断裂痕迹。"},
    {"label": "观察钟楼", "action": "我望向只敲了半下的钟楼，寻找雾中的人影或魔法迹象。"}
  ]
}
```"""

        hook = parse_generated_adventure(raw_response)

        self.assertTrue(hook.adventure_id.startswith("adv-ai-"))
        self.assertNotEqual(hook.adventure_id, AI_GENERATED_ADVENTURE_ID)
        self.assertTrue(is_model_generated_adventure_id(hook.adventure_id))
        self.assertEqual(hook.title, "雾港血契")
        self.assertIn("码头行会", hook.summary)

    def test_generated_adventure_rejects_non_dnd_folklore(self) -> None:
        raw_response = """{
  "title": "荒村饿鬼瓮",
  "summary": "山村土地龛下的黑陶瓮裂开，封在里头的饿鬼婆逃入祠堂。",
  "tone": "中式志怪",
  "difficulty": "中等",
  "opening_scene": "村口土地龛下倒着一尊黑陶瓮，香灰洒了一地。庙祝跪在祠堂里，村老说饿鬼婆已经跑了出来。",
  "opening_suggestions": [
    {"label": "查看陶瓮", "action": "我查看土地龛下裂开的黑陶瓮。"},
    {"label": "询问庙祝", "action": "我询问跪在祠堂里的庙祝。"},
    {"label": "追踪饿鬼", "action": "我追踪村老所说的饿鬼婆。"}
  ]
}"""

        with self.assertRaisesRegex(ValueError, "non-D&D folklore"):
            parse_generated_adventure(raw_response)

    def test_dnd_theme_validation_accepts_dnd_anchor(self) -> None:
        hook = parse_generated_adventure("""{
  "title": "黑荆地城",
  "summary": "边境酒馆的商队护卫失踪，线索指向旧矿坑下方的地精地城。",
  "tone": "阴郁西幻",
  "difficulty": "中等",
  "opening_scene": "你们在边境酒馆听见商队首领压低声音求助：三名护卫昨夜被拖进旧矿坑，入口处留着地精的短矛和一枚刻着散塔林会暗记的铜扣。村镇守卫不愿下井。",
  "opening_suggestions": [
    {"label": "询问马夫", "action": "我询问幸存马夫，确认地精袭击商队时的数量和方向。"},
    {"label": "检查铜扣", "action": "我检查刻着散塔林会暗记的铜扣，判断它属于护卫还是袭击者。"},
    {"label": "勘察矿坑", "action": "我前往旧矿坑入口，查看地精短矛和拖行痕迹。"}
  ]
}""")

        validate_dnd_adventure_theme(hook)


if __name__ == "__main__":
    unittest.main()
