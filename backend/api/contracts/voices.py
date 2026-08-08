from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class StockVoiceOut(BaseModel):
    id: str
    slug: str
    display_name: str
    gender: str
    accent: str
    age_range: Optional[str]
    style_tags: Optional[List[str]]
    description: Optional[str]
    provider: str
    sample_audio_url: Optional[str]
    languages: Optional[List[str]]
    emotion_tags: Optional[List[str]]
    is_cloneable: bool


class VoiceDetailOut(StockVoiceOut):
    provider_voice_id: Optional[str]
    source: Optional[str]


class VoiceCloneOut(BaseModel):
    id: str
    name: str
    status: str
    provider: str
    reference_duration_seconds: float
    safety_similarity_score: Optional[float]
    created_at: str


class CreateCloneOut(BaseModel):
    error: str


ListVoicesOut = List[StockVoiceOut]
ListClonesOut = List[VoiceCloneOut]
