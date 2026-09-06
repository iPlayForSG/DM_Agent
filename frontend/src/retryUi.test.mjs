import assert from "node:assert/strict";
import test from "node:test";

import { prepareDmRetryUiRollback, preparePlayerRewriteUiRollback } from "./retryUi.js";

test("retry removes the DM reply and its transient projections while keeping a recovery snapshot", () => {
  const current = {
    messages: [
      { index: 0, sender: "player", text: "我观察石门。" },
      { index: 1, sender: "dm", text: "石门发出微光。" },
      { index: 2, sender: "player", text: "我继续观察。" },
      { index: 3, sender: "dm", text: "符号沿刻痕流动。" },
      { optimistic: true, sender: "player", text: "临时输入" },
    ],
    workflowEvents: [{ node_name: "finalize_turn" }],
    dmThinking: { status: "completed", output: "观察规则与现场。" },
  };

  const result = prepareDmRetryUiRollback(current, 3);

  assert.deepEqual(result.next.messages.map((item) => item.index), [0, 1, 2]);
  assert.deepEqual(result.next.workflowEvents, []);
  assert.equal(result.next.dmThinking.status, "idle");
  assert.equal(result.next.dmThinking.output, "");
  assert.strictEqual(result.snapshot.messages, current.messages);
  assert.strictEqual(result.snapshot.dmThinking, current.dmThinking);
});

test("rewrite immediately replaces the player message and removes the later UI branch", () => {
  const current = {
    messages: [
      { index: 0, chatIndex: 0, sender: "player", text: "我观察石门。" },
      { index: 1, chatIndex: 1, sender: "dm", text: "石门发出微光。" },
      { index: 2, chatIndex: 2, sender: "system", text: "记录了一个节点。" },
      { index: 3, chatIndex: 3, sender: "player", text: "我继续观察。" },
      { index: 4, chatIndex: 4, sender: "dm", text: "符号沿刻痕流动。" },
      { optimistic: true, sender: "player", text: "未结算输入" },
    ],
    workflowEvents: [{ node_name: "finalize_turn" }],
    dmThinking: { status: "completed", output: "观察规则与现场。" },
  };

  const result = preparePlayerRewriteUiRollback(
    current,
    0,
    "我谨慎地检查石门。",
    "game-1-rewrite-1",
  );

  assert.equal(result.next.messages.length, 1);
  assert.deepEqual(result.next.messages[0], {
    index: 0,
    chatIndex: 0,
    role: "user",
    sender: "player",
    text: "我谨慎地检查石门。",
    optimistic: true,
    optimisticMessageId: "game-1-rewrite-1",
    renderKey: "pending-rewrite-game-1-rewrite-1",
    deliveryState: "sending",
    deliveryLabel: "正在重写…",
  });
  assert.deepEqual(result.next.workflowEvents, []);
  assert.equal(result.next.dmThinking.status, "idle");
  assert.strictEqual(result.snapshot.messages, current.messages);
  assert.strictEqual(result.snapshot.workflowEvents, current.workflowEvents);
  assert.strictEqual(result.snapshot.dmThinking, current.dmThinking);
});

test("rewrite keeps only messages before the selected player action", () => {
  const current = {
    messages: [
      { index: 0, chatIndex: 0, sender: "player", text: "第一步。" },
      { index: 1, chatIndex: 1, sender: "dm", text: "第一段回复。" },
      { index: 2, chatIndex: 2, sender: "player", text: "第二步。" },
      { index: 3, chatIndex: 3, sender: "system", text: "后续记录。" },
    ],
    workflowEvents: [],
    dmThinking: { status: "idle", output: "" },
  };

  const result = preparePlayerRewriteUiRollback(current, 2, "改写后的第二步。", "rewrite-2");

  assert.deepEqual(result.next.messages.map((item) => item.index), [0, 1, 2]);
  assert.equal(result.next.messages[2].text, "改写后的第二步。");
  assert.equal(result.next.messages[2].optimistic, true);
});

test("确定失败与未知断线使用不同骰点状态，错误原因保留在卡片", async () => {
  const { interruptedThinking } = await import("./retryUi.js");
  const current = {rollRecords:[{record_id:"r",settlement:"pending"}],output:"准备调查。"};
  const known = interruptedThinking(current,{message:"原剧情已保留",turnFailure:{code:"turn_not_committed",branch_preserved:true,roll_records:[{record_id:"r",settlement:"rolled_back"}]}});
  assert.equal(known.rollRecords[0].settlement,"rolled_back");
  assert.equal(known.errorMessage,"原剧情已保留");
  assert.equal(known.expanded,false);
  const unknown = interruptedThinking(current,new Error("连接中断"));
  assert.equal(unknown.rollRecords[0].settlement,"unknown");
});
