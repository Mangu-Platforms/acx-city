from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class CharacterVoiceOut(BaseModel):
    id: str
    character_name: str
    voice_id: Optional[str]
    voice_slug: Optional[str]
    pitch_adjustment: float
    speed_adjustment: float
    base_emotion: str
    is_narrator: bool
    attribution_confidence: Optional[float]
    notes: Optional[str]


class SetCharacterIn(BaseModel):
    character_name: str
    voice_id: Optional[str] = None
    voice_slug: Optional[str] = None
    pitch_adjustment: float = 1.0
    speed_adjustment: float = 1.0
    base_emotion: str = "neutral"
    is_narrator: bool = False
    notes: Optional[str] = None


class SetCharacterOut(BaseModel):
    id: str
    updated: Optional[bool] = None
    created: Optional[bool] = None
