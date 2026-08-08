"""Pydantic contracts for the /api/ surface.

These models are the single source of truth for request/response shapes.
Run `python scripts/gen_ts_types.py` to regenerate frontend/src/types/api.generated.ts.
"""
from .characters import CharacterVoiceOut, SetCharacterIn, SetCharacterOut
from .lexicon import LexiconEntryOut, AddLexiconIn, AddLexiconOut, DeleteOut
from .pipeline import (
    PipelineTraceOut,
    PipelineStatusOut,
    PipelineStartOut,
    PipelineTraceDetailOut,
)
from .voices import (
    StockVoiceOut,
    VoiceDetailOut,
    VoiceCloneOut,
    CreateCloneOut,
    ListVoicesOut,
    ListClonesOut,
)
from .chapters import RerenderOut, WaveformOut
from .common import ErrorOut

__all__ = [
    "CharacterVoiceOut",
    "SetCharacterIn",
    "SetCharacterOut",
    "LexiconEntryOut",
    "AddLexiconIn",
    "AddLexiconOut",
    "DeleteOut",
    "PipelineTraceOut",
    "PipelineStatusOut",
    "PipelineStartOut",
    "PipelineTraceDetailOut",
    "StockVoiceOut",
    "VoiceDetailOut",
    "VoiceCloneOut",
    "CreateCloneOut",
    "ListVoicesOut",
    "ListClonesOut",
    "RerenderOut",
    "WaveformOut",
    "ErrorOut",
]
