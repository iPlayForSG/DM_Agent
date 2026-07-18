"""Factory for isolated LangChain agents compiled on LangGraph."""

from typing import Any, Dict, Iterable, Optional

from langchain.agents import create_agent

from .contracts import AuditResult, DirectorDecision, NarrationResult
from .specs import AGENT_SPECS, AgentRole, AgentSpec


class DMAgentFactory:
    def __init__(self, model: Any, tools: Optional[Dict[str, Any]] = None):
        self.model = model
        self.tools = dict(tools or {})

    def spec(self, role: AgentRole) -> AgentSpec:
        return AGENT_SPECS[role]

    def tools_for(self, role: AgentRole) -> list[Any]:
        spec = self.spec(role)
        missing = [name for name in spec.tool_names if name not in self.tools]
        if missing:
            raise KeyError(f"Missing tools for {role.value}: {', '.join(missing)}")
        return [self.tools[name] for name in spec.tool_names]

    def create(self, role: AgentRole):
        response_format = None
        if role == AgentRole.DIRECTOR:
            response_format = DirectorDecision
        elif role == AgentRole.NARRATOR:
            response_format = NarrationResult
        elif role == AgentRole.AUDITOR:
            response_format = AuditResult
        return create_agent(
            model=self.model,
            tools=self.tools_for(role),
            system_prompt=self.spec(role).system_prompt,
            response_format=response_format,
            name=f"dm_{role.value}_agent",
        )

    def create_many(self, roles: Iterable[AgentRole]) -> Dict[AgentRole, Any]:
        return {role: self.create(role) for role in roles}
