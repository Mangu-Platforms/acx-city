"""Base agent interface and shared utilities for the VoxEngine pipeline."""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("acx.pipeline")


@dataclass
class AgentResult:
    """Standardized output from each pipeline agent."""
    agent_name: str
    success: bool
    data: dict[str, Any]
    duration_ms: int = 0
    cost_usd: float = 0.0
    characters_in: int = 0
    characters_out: int = 0
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


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
            )
