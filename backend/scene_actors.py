"""战斗外规则目标登记；NPC身份进入先攻后保持不变。"""
from models import Combatant, Stats, random_id

TYPE_ALIASES = {"类人": "humanoid", "类人生物": "humanoid", "妖精": "fey", "野兽": "beast",
                "不死生物": "undead", "构装体": "construct", "龙": "dragon", "巨人": "giant",
                "异怪": "aberration", "天界": "celestial", "邪魔": "fiend", "元素": "elemental",
                "植物": "plant", "软泥": "ooze", "怪兽": "monstrosity"}


def creature_type(value):
    text = str(value or "").strip().casefold()
    return TYPE_ALIASES.get(text, text.split(" (")[0])


def register_actor(logic, name, creature, ability_scores, source, hp_max=10, ac=10,
                   saving_throws=None, condition_immunities=None, template=None):
    name, source = str(name or "").strip(), str(source or "").strip()
    if not name or not source:
        raise ValueError("登记场景人物需要名称与已确认的场景/规则来源")
    if logic.get_character(name):
        raise ValueError("该名称已是队伍角色，请使用现有角色ID")
    existing = logic.get_combatant(name)
    if existing:
        supplied_type = creature_type(template.creature_type if template else creature)
        if supplied_type and existing.creature_type and supplied_type != creature_type(existing.creature_type):
            raise ValueError("登记资料与目标已记录的生物类型冲突")
        if supplied_type and not existing.creature_type:
            existing.creature_type = supplied_type
        return existing, True
    if template:
        stats = template.stats.model_copy(deep=True)
        creature = template.creature_type
        hp_max, ac = template.hp_max, template.ac
        saving_throws, condition_immunities = template.saving_throws, template.condition_immunities
    else:
        if set(Stats.model_fields) - set(ability_scores or {}):
            raise ValueError("无模板NPC需要明确六项属性，不能以默认属性代替目标的豁免资料")
        stats = Stats(**ability_scores)
    if any(not 1 <= score <= 30 for score in stats.model_dump().values()) or hp_max <= 0 or ac <= 0:
        raise ValueError("场景人物的属性、生命或护甲数据无效")
    if not creature_type(creature):
        raise ValueError("场景人物需要明确生物类型")
    actor = Combatant(combatant_id=random_id("npc"), name=name, side="neutral", stats=stats,
                      creature_type=creature_type(creature), hp_max=hp_max, hp_current=hp_max, ac=ac,
                      saving_throws=dict(saving_throws or {}), condition_immunities=list(condition_immunities or []),
                      monster_template_id=template.monster_id if template else None, source=source)
    logic.state.scene_actors[actor.combatant_id] = actor
    return actor, False


def archive_inactive_encounter(state):
    if state.encounter and not state.encounter.active:
        for key, actor in state.encounter.combatants.items():
            if not actor.linked_character_id:
                state.scene_actors[key] = actor.model_copy(deep=True)
