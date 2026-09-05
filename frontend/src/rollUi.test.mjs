import test from "node:test";
import assert from "node:assert/strict";
import { mergeRollRecords, rollSettlementLabel } from "./rollUi.js";

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
