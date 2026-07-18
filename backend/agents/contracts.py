"""Structured boundaries shared by the parent graph and agent subgraphs."""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class DirectorDecision(BaseModel):
    route: Literal["rules", "exploration", "combat", "downtime", "level_up"]
    objective: str = Field(min_length=1, max_length=500)
    requires_rules: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
    reason: str = Field(min_length=1, max_length=500)


class RuleBrief(BaseModel):
    answer: str
    queries: List[str] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class NarrationResult(BaseModel):
    response: str = Field(min_length=1)


class AuditResult(BaseModel):
    accepted: bool
    issues: List[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=1000)
