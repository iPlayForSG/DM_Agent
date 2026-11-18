export function mergeRollRecords(current = [], incoming = []) {
  const merged = new Map(current.map((record) => [record.record_id, record]));
  for (const record of incoming) {
    if (record?.record_id) merged.set(record.record_id, record);
  }
  return [...merged.values()];
}

export function rollSettlementLabel(record) {
  return {
    pending: "待提交", committed: "已记录", rolled_back: "本轮未提交",
    not_applied: "工具未成功", unknown: "提交状态待确认",
  }[record.settlement] || "待提交";
}

export function rollOutcomeLabel(record) {
  if (record.kind === "attack") {
    // 旧记录只从实际保留的d20读取自然骰值；绝不按总值或被丢弃的20推断重击。
    const kept = Array.isArray(record.kept) ? record.kept : [];
    const dice = Array.isArray(record.dice) ? record.dice : [];
    const natural = record.natural ?? (kept.length === 1 ? kept[0] : dice.length === 1 ? dice[0] : null);
    const critical = record.critical ?? (natural === 20);
    if (critical) return natural === 20 ? "自然20 · 重击" : "重击";
    if (natural === 1 && record.success === false) return "自然1 · 自动未命中";
  }
  if (record.kind === "damage" && record.critical) return "重击伤害";
  return record.success == null ? "" : record.success ? "成功" : "失败";
}
