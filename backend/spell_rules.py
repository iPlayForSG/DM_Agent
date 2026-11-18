"""受信规则资料与通用效果协议；规则差异在数据中，不在执行器中按名字分流。"""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
import re


class RuleConflict(ValueError):
    """可直接向玩家解释、要求调整的规则冲突。"""


class RulesUnavailable(ValueError):
    """规则数据不能支持可靠结算，区别于玩家选择错误。"""


def key(name):
    return str(name or "").replace("’", "'").strip().casefold()


@lru_cache(maxsize=1)
def definitions():
    return json.loads((Path(__file__).parent / "data/spell_effect_rules.json").read_text(encoding="utf-8"))["rules"]


def rule_for(details):
    # mechanics可来自受信的本地法术库；不会接收模型在工具参数中临时拼出的效果定义。
    if isinstance(details.get("mechanics"), dict):
        result = deepcopy(details["mechanics"])
    else:
        names = {key(details.get("name")), key(details.get("nameEN"))}
        result = next((deepcopy(rule) for rule in definitions() if names & {key(n) for n in rule["names"]}), None)
    if result is None:
        return None
    allowed = {"conditions", "damage", "healing", "narrative"}
    if any(effect.get("kind") not in allowed for effect in result.get("effects", [])):
        raise RulesUnavailable("该法术含尚未支持的效果类型，不能可靠地完成结算")
    return result


def automatic_save_rule(name, library):
    rule = rule_for(library.get_spell_details(name) or {"name": name})
    return bool(rule and rule.get("save"))


def declared_spells(graph_state, library):
    flow = graph_state.get("combat_flow") or {}
    if flow.get("stop_at_player") and not flow.get("action_done"):
        return []
    intent = graph_state.get("turn_intent") or {}
    if "spell_action" not in intent.get("intent_tags", []) and not ("cast_spell" in intent.get("suggested_tools", []) and intent.get("turn_type") in {"action_resolution", "combat_resolution"}):
        return []
    text = key(graph_state.get("user_input"))
    # 条件分支由DM根据现场选择，只要求实际启动的结算；不强迫同时执行互斥分支。
    if any(word in text for word in ("如果", "否则", "若能", "if ", "otherwise")):
        return []
    candidates = {}
    for values in library.spells.values():
        for spell in values:
            for name in [spell.get("name"), spell.get("nameEN"), *spell.get("aliases", [])]:
                if name:
                    candidates[key(name)] = spell.get("name") or name
    mentions = []
    masked = text
    for name in sorted(candidates, key=len, reverse=True):
        pattern = r"(?<![a-z])" + re.escape(name) + r"(?![a-z])" if name.isascii() else re.escape(name)
        matches = list(re.finditer(pattern, masked))
        for match in matches:
            mentions.append((match.start(), match.end(), candidates[name]))
        for match in reversed(matches):
            masked = masked[:match.start()] + " " * (match.end()-match.start()) + masked[match.end():]
    result = []
    for start, end, canonical in sorted(mentions):
        prefix = re.split(r"[，。；;,.!?！？\n]", text[:start])[-1]
        suffix = re.split(r"[，。；;,.!?！？\n]", text[end:])[0]
        if re.search(r"不(?:再)?(?:施放|施展|释放)|不要(?:再)?(?:施放|施展|释放)|别施放|not cast|don't cast", prefix):
            continue
        # 同一段可能先提旧效果再施放新法术；按每次提及的最近动词判断，不能全句一刀切。
        verbs = list(re.finditer(r"施放|施展|释放|重施|使用|用|(?:re)?cast(?:ing)?|等待|等到|等候|等着|静待|只等|等|专注|维持|保持|停止|结束|取消|解除|放弃|观察|确认|检查|核验|查阅|查看|了解|维系|wait(?:ing)?|maintain(?:ing)?|concentrat(?:e|ing)|end(?:ing)?|stop(?:ping)?", prefix))
        last = verbs[-1].group() if verbs else ''
        explicit_cast = bool(re.fullmatch(r"施放|施展|释放|重施|使用|用|(?:re)?cast(?:ing)?", last))
        referring_to_effect = bool(re.match(r"(?:的)?(?:效果|剩余|余下|持续时间|专注(?:状态)?|还在|还有)|.*?(?:结束|到期|失效|消退|散去|expire|wear off)", suffix))
        if last and not explicit_cast:
            continue
        if referring_to_effect and not re.fullmatch(r"施放|施展|释放|重施|(?:re)?cast(?:ing)?", last):
            continue
        # 没有生命周期/查询语境的简短法术指令仍按既有spell_action意图处理。
        result.append(canonical)
    return list(dict.fromkeys(result))
