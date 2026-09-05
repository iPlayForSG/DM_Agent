export const createEmptyDmThinking = () => ({
  status: "idle",
  expanded: false,
  output: "",
  events: [],
  segmentCount: 0,
  rollRecords: [],
  startedAt: 0,
  waitingForModel: false,
});

export function prepareDmRetryUiRollback(current, targetMessageIndex) {
  const snapshot = {
    messages: current.messages,
    actionSuggestions: current.actionSuggestions,
    workflowEvents: current.workflowEvents,
    dmThinking: current.dmThinking,
    actionSuggestionsLoading: Boolean(current.actionSuggestionsLoading),
  };
  return {
    snapshot,
    next: {
      messages: (current.messages || []).filter((item) => (
        !item.optimistic
        && Number.isInteger(item.index)
        && item.index < targetMessageIndex
      )),
      actionSuggestions: [],
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
    actionSuggestions: current.actionSuggestions,
    workflowEvents: current.workflowEvents,
    dmThinking: current.dmThinking,
    actionSuggestionsLoading: Boolean(current.actionSuggestionsLoading),
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
      actionSuggestions: [],
      workflowEvents: [],
      dmThinking: createEmptyDmThinking(),
    },
  };
}
