export const createEmptyDmThinking = () => ({
  status: "idle",
  expanded: false,
  output: "",
  events: [],
  segmentCount: 0,
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
