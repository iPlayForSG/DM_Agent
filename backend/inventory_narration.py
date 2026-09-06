"""以已提交状态差值生成物品叙事标记；模型只能决定位置，不能创造数量。"""
from collections import Counter
import re

MARKER = re.compile(r"\*\*物品｜[^\n*]+\*\*")


def _text(value):
    return re.sub(r"[\r\n*`<>\[\]\\]", " ", str(value)).strip()


def _items(character):
    result = {}
    if character:
        for item in character.inventory:
            key = (item.name, item.type)
            entry = result.setdefault(key, {"quantity": 0, "equipped": False})
            entry["quantity"] += item.quantity
            entry["equipped"] |= item.is_equipped
    return result


def inventory_annotations(before, after, localize=lambda value: value):
    records = []
    for actor_id in sorted(set(before.characters) | set(after.characters)):
        old = before.characters.get(actor_id)
        new = after.characters.get(actor_id)
        actor_name = _text(localize((new or old).name))
        old_items, new_items = _items(old), _items(new)
        for key in sorted(set(old_items) | set(new_items)):
            previous = old_items.get(key, {"quantity": 0, "equipped": False})
            current = new_items.get(key, {"quantity": 0, "equipped": False})
            delta = current["quantity"] - previous["quantity"]
            item_name = _text(localize(key[0]))
            if delta:
                line = f"{actor_name}：{item_name} {delta:+d}（现有 {current['quantity']}）"
                records.append((item_name, f"**物品｜{line}**"))
            if previous['equipped'] != current['equipped'] and current['quantity'] > 0:
                action = '已装备' if current['equipped'] else '已卸下'
                records.append((item_name, f"**物品｜{actor_name}：{item_name} {action}**"))
        gold_delta = (new.gold_gp if new else 0) - (old.gold_gp if old else 0)
        if gold_delta:
            records.append(('金币', f"**物品｜{actor_name}：金币 {gold_delta:+g}（现有 {(new.gold_gp if new else 0):g}）**"))
    return records


def ensure_inventory_annotations(text, records):
    # 仅接受本次状态差值对应的完整标记，去除伪造值与重复项；后处理扩写后也须再核对。
    remaining = Counter(marker for _, marker in records)
    def keep(match):
        marker = match.group(0)
        if remaining[marker] <= 0:
            return ''
        remaining[marker] -= 1
        return marker
    response = MARKER.sub(keep, text).strip()
    paragraphs = [part.strip() for part in re.split(r'\n\s*\n', response) if part.strip()] or ['']
    for item_name, marker in records:
        if remaining[marker] <= 0:
            continue
        remaining[marker] -= 1
        # 优先紧随提到物品的段落；没有明确对应段落时放在正文末尾，不能编造取得过程。
        index = next((i for i, paragraph in enumerate(paragraphs) if item_name in paragraph), len(paragraphs)-1)
        paragraphs[index] += '\n\n' + marker
    return '\n\n'.join(paragraphs).strip()
