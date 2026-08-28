"""Private state contracts for compiled DM agent subgraphs."""

from typing import Annotated, Any, Dict, List, TypedDict

from langgraph.graph.message import add_messages


class DMBrainState(TypedDict, total=False):
    """Private per-invocation state for the model/tool/validation loop."""

    agent_role: str
    game_state: Dict[str, Any]
    initial_game_state: Dict[str, Any]
    user_input: str
    thread_id: str
    phase: str
    scene: str
    phase_objective: str
    phase_constraints: List[str]
    phase_blockers: List[str]
    messages: Annotated[List[Any], add_messages]
    state_summary: str
    recent_history: str
    campaign_memory: str
    instruction: str
    rag_snippets: List[Dict[str, Any]]
    rag_context: str
    rag_queries: List[str]
    rag_intent: str
    rag_reason: str
    rag_metadata: Dict[str, Any]
    input_warnings: List[str]
    turn_intent: Dict[str, Any]
    turn_profile: str
    turn_profile_reason: str
    turn_guidance: str
    turn_expectation: str
    suggested_tools: List[str]
    turn_checklist: List[str]
    allowed_tools: List[str]
    tool_round_limit: int
    tool_call_rounds: int
    turn_status: str
    pending_input: Dict[str, Any]
    final_response: str
    action_suggestions: List[Dict[str, Any]]
    active_agent: str
    tool_results: List[Dict[str, Any]]
    state_delta: Dict[str, Any]
    timeline_append: List[Dict[str, Any]]
    validation_status: str
    validation_repair_tools: List[str]
    validation_notes: List[str]
    validation_issues: List[Dict[str, Any]]
    node_traces: List[Dict[str, Any]]


DM_BRAIN_PARENT_FIELDS = frozenset(
    field_name
    for field_name in DMBrainState.__annotations__
    if field_name != "agent_role"
)
