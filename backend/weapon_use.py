"""按实际使用方式解析持有物；临时武器不继承原武器的伤害、灵巧或熟练。"""
from rules_catalog import lookup_item_rules, proficiency_bonus_for_level
from stealth_rules import combine_roll_mode

# PHB2024 装备/武器：原生投掷武器的常规/最大射程。
THROWN_RANGES = {'Dagger': (20, 60), 'Handaxe': (20, 60), 'Light Hammer': (20, 60),
                 'Spear': (20, 60), 'Javelin': (30, 120), 'Trident': (20, 60), 'Dart': (20, 60)}


def profile(catalog, character, name, mode, distance, damage_type, equivalent, reason, roll_mode):
    if mode not in {'melee', 'thrown', 'improvised_melee'}:
        raise ValueError('Unsupported weapon use mode')
    items = [item for item in character.inventory if item.quantity > 0 and name.casefold() in
             {item.name.casefold(), item.rules_name.casefold(), catalog.library.localize_game_terms(item.name).casefold()}]
    if len(items) != 1:
        raise ValueError('attack_name must identify one held item; put the use mode in attack_mode, not in its name')
    item = items[0]
    definition = lookup_item_rules(item.rules_name or item.name) or {}
    properties = set(definition.get('properties', item.properties))
    improvised = mode == 'improvised_melee' or (mode == 'melee' and 'Ranged' in properties) or (mode == 'thrown' and 'Thrown' not in properties) or item.type != 'weapon'
    used = item
    if equivalent:
        if not improvised or not reason.strip():
            raise ValueError('Equivalent weapon requires an improvised object and an established similarity reason')
        definition = lookup_item_rules(equivalent) or {}
        if definition.get('type') != 'weapon':
            raise ValueError('Equivalent weapon must exist in the rules catalogue')
        used = item.model_copy(update={'name': definition['name'], 'rules_name': definition['name'], 'type': 'weapon'})
        properties = set(definition.get('properties', []))
        improvised = mode == 'thrown' and 'Thrown' not in properties
    if improvised:
        if damage_type not in {'bludgeoning', 'piercing', 'slashing'} or not reason.strip():
            raise ValueError('Improvised weapon requires a suitable physical damage_type and reason')
        ability = 'dexterity' if mode == 'thrown' else 'strength'
        modifier = catalog.get_ability_modifier(character, ability)
        proficient = character.origin_feat.casefold() in {'tavern brawler', '酒馆斗殴者', '酒馆斗士'}
        result = {'attack_bonus': modifier + (proficiency_bonus_for_level(character.level) if proficient else 0),
                  'damage_expression': catalog._format_damage_expression('1d4', modifier),
                  'damage_type': damage_type, 'source': 'improvised_weapon'}
    else:
        result = catalog._character_weapon_attack_profile(character, used)
    if mode == 'thrown':
        normal, maximum = (20, 60) if improvised else THROWN_RANGES.get(definition.get('name'), (0, 0))
        if not maximum:
            raise ValueError('Thrown weapon has no authoritative range')
        if distance is None or not 0 <= distance <= maximum:
            raise ValueError(f'Thrown attack requires distance_feet within {maximum} feet')
        roll_mode = combine_roll_mode(roll_mode, disadvantage=distance > normal)
        result.update(range_normal=normal, range_maximum=maximum, range_disadvantage=distance > normal)
    elif distance is not None and (distance < 0 or distance > (10 if not improvised and 'Reach' in properties else 5)):
        raise ValueError('Target is outside melee reach')
    result.update(attack_name=item.name, attack_mode=mode, improvised=improvised, roll_mode=roll_mode)
    return result


def release_thrown(character, name):
    # 命中与否都已离手；后续回收仍须明确拾取，不能继续从同一库存无限投掷。
    item = next(item for item in character.inventory if item.name == name and item.quantity > 0)
    item.quantity -= 1
    character.inventory = [entry for entry in character.inventory if entry.quantity > 0]
    return {'characters': {character.character_id: {'inventory': [i.model_dump(mode='json') for i in character.inventory]}}}
