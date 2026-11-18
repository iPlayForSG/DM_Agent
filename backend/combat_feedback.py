"""共享攻击结果文案；只展示已结算结果，不重新掷骰或修改伤害。"""


def attack_outcome_text(result):
    if result["critical"]:
        return "自然20 · 重击" if result.get("natural") == 20 else "重击"
    return "命中" if result["hit"] else "未命中"


def attack_damage_text(result):
    text = f"伤害 {result['damage_total']}"
    if result["critical"] and result.get("damage_roll"):
        text += f"（{result['damage_roll']}）"
    return text
