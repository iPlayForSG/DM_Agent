import assert from "node:assert/strict";
import test from "node:test";

import { prepareDmRetryUiRollback } from "./retryUi.js";

test("retry removes the DM reply and its transient projections while keeping a recovery snapshot", () => {
  const current = {
    messages: [
      { index: 0, sender: "player", text: "我观察石门。" },
      { index: 1, sender: "dm", text: "石门发出微光。" },
      { index: 2, sender: "player", text: "我继续观察。" },
      { index: 3, sender: "dm", text: "符号沿刻痕流动。" },
      { optimistic: true, sender: "player", text: "临时输入" },
    ],
    actionSuggestions: [{ label: "检查符号", action: "我检查符号。" }],
    workflowEvents: [{ node_name: "finalize_turn" }],
    dmThinking: { status: "completed", output: "观察规则与现场。" },
    actionSuggestionsLoading: true,
  };

  const result = prepareDmRetryUiRollback(current, 3);

  assert.deepEqual(result.next.messages.map((item) => item.index), [0, 1, 2]);
  assert.deepEqual(result.next.actionSuggestions, []);
  assert.deepEqual(result.next.workflowEvents, []);
  assert.equal(result.next.dmThinking.status, "idle");
  assert.equal(result.next.dmThinking.output, "");
  assert.strictEqual(result.snapshot.messages, current.messages);
  assert.strictEqual(result.snapshot.actionSuggestions, current.actionSuggestions);
  assert.strictEqual(result.snapshot.dmThinking, current.dmThinking);
  assert.equal(result.snapshot.actionSuggestionsLoading, true);
});
