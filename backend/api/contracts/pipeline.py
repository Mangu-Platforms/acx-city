from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class PipelineTraceOut(BaseModel):
    chapter_number: int
    status: str
    current_agent: Optional[str]
    agent1_ms: Optional[int]
    agent2_ms: Optional[int]
    agent3_ms: Optional[int]
    agent4_ms: Optional[int]
    agent5_ms: Optional[int]
    qa_passed: Optional[bool]
    qa_completeness_score: Optional[float]
    error: Optional[str]


class PipelineStatusOut(BaseModel):
    job_id: str
    status: str
    chapters_total: int
    chapters_completed: int
    chapters_failed: int
    total_cost_usd: float
    traces: List[PipelineTraceOut]


class AgentTimingOut(BaseModel):
    ms: Optional[int]
    cost_usd: Optional[float] = None


class PipelineTraceDetailOut(BaseModel):
    id: str
    job_id: str
    chapter_number: int
    status: str
    current_agent: Optional[str]
    agents: Dict[str, AgentTimingOut]
    characters_in: Optional[Any]
    characters_out: Optional[Any]
    qa_passed: Optional[bool]
    qa_issues: Optional[Any]
    qa_completeness_score: Optional[float]
    error: Optional[str]


class PipelineStartOut(BaseModel):
    error: str
