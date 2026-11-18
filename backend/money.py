"""钱币只有库存一个事实源；以整数铜币计算，避免浮点或整数金币截断。"""
import re

# 本地《玩家手册2024》装备/钱币：CP、SP、EP、GP、PP的等值铜币数。
COINS = {
    'cp': ('铜币', 1, ('copper', 'copper piece', 'copper pieces')),
    'sp': ('银币', 10, ('silver', 'silver piece', 'silver pieces')),
    'ep': ('银金币', 50, ('electrum', 'electrum piece', 'electrum pieces', '琥珀金币')),
    'gp': ('金币', 100, ('gold', 'gold piece', 'gold pieces')),
    'pp': ('铂金币', 1000, ('platinum', 'platinum piece', 'platinum pieces', '白金币')),
}
ORDER = ('pp', 'gp', 'ep', 'sp', 'cp')
ALIASES = {alias.casefold(): key for key, (name, _, aliases) in COINS.items()
           for alias in (key, name, *aliases)}


def denomination(name):
    return ALIASES.get(str(name or '').strip().casefold())


def count(value):
    if isinstance(value, str) and re.fullmatch(r'\d+', value):
        value = int(value)
    if type(value) is not int or value < 0:
        raise ValueError('钱币数量必须为非负整数。')
    return value


def coin_row(key, amount):
    name, value, _ = COINS[key]
    return {'name': name, 'quantity': amount, 'type': 'currency',
            'notes': f'每枚{name}价值{value}铜币。1金币＝10银币＝100铜币；1银金币＝50铜币；1铂金币＝10金币。',
            'source': 'currency'}


def split_inventory(rows):
    other, coins = [], {key: 0 for key in COINS}
    for item in rows:
        row = item.model_dump(mode='json') if hasattr(item, 'model_dump') else dict(item)
        key = denomination(row.get('name'))
        if key:
            coins[key] += count(row.get('quantity', 1))
        else:
            # 无面额的古币、纪念币、钱袋不推测购买力，原样保留普通物品。
            other.append(row)
    return other, coins


def join_inventory(other, coins):
    return [*other, *(coin_row(key, count(coins[key])) for key in ORDER if coins[key])]


def migrate_character_money(data):
    data = dict(data)
    other, coins = split_inventory(data.get('inventory') or [])
    if int(data.get('currency_inventory_version', 0)) < 1:
        # 老字段与原有金币物品是两笔余额；只迁移一次，不用名称猜测它们是同一笔。
        coins['gp'] += count(data.get('gold_gp', 0))
    for key in ('gold_gp', 'gold', 'gp'):
        data.pop(key, None)
    data['currency_inventory_version'] = 1
    data['inventory'] = join_inventory(other, coins)
    return data


def balance_cp(character):
    _, coins = split_inventory(character.inventory)
    return sum(coins[key] * COINS[key][1] for key in COINS)


def adjust(character, amount, coin):
    """先计算完整付款/找零结果，余额足够后一次发布；不会给出负库存。"""
    key = denomination(coin)
    if not key or type(amount) is not int or amount == 0:
        raise ValueError('收支需提供非零整数数量及有效钱币面额CP/SP/EP/GP/PP。')
    other, coins = split_inventory(character.inventory)
    before = dict(coins)
    before_value = sum(coins[c] * COINS[c][1] for c in COINS)
    after_value = before_value + amount * COINS[key][1]
    if after_value < 0:
        raise ValueError(f'钱币余额不足：现有等值{before_value}铜币，需支付{-amount * COINS[key][1]}铜币。')
    changed = amount < 0 and coins[key] < -amount
    if not changed:
        coins[key] += amount
    else:
        # 面额不足但总价值足够时等值找零；不生成不必要的银金币面额。
        coins = {c: 0 for c in COINS}
        remaining = after_value
        coins['pp'] = min(before['pp'], remaining // 1000)
        remaining -= coins['pp'] * 1000
        for c in ('gp', 'sp', 'cp'):
            coins[c], remaining = divmod(remaining, COINS[c][1])
    from models import InventoryItem
    inventory = [InventoryItem.model_validate(row) for row in join_inventory(other, coins)]
    character.inventory = inventory
    return {'denomination': key, 'coin_name': COINS[key][0], 'amount': amount,
            'change_made': changed, 'before': before, 'after': coins,
            'balance_cp_before': before_value, 'balance_cp_after': after_value,
            'patch': {'characters': {character.character_id: {'inventory': [i.model_dump(mode='json') for i in inventory]}}}}
