from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel


class RerenderOut(BaseModel):
    error: str


class WaveformOut(BaseModel):
    chapter_id: str
    duration_s: Optional[float]
    sample_rate: int
    peaks: List[Any]
    markers: List[Any]
