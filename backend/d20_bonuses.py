"""来源拥有的可消费D20加骰；随机任务与玩家决定分离，恢复时不重掷。"""
from contextlib import contextmanager
from contextvars import ContextVar
import random
from uuid import uuid4

_decision = ContextVar('d20_bonus_decision', default=None)
_replay = ContextVar('pending_dice_replay', default=None)
_history = ContextVar('operation_dice_history', default=None)


@contextmanager
def replay_pending_rolls(draws):
    # 嵌套StructuredTool的随机子任务并不保证跨恢复复用同一task ID。
    # 使用checkpoint与服务端pending_turn内的内部随机带；显示RollRecord不参与裁定。
    token = _replay.set(list(draws))
    try:
        yield
    finally:
        _replay.reset(token)


def draw(count, sides):
    pending = _replay.get()
    if pending:
        record = pending.pop(0)
        values = record.get('values', [])
        if (record.get('count'), record.get('sides')) != (count, sides) or len(values) != count or any(not isinstance(d,int) or not 1 <= d <= sides for d in values):
            raise ValueError('暂停期间骰型发生变化，不能重掷或继续该结算。')
        values, identifier = list(values), record['record_id']
    else:
        values, identifier = [random.randint(1, sides) for _ in range(count)], uuid4().hex
    if _history.get() is not None:
        _history.get().append({'count':count,'sides':sides,'values':values,'record_id':identifier})
    return values, identifier


@contextmanager
def decision_context(handler=None):
    first = _decision.set(handler)
    history_token = _history.set([])
    try:
        yield
    finally:
        _decision.reset(first)
        _history.reset(history_token)


def available(logic, ref):
    from spell_effects import actor_id
    identifier = actor_id(logic, ref)
    return [bonus for bonus in logic.state.granted_dice
            if bonus.target_id == identifier and bonus.expires_at_seconds > logic.state.rules_time_seconds]


def expire(state):
    state.granted_dice = [b for b in state.granted_dice if b.expires_at_seconds > state.rules_time_seconds]


def prepare_inspiration(logic, source, target_ref, distance_feet, target_can_perceive):
    from models import GrantedDie
    from spell_effects import actor, actor_id
    if not target_ref:
        raise ValueError('诗人激励必须指定另一名生物 target_ref；场景人物需先登记。')
    target = actor(logic, target_ref)
    identifier = actor_id(logic, target_ref)
    if identifier == source.character_id:
        raise ValueError('诗人激励不能给予自己。')
    if distance_feet is None or not 0 <= distance_feet <= 60 or target_can_perceive is not True:
        raise ValueError('诗人激励需要确认目标在60尺内且能听见或看见施予者。')
    if target.hp_current <= 0 or target.defeat_state == 'dead':
        raise ValueError('目标无法感知这次诗人激励。')
    if any(b.kind == 'bardic_inspiration' for b in available(logic, target_ref)):
        raise ValueError('目标已持有诗人激励骰；不能叠加或覆盖。')
    if source.class_name.casefold() not in {'bard', '吟游诗人'}:
        raise ValueError('施予者没有诗人激励职业特性。')
    sides = 12 if source.level >= 15 else 10 if source.level >= 10 else 8 if source.level >= 5 else 6
    return GrantedDie(bonus_id=uuid4().hex, source_id=source.character_id, target_id=identifier,
                      expression=f'1d{sides}', expires_at_seconds=logic.state.rules_time_seconds + 3600)


def apply_failed_test(logic, ref, total, dc, detail, *, eligible=True):
    """在失败后果生效前消费；自然1攻击不能被加值变成命中，成功不消费。"""
    if not eligible or dc <= 0 or total >= dc:
        return total, detail, []
    from spell_effects import actor_id
    from game_logic import DiceRoller
    from roll_capture import dice_context
    events = []
    for bonus in available(logic, ref):
        info = {'actor': logic.get_actor_name(ref), 'total': total, 'dc': dc,
                'expression': bonus.expression, 'bonus_id': bonus.bonus_id}
        handler = _decision.get()
        # NPC/托管队友由DM决定；玩家骰必须有玩家选择，缺少交互的本地调用保留骰。
        use = handler(info) if handler and logic.state.is_player_controlled(actor_id(logic, ref)) else not logic.state.is_player_controlled(actor_id(logic, ref))
        if not use:
            continue
        with dice_context(kind='effect', actor=info['actor'], label='诗人激励', dc=None):
            amount, rolled = DiceRoller.roll(bonus.expression)
        logic.state.granted_dice.remove(bonus)
        total += amount
        detail += f' + 诗人激励 {rolled}'
        events.append({'kind': 'granted_die_consumed', **info, 'bonus': amount, 'result': total, 'success': total >= dc})
        if total >= dc:
            break
    return total, detail, events


def graph_decision(info):
    from langgraph.types import interrupt
    prompt = f"{info['actor']} 的D20检定 {info['total']} vs DC {info['dc']} 失败。是否消耗诗人激励 {info['expression']}？"
    while True:
        selected = interrupt({'kind': 'player_choice', 'prompt': prompt,
                              'details': {'options': ['使用激励', '保留激励'], 'allow_cancel': False,
                                          '_dice_replay': list(_history.get() or []),
                                          'reason': 'failed_d20_bonus', **info}})
        text = str(selected.get('message', '') if isinstance(selected, dict) else selected).strip()
        if text in {'使用激励', '使用', 'yes'}:
            return True
        if text in {'保留激励', '保留', '不使用', 'no'}:
            return False
        prompt = '请选择“使用激励”或“保留激励”。原检定骰点保持不变。'
