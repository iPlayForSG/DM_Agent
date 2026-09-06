import { mergeRollRecords } from "./rollUi.js";

export const createEmptyDmThinking = () => ({
  status: "idle",
  expanded: false,
  output: "",
  events: [],
  segmentCount: 0,
  rollRecords: [],
  startedAt: 0,
  waitingForModel: false,
  errorMessage: "",
  retryMessage: "",
});

export function prepareDmRetryUiRollback(current, targetMessageIndex) {
  const snapshot = {
    messages: current.messages,
    workflowEvents: current.workflowEvents,
    dmThinking: current.dmThinking,
  };
  return {
    snapshot,
    next: {
      messages: (current.messages || []).filter((item) => (
        !item.optimistic
        && Number.isInteger(item.index)
        && item.index < targetMessageIndex
      )),
      workflowEvents: [],
      dmThinking: createEmptyDmThinking(),
    },
  };
}

export function preparePlayerRewriteUiRollback(
  current,
  targetMessageIndex,
  replacementText,
  optimisticMessageId,
) {
  const snapshot = {
    messages: current.messages,
    workflowEvents: current.workflowEvents,
    dmThinking: current.dmThinking,
  };
  const targetMessage = (current.messages || []).find((item) => (
    !item.optimistic
    && item.sender === "player"
    && item.index === targetMessageIndex
  ));
  const precedingMessages = (current.messages || []).filter((item) => (
    !item.optimistic
    && Number.isInteger(item.index)
    && item.index < targetMessageIndex
  ));
  const rewrittenMessage = {
    index: targetMessageIndex,
    chatIndex: targetMessage?.chatIndex ?? null,
    role: "user",
    sender: "player",
    text: replacementText,
    optimistic: true,
    optimisticMessageId,
    renderKey: `pending-rewrite-${optimisticMessageId}`,
    deliveryState: "sending",
    deliveryLabel: "正在重写…",
  };

  return {
    snapshot,
    next: {
      // 服务端会按 rewind snapshot 回退；响应到达前先让浏览器展示同一条历史边界，避免旧分支继续留在画面上。
      messages: [...precedingMessages, rewrittenMessage],
      workflowEvents: [],
      dmThinking: createEmptyDmThinking(),
    },
  };
}

export function interruptedThinking(current, error) {
  const failure = error?.turnFailure;
  const confirmed = failure?.code === "turn_not_committed" && failure.branch_preserved === true;
  const records = confirmed
    ? mergeRollRecords(current.rollRecords, failure.roll_records || [])
    : current.rollRecords;
  return {
    ...current, status: "error", expanded: false, waitingForModel: false, retryMessage: "",
    errorMessage: error?.message || "主持连接中断，请重新载入存档确认进度。",
    rollRecords: records.map(record => ({ ...record,
      settlement: confirmed ? (["rolled_back", "not_applied"].includes(record.settlement) ? record.settlement : "rolled_back") : "unknown",
    })),
  };
}
