import test from "node:test";
import assert from "node:assert/strict";
import { mergeRollRecords, rollSettlementLabel, rollOutcomeLabel } from "./rollUi.js";

test("identical dice results are distinct, while updates replace only their own record", () => {
  const first = { record_id: "a", total: 5, visibility: "hidden", settlement: "pending" };
  const second = { record_id: "b", total: 5, visibility: "public", settlement: "pending" };
  const records = mergeRollRecords([first], [second, { ...first, success: true }]);
  assert.deepEqual(records.map((record) => record.record_id), ["a", "b"]);
  assert.equal(records[0].success, true);
  assert.equal(first.success, undefined);
});

test("unconfirmed and rolled-back rolls are not labelled as committed", () => {
  assert.equal(rollSettlementLabel({ settlement: "unknown" }), "提交状态待确认");
  assert.equal(rollSettlementLabel({ settlement: "rolled_back" }), "本轮未提交");
  assert.equal(rollSettlementLabel({ settlement: "not_applied" }), "工具未成功");
});

test("critical labels use the kept natural die and preserve legacy receipts", () => {
  assert.equal(rollOutcomeLabel({kind:"attack", natural:20, critical:true, total:24}), "自然20 · 重击");
  assert.equal(rollOutcomeLabel({kind:"attack", kept:[20], dice:[7,20], success:true}), "自然20 · 重击");
  assert.equal(rollOutcomeLabel({kind:"attack", kept:[4], dice:[20,4], success:false}), "失败");
  assert.equal(rollOutcomeLabel({kind:"attack", kept:[16], total:20, success:true}), "成功");
  assert.equal(rollOutcomeLabel({kind:"attack", dice:[20,4], success:false}), "失败");
  assert.equal(rollOutcomeLabel({kind:"attack", natural:1, total:101, success:false}), "自然1 · 自动未命中");
  assert.equal(rollOutcomeLabel({kind:"skill", dice:[20], kept:[20], success:false}), "失败");
  assert.equal(rollOutcomeLabel({kind:"damage", critical:true}), "重击伤害");
});

test("critical annotations survive stream merging and settlement labels remain separate", () => {
  const merged = mergeRollRecords([{record_id:"crit",kind:"attack",kept:[20],settlement:"pending"}],
    [{record_id:"crit",kind:"attack",natural:20,critical:true,settlement:"rolled_back"}]);
  assert.equal(merged.length,1);
  assert.equal(rollOutcomeLabel(merged[0]),"自然20 · 重击");
  assert.equal(rollSettlementLabel(merged[0]),"本轮未提交");
});
