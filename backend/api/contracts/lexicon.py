from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LexiconEntryOut(BaseModel):
    id: str
    word: str
    ipa_phoneme: Optional[str]
    phonetic_spelling: Optional[str]
    context_note: Optional[str]
    source: str
    is_global: bool


class AddLexiconIn(BaseModel):
    word: str
    ipa_phoneme: Optional[str] = None
    phonetic_spelling: Optional[str] = None
    context_note: Optional[str] = None
    is_global: bool = False


class AddLexiconOut(BaseModel):
    id: str
    updated: Optional[bool] = None
    created: Optional[bool] = None


class DeleteOut(BaseModel):
    deleted: bool
