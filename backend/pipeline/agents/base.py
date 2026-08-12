"""Base agent interface and shared utilities for the VoxEngine pipeline."""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("acx.pipeline")


@dataclass
class AgentResult:
    """Standardized output from each pipeline stage (P1.2 contract).

    Every stage returns this exact type, success or failure. A failed
    OPTIONAL stage never changes object type: it returns success=False with
    fallback_used=True and deterministic fallback_data that downstream
    stages consume in place of data.
    """
    agent_name: str
    success: bool
    data: dict[str, Any]
    duration_ms: int = 0
    cost_usd: float = 0.0
    characters_in: int = 0
    characters_out: int = 0
    error: Optional[str] = None
    error_code: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False
    fallback_data: Optional[dict[str, Any]] = None

    @property
    def effective_data(self) -> dict[str, Any]:
        """What downstream stages should consume: data on success, the
        deterministic fallback on failure (empty dict as last resort)."""
        if self.success:
            return self.data
        return self.fallback_data if self.fallback_data is not None else {}


def fallback_result(agent_name: str, error: str, fallback_data: dict[str, Any],
                    duration_ms: int = 0, error_code: str = "agent_failed") -> AgentResult:
    """Typed fallback for a failed optional stage — same shape, never a
    different object type, with deterministic downstream data."""
    return AgentResult(
        agent_name=agent_name,
        success=False,
        data={},
        duration_ms=duration_ms,
        error=error,
        error_code=error_code,
        fallback_used=True,
        fallback_data=fallback_data,
    )


class BaseAgent:
    """Base class for pipeline agents."""

    name: str = "base"

    def run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        """Execute the agent. Override in subclasses."""
        raise NotImplementedError

    def timed_run(self, input_data: dict[str, Any], context: dict[str, Any]) -> AgentResult:
        """Run with automatic timing."""
        start = time.monotonic()
        try:
            result = self.run(input_data, context)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception(f"Agent {self.name} failed after {duration_ms}ms")
            return AgentResult(
                agent_name=self.name,
                success=False,
                data={},
                duration_ms=duration_ms,
                error=str(exc),
                error_code="exception",
            )
