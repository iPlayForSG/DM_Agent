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
