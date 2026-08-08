"""Contracts for the canonical /api/voices surface (voice_catalog blueprint).

Shapes mirror backend/services/voice_catalog_endpoints.py serializers:
_serialize_voice, _serialize_voice_detail, _serialize_clone, and the
list/clone/preview endpoint envelopes.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class StockVoiceOut(BaseModel):
    id: str
    slug: str
    display_name: str
    gender: str
    accent: str
    age_range: Optional[str] = None
    style_tags: List[str]
    description: Optional[str] = None
    provider: str
    provider_voice_id: Optional[str] = None
    sample_audio_url: Optional[str] = None
    languages: List[str]
    emotion_tags: List[str]
    is_active: bool
    is_cloneable: bool
    source: str
    has_latent_embedding: bool
    created_at: Optional[str] = None


class ListVoicesOut(BaseModel):
    voices: List[StockVoiceOut]
    total: int
    page: int
    pages: int


class VoiceDetailOut(StockVoiceOut):
    latent_s3_key: Optional[str] = None
    organization_id: Optional[str] = None
    voice_city_voice_id: Optional[str] = None


class VoiceCloneOut(BaseModel):
    id: str
    name: str
    status: str
    provider: str
    reference_duration_seconds: Optional[float] = None
    safety_similarity_score: Optional[float] = None
    error: Optional[str] = None
    created_at: Optional[str] = None


class ListClonesOut(BaseModel):
    clones: List[VoiceCloneOut]
    total: int


class CreateCloneOut(BaseModel):
    clone_id: str
    name: str
    status: str
    message: str


class PreviewOut(BaseModel):
    preview_url: str
    expires_in: int
    voice_id: str
